"""CEDA RC Column Design – Streamlit front end for the ceda-column-design skill engine (engine/ = skill scripts v1.2).

Flow: upload ETABS exports -> confirm design criteria -> Run -> label → mark, Table of Column, calc sheets,
back-up Excel, DXF, interaction surface per mark / story range.  The app never re-implements the design rules.
"""
import os, io, json, hashlib, tempfile, collections
import pandas as pd
import streamlit as st
import app_io as AIO

st.set_page_config(page_title='CEDA Column Design', layout='wide')
st.title('CEDA RC Column Design')
st.caption(f'Engine = ceda-column-design skill v{AIO.ENGINE_VERSION} (bundled scripts, not re-implemented). '
           'Units: t, t-m, ksc. Draft outputs for engineer review – not construction drawings.')

ss = st.session_state
ss.setdefault('workdir', tempfile.mkdtemp(prefix='ceda_col_'))
ss.setdefault('approved', [])


def _h(files):
    m = hashlib.md5()
    for f in files or []:
        m.update(f.name.encode()); m.update(f.getvalue())
    return m.hexdigest()


@st.cache_data(show_spinner=False)
def _read(key, blobs):
    parts, info = [], []
    d = tempfile.mkdtemp()
    for name, data in blobs:
        p = os.path.join(d, name)
        open(p, 'wb').write(data)
        t, u, i = AIO.read_upload(p)
        parts.append((t, u)); info += i
    T, U = AIO.merge(parts)
    return T, U, info


def model_upload(col, key, title, help_):
    with col:
        fs = st.file_uploader(title, type=['xlsx', 'xlsm'], accept_multiple_files=True, key=key, help=help_)
    if not fs:
        return None
    return _read(_h(fs), [(f.name, f.getvalue()) for f in fs])


# ================================================================================================ 1 upload
st.header('1. Upload ETABS exports')
st.markdown('Each model may be one workbook or several (all `TABLE:` blocks are merged). A combination sheet pasted without '
            'the header (Name / Type / Auto / Load Name / Mode / SF) is also accepted.')
c1, c2, c3 = st.columns(3)
mS = model_upload(c1, 'upS', '1.1 Seismic model (above ground, reduced stiffness)',
                  'Element Forces – Columns (EQ combos incl. V2/V3), Load Combination Definitions, Column/Point Object Connectivity, '
                  'Frame Assignments – Section Properties, Concrete Rectangular/Circle, Story Forces, Story Drifts')
mR = model_upload(c2, 'upR', '1.2 Full model – reduced stiffness (with basement)',
                  'Gravity combos + load cases DL/SDL/LL (basement ΔP, βd), connectivity, sections')
mU = model_upload(c3, 'upU', '1.3 Full model – unreduced stiffness (optional)', 'Gravity combos')

if not mS and not mR:
    st.info('Upload at least the seismic model (or one model with all combos) to continue.')
    st.stop()

single = mR is None
if single:
    st.warning('Only one model uploaded: it is used for both the gravity and the seismic part. No basement load assembly '
               '(ข้อ Rev.1) is possible – basement columns must already be in the model forces.')
models = {'seismic': mS or mR, 'full_reduced': mR or mS, 'full_unreduced': mU}
inv = []
for k, m in models.items():
    if m is None:
        continue
    for row in AIO.inventory(m[0]):
        inv.append(dict(model=k, **row))
    for i in m[2]:
        st.caption(i)
with st.expander('Tables found in the uploads', expanded=False):
    st.dataframe(pd.DataFrame(inv), hide_index=True, width='stretch')

T_S, U_S = models['seismic'][0], models['seismic'][1]
T_R, U_R = models['full_reduced'][0], models['full_reduced'][1]
scS, scR = AIO.scan(T_S, U_S), AIO.scan(T_R, U_R)
labels = sorted(set(scS['labels']) | set(scR['labels']), key=lambda s: (len(s), s))
stories = scR['stories'] + [s for s in scS['stories'] if s not in scR['stories']]
combos = sorted(set(scS['combos']) | set(scR['combos']))
undefined = [c for c in combos if c not in set(scS['defined']) | set(scR['defined'])]
if not labels:
    st.error('No "Element Forces - Columns" rows found.')
    st.stop()
st.success(f'{len(labels)} column labels · {len(stories)} stories · {len(combos)} combos read.')

# ================================================================================================ 2 criteria
st.header('2. Design criteria (skill Step 1 – confirm before running)')
tab_p, tab_s, tab_m, tab_g, tab_c, tab_l, tab_o = st.tabs(['Project', 'Seismic', 'Materials & detailing', 'Sections / Lu / k',
                                                           'Load combinations', 'Lap table', 'Marks & story ranges'])
with tab_p:
    a, b = st.columns(2)
    P = dict(name=a.text_input('Project', ''), location=b.text_input('Location', ''), building=a.text_input('Building', ''),
             job=b.text_input('Job no. (file prefix)', 'JOB'), date=a.text_input('Date', ''))
    cb1 = b.text_input('Calculated by (name, licence)', '')
    cb2 = a.text_input('Checked by (name, licence)', '')
    ap = b.text_input('Approved by (name, licence)', '')
    split = lambda s: [x.strip() for x in (s.split(',', 1) + [''])[:2]]
    P.update(calc_by=[split(cb1), split(cb2)], approve_by=split(ap))
with tab_s:
    a, b, c = st.columns(3)
    seis = dict(design=a.checkbox('Seismic design required', True), zone=b.text_input('Zone', ''), importance=c.text_input('Importance factor', ''),
                category=a.selectbox('Seismic design category', ['ก', 'ข', 'ค', 'ง']), system=b.text_input('Lateral system', 'Building frame + ordinary RC shear wall'),
                R=c.number_input('R', value=5.0), Omega0=a.number_input('Ω0', value=2.5), Cd=b.number_input('Cd', value=4.5),
                frame=c.selectbox('Columns are', ['gravity', 'IMF', 'SMF']), imf_E_factor=2.0)
    if seis['category'] == 'ง':
        st.warning('Category ง with ordinary walls: height ≤ 60 m and seismic force +40 % (มยผ.) – check.')
    if seis['frame'] == 'SMF':
        st.warning('SMF detailing (ACI 18.7) is not automated – design forces only.')
with tab_m:
    a, b, c, d = st.columns(4)
    fc_typ = a.selectbox("Typical f'c of the project (ksc, cylinder)", [210, 240, 280, 320, 400, 450, 500, 560, 600, 700], index=4)
    fy = b.number_input('fy (ksc)', value=5000.0); fyt = c.number_input('fyt (ksc)', value=4000.0)
    fc_slab = d.number_input("Slab f'c (ksc) – ACI 15.5", value=320.0)
    fc_mode = a.radio("Column f'c", ['Auto study (one reduction, skill rule)', 'Fixed by me'], horizontal=False)
    fc_by_story = None
    if fc_mode.startswith('Fixed'):
        fb = b.selectbox("Bottom f'c (ksc)", [210, 240, 280, 320, 400, 450, 500, 560, 600, 700], index=7)
        red = c.selectbox("Reduce to typical f'c from story", stories, index=min(len(stories) - 1, len(stories) // 3))
        fc_by_story = {s: (fb if stories.index(s) < stories.index(red) else fc_typ) for s in stories}
    cover = a.number_input('Cover to ties (mm)', value=40); tie_db = b.selectbox('Tie size', [12, 16], index=0)
    restricted = c.checkbox('Column size restricted (ρ 6–8 % may be approved)', False)
    st.caption('Bar rules (fixed, skill §5): face ≤ 200 mm 2 bars, ≤ 540 mm 3, ≤ 660 mm 4, else c/c 125–150 mm; 1 % pattern; '
               'smallest bar by long side DB12/16/20; bundles DB32 at tie corners; ρ ≤ 6 %.')
with tab_g:
    st.markdown('**Sections** (b = t2 → My, h = t3 → Mx). Labels with a section in ETABS are read from the model.')
    known = {**scS['sec_of'], **scR['sec_of']}
    srows = []
    for lab in labels:
        s = known.get(lab)
        if s:
            for shape, b_, h_, assumed in sorted(s):
                srows.append(dict(label=lab, shape=shape, b_mm=b_, h_mm=h_, source='ETABS name (ASSUMPTION)' if assumed else 'ETABS'))
        else:
            srows.append(dict(label=lab, shape='rect', b_mm=None, h_mm=None, source='enter'))
    sec_df = st.data_editor(pd.DataFrame(srows), hide_index=True, width='stretch', key='sec',
                            disabled=['label', 'source'], column_config={'shape': st.column_config.SelectboxColumn(options=['rect', 'circ'])})
    st.markdown('**Lu / k per story** – leave Lu blank to use the column length from ETABS connectivity.')
    has_L = bool(scR['Lu'] or scS['Lu'])
    lrows = [dict(story=s, Lu_ETABS_m=(scR['Lu'].get(s) or scS['Lu'].get(s)), Lu_override_m=None, k=1.0) for s in stories]
    lu_df = st.data_editor(pd.DataFrame(lrows), hide_index=True, width='stretch', key='lu', disabled=['story', 'Lu_ETABS_m'])
    if not has_L:
        st.warning('No connectivity in the uploads – enter Lu for every story.')
    st.markdown('**Story order (bottom → top)** – from ETABS elevations when connectivity is exported, otherwise natural order.')
    order_txt = st.text_area('one story per line', '\n'.join(stories), height=120)
    story_order = [x.strip() for x in order_txt.splitlines() if x.strip()]
    bd = st.number_input('βd (only used when DL/SDL/LL load cases are not exported; skill Rev.1 computes it per column-story)', value=0.0,
                         help='0 = compute from load cases')
with tab_c:
    if undefined:
        st.warning(f'{len(undefined)} combos have no Load Combination Definitions. Enter their factors (never judged by name).')
        cdf = st.data_editor(pd.DataFrame([dict(combo=c, DL=None, SDL=None, LL=None, E=None, W=None) for c in undefined]),
                             hide_index=True, width='stretch', key='cmb', disabled=['combo'])
    else:
        cdf = None
        st.success('All combos are defined in the uploads; the ข้อ 7 check runs on their factors.')
    excl = st.multiselect('Exclude combos', combos, help='e.g. cross-standard U_B combos')
with tab_l:
    st.markdown('Class B lap (S-00-04-04, "other bar"), mm. Blank = unknown → reported, never invented.')
    fcs = sorted({fc_typ} | ({*fc_by_story.values()} if fc_by_story else {560, fc_typ}))
    lap_df = st.data_editor(pd.DataFrame([{"f'c": f, **{f'DB{d}': AIO.LAP_KNOWN.get(f, {}).get(d) for d in (16, 20, 25, 28, 32)}} for f in fcs]),
                            hide_index=True, width='stretch', key='lap', num_rows='dynamic')
with tab_o:
    a, b, c = st.columns(3)
    env = a.checkbox('Mark envelope', True)
    mr = b.number_input('max rows that differ', value=2, min_value=0); ms_ = c.number_input('max ladder steps per row', value=1, min_value=0)
    mw = a.number_input('max extra longitudinal steel (%)', value=20.0)
    srm = b.selectbox('Story ranges', ['auto', 'each'], help='auto: basement every story, above ground 2–3 stories / 12 m + Lst')
    if single:
        base = c.multiselect('Basement stories', stories)
    else:
        base = []

# ------------------------------------------------------------------------------------------------ checks before run
problems = []
for _, r in sec_df.iterrows():
    if pd.isna(r['b_mm']) or pd.isna(r['h_mm']):
        problems.append(f"section of {r['label']}")
if not has_L and lu_df['Lu_override_m'].isna().any():
    problems.append('Lu of every story')
if cdf is not None and cdf[['DL', 'SDL', 'LL', 'E', 'W']].isna().all(axis=1).any():
    problems.append('factors of every undefined combo')
confirm = st.checkbox('I confirm the design criteria above (skill: never run before the criteria are confirmed)')
if problems:
    st.error('Missing: ' + ', '.join(problems[:8]) + (' …' if len(problems) > 8 else ''))


def build_cfg():
    wd = ss['workdir']
    T_R2 = dict(T_R)
    T_S2 = dict(T_S)
    if cdf is not None:
        rows = AIO.synth_combos(cdf.to_dict('records'))
        for TT in (T_S2, T_R2):
            TT['Load Combination Definitions'] = list(TT.get('Load Combination Definitions', [])) + rows
    paths = {}
    AIO.write_tables(os.path.join(wd, 'seismic.xlsx'), T_S2, U_S); paths['seismic'] = 'seismic.xlsx'
    AIO.write_tables(os.path.join(wd, 'full_reduced.xlsx'), T_R2, U_R); paths['full_reduced'] = 'full_reduced.xlsx'
    if mU:
        AIO.write_tables(os.path.join(wd, 'full_unreduced.xlsx'), mU[0], mU[1]); paths['full_unreduced'] = 'full_unreduced.xlsx'
    secs = {}
    for _, r in sec_df.iterrows():
        if r['source'] == 'enter':
            secs[r['label']] = dict(shape=r['shape'], b=float(r['b_mm']) / 10, h=float(r['h_mm']) / 10)
    ov = []
    for _, r in lu_df.iterrows():
        if not pd.isna(r['Lu_override_m']) or float(r['k']) != 1.0:
            o = dict(stories=[r['story']], labels=[], k=float(r['k']))
            if not pd.isna(r['Lu_override_m']):
                o['Lu_m'] = float(r['Lu_override_m'])
            ov.append(o)
    lap = {}
    for _, r in lap_df.iterrows():
        if pd.isna(r["f'c"]):
            continue
        lap[str(int(r["f'c"]))] = {k[2:]: float(v) for k, v in r.items() if k.startswith('DB') and not pd.isna(v)}
    mat = dict(fy=fy, fyt=fyt, fc_typical=fc_typ, fc_slab=fc_slab, fc_list=[210, 240, 280, 320, 400, 450, 500, 560, 600, 700])
    if fc_by_story:
        mat['fc_by_story'] = fc_by_story
    cfg = dict(project=P, seismic=seis, materials=mat,
               detailing=dict(cover_mm=cover, tie_db=tie_db, kmax=4, cc=[125, 150], rho_max=0.06, rho_ask=0.08, so_mm=150, s_mm=300,
                              rho_min=0.01, small_face=[[200, 2], [540, 3], [660, 4]]),
               slender=dict(k=1.0, beta_d=(bd or None), overrides=ov, Lu_default_m=3.0),
               sections=secs, lap_table=lap, exclude_combos=excl,
               approved_rho_over_6=[list(x) for x in ss['approved']] if restricted else [],
               inputs=paths, story_ranges=dict(mode=srm, max_group=3, stock_m=12.0, lst_m=None, groups=[]),
               basement_stories=base, story_order=story_order,
               mark_envelope=dict(envelope=env, max_rows=int(mr), max_step=int(ms_), max_weight=mw / 100))
    return cfg


if st.button('▶ Run design', type='primary', disabled=not confirm or bool(problems)):
    with st.status('Running engine (run.py → make_outputs.py) …', expanded=False) as stt:
        try:
            log = []
            res, out = AIO.run_engine(ss['workdir'], build_cfg(), log)
            ss['out'] = out
            stt.update(label='Done', state='complete')
        except Exception as e:                      # show the engine error as is
            stt.update(label='Engine error', state='error')
            st.exception(e)
            st.stop()

if 'out' not in ss:
    st.stop()

# ================================================================================================ 3 results
out = ss['out']
res = json.load(open(os.path.join(out, 'results.json')))
R = res['results']
st.header('3. Results')
nask = sum(1 for r in R for q in r['per'] if q['status'] == 'ASK_RHO')
nrev = sum(1 for r in R for q in r['per'] if q['status'] == 'REVISE')
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric('Labels', len(res['marks'])); m2.metric('Marks', len(set(res['marks'].values())))
m3.metric('Story ranges (rows)', len(res['bands'])); m4.metric('ASK ρ 6–8 %', nask); m5.metric('REVISE', nrev)

with st.expander(f"Review checkpoints / notes ({len(res['notes'])})", expanded=bool(nask or nrev)):
    for n in res['notes']:
        (st.error if n.startswith(('SWAY', 'combo')) else st.warning)(n)
    fi = res.get('fcinfo', {})
    if fi and not fi.get('fixed'):
        st.info(f"f'c study: bottom {fi.get('fc_bottom')} ksc, reduce to {fi.get('fc_typical')} ksc at {fi.get('reduce_at')}")
        if fi.get('table'):
            st.dataframe(pd.DataFrame(fi['table']), hide_index=True)

tabs = st.tabs(['Label → Mark', 'Table of Column', 'Interaction surface', 'DXF', 'Downloads', 'Decision (label × story)'])

# ---- label -> mark
with tabs[0]:
    rows = []
    for lab, mk in sorted(res['marks'].items(), key=lambda kv: (int(kv[1][1:]), kv[0])):
        rr = [r for r in R if r['label'] == lab]
        rows.append(dict(label=lab, mark=mk, section=f"{rr[0]['b']*10:.0f}×{rr[0]['h']*10:.0f}",
                         stories=f"{rr[0]['stories'][0]} → {rr[-1]['stories'][-1]}" if rr else '',
                         rotated='yes' if rr and rr[0].get('rotated') else '', reference='●' if rr and rr[0].get('ref') else '',
                         max_DC=round(max(q['dc'] for r in rr for q in r['per']), 3),
                         status=', '.join(sorted({q['status'] for r in rr for q in r['per']}))))
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

# ---- schedule
def cell(r):
    t = f"{r['nbar']}-DB{r['db']}"
    d = AIO.LY.describe(r['counts'], r.get('phase', 0))
    return t + (' (' + d.lower().replace('bundle ', 'b').replace(' @ tie corners', '') + ')' if d else '')


with tabs[1]:
    marks = sorted(set(res['marks'].values()), key=lambda m: int(m[1:]))
    bands = [tuple(b) for b in res['bands']]
    ref = {}
    for r in R:
        if r.get('ref'):
            ref[(r['mark'], tuple(r['band']))] = r
    grid = []
    for b in reversed(bands):
        row = {'story range': f'{b[0]} → {b[1]}', "f'c": res['fc_of'][b[0]]}
        for m in marks:
            r = ref.get((m, b))
            if r:
                dcm = max(q['dc'] for x in R if x['mark'] == m and tuple(x['band']) == b for q in x['per'])
                row[m] = f"{r['b']*10:.0f}×{r['h']*10:.0f} | {cell(r)} | {r['nset']}ป DB{r['tie_db']}@{r['so']}/{r['s']} | D/C {dcm:.2f}"
            else:
                row[m] = ''
        grid.append(row)
    st.dataframe(pd.DataFrame(grid), hide_index=True, width='stretch', height=min(800, 60 + 36 * len(grid)))
    st.caption('Draft schedule (reference label orientation). Same bars in consecutive rows are merged cells in the DXF.')

# ---- surface
with tabs[2]:
    a, b = st.columns(2)
    mk = a.selectbox('Mark', marks, key='smk')
    bl = [tuple(r['band']) for r in R if r['mark'] == mk and r.get('ref')]
    bsel = b.selectbox('Story range', bl, format_func=lambda x: f'{x[0]} → {x[1]}', key='sbd')

    @st.cache_resource(show_spinner='Building the interaction surface …')
    def _surf(out_, mk_, b_, stamp):
        return AIO.surface_figures(AIO.mark_band_eval(out_, mk_, b_))
    f3, f2, fc_, gov = _surf(out, mk, bsel, os.path.getmtime(os.path.join(out, 'results.json')))
    r = gov['r']
    st.markdown(f"**{mk}  {bsel[0]} → {bsel[1]}** · {r['b']*10:.0f}×{r['h']*10:.0f} mm · {cell(r)} · f'c {res['fc_of'][bsel[0]]} ksc · "
                f"governing {gov['label']} {gov['story']} – D/C **{gov['ev']['dcmax']:.3f}**")
    st.plotly_chart(f3, width='stretch')
    x1, x2, x3 = st.columns(3)
    x1.plotly_chart(f2[0], width='stretch'); x2.plotly_chart(f2[1], width='stretch'); x3.plotly_chart(fc_, width='stretch')

# ---- DXF
main_files, per_mark = AIO.files(out)
with tabs[3]:
    dxf = next((p for p, n, d in main_files if n.endswith('.dxf')), None)
    if dxf:
        @st.cache_data(show_spinner='Rendering DXF …')
        def _png(p, stamp):
            return AIO.dxf_png(p)
        st.image(_png(dxf, os.path.getmtime(dxf)), width='stretch')
        st.download_button('Download DXF', open(dxf, 'rb').read(), os.path.basename(dxf))
        st.caption('Layers: G-ANNO-TEXT, A-DETL-GENF, CED_0_10/13/18_Solid, S-DIMS; [CHECK] lines on G-ANNO-CHECK – freeze before issue.')

# ---- downloads
with tabs[4]:
    st.download_button('⬇ All outputs (ZIP)', AIO.zip_all(out), f"{res['config']['project'].get('job', 'job')}_Column_outputs.zip", type='primary')
    st.subheader('Project files')
    for p, n, d in main_files:
        st.download_button(f'{n}  –  {d}', open(p, 'rb').read(), n, key='dl_' + n)
    st.subheader('Per mark: calculation sheets + back-up calculation')
    for mk_ in sorted(per_mark, key=lambda m: int(''.join(ch for ch in m if ch.isdigit()) or 0)):
        cA, cB, cC = st.columns([1, 2, 2])
        cA.markdown(f'**{mk_}** – ' + ', '.join(sorted(l for l, m in res['marks'].items() if m == mk_)))
        if 'Calc.pdf' in per_mark[mk_]:
            cB.download_button(f'{mk_} calculation (PDF)', open(per_mark[mk_]['Calc.pdf'], 'rb').read(),
                               os.path.basename(per_mark[mk_]['Calc.pdf']), key='c_' + mk_)
        if 'Backup.xlsx' in per_mark[mk_]:
            cC.download_button(f'{mk_} back-up (Excel)', open(per_mark[mk_]['Backup.xlsx'], 'rb').read(),
                               os.path.basename(per_mark[mk_]['Backup.xlsx']), key='b_' + mk_)
    st.subheader('Detailed CEDA-style Excel (one mark-range, on request)')
    a, b, c = st.columns(3)
    dmk = a.selectbox('Mark ', marks, key='dmk')
    dbl = [tuple(r['band']) for r in R if r['mark'] == dmk and r.get('ref')]
    dbd = b.selectbox('Story range ', dbl, format_func=lambda x: f'{x[0]} → {x[1]}', key='dbd')
    if c.button('Make detailed Excel'):
        p = AIO.detail_excel(out, dmk, dbd[0])
        st.download_button(f'Download {os.path.basename(p)}', open(p, 'rb').read(), os.path.basename(p))
    st.caption('Excel files contain live formulas – Excel recalculates them on opening.')

# ---- decision
with tabs[5]:
    rows = []
    for r in R:
        for q in r['per']:
            rows.append(dict(mark=r['mark'], label=r['label'], story=q['story'], drawing=f"{q['dwg'][0]}→{q['dwg'][1]}",
                             range=f"{r['band'][0]}→{r['band'][1]}", section=f"{r['b']*10:.0f}×{r['h']*10:.0f}", fc=q['fc'], bars=cell(r),
                             rho_pct=round(q['rho'] * 100, 2), DC=round(q['dc'], 3), gov_combo=q['gov'].get('combo', ''),
                             Pu_t=round(q['gov']['P'] / 1e3, 1), kLu_r=f"{q['slr_x']:.0f}/{q['slr_y']:.0f}",
                             delta_max=round(max(q['dmax_x'], q['dmax_y']), 2),
                             shear_DC=round(max(v['dc_lo'] for v in q['shear'].values()), 2),
                             ties=f"{r['nset']}ป DB{r['tie_db']}@{r['so']}/{r['s']}", status=q['status']))
    df = pd.DataFrame(rows)
    flt = st.multiselect('Status', sorted(df['status'].unique()), default=sorted(df['status'].unique()))
    st.dataframe(df[df['status'].isin(flt)], hide_index=True, width='stretch')
    ask = df[df['status'] == 'ASK_RHO']
    if len(ask):
        st.warning('ASK_RHO: passes only with 6 % < ρ ≤ 8 %. Approve (column size restricted) and run again.')
        pick = st.multiselect('Approve ρ > 6 % for', [f'{a}|{b}' for a, b in zip(ask['label'], ask['story'])])
        if st.button('Save approvals (then tick "Column size restricted" and Run again)'):
            ss['approved'] = [p.split('|') for p in pick]
            st.success(f'{len(pick)} approvals saved.')
