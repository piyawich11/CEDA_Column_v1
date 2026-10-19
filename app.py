"""CEDA RC Column Design – Streamlit front end for the ceda-column-design skill engine (engine/ = skill scripts).

Excel in, results out:
  1 upload ETABS exports + the CEDA input workbook (criteria, stories, connectivity, column sizes, combos, lap, …)
  2 the app shows every input, where it came from and what is missing (fill it in the workbook, upload again)
  3 confirm -> Run -> label → mark, Table of Column, calc sheets + back-up per mark, DXF, interaction surface
The app never re-implements the design rules.
"""
import os, json, hashlib, tempfile, collections
import pandas as pd
import streamlit as st
import app_io as AIO
import inputs as INP

st.set_page_config(page_title='CEDA Column Design', layout='wide')
st.title('CEDA RC Column Design')
st.caption(f'Engine = ceda-column-design skill v{AIO.ENGINE_VERSION} (bundled scripts). Units t, t-m, ksc. '
           'Draft outputs for engineer review – not construction drawings.')
ss = st.session_state
ss.setdefault('workdir', tempfile.mkdtemp(prefix='ceda_col_'))


def _h(files):
    m = hashlib.md5()
    for f in files or []:
        m.update(f.name.encode()); m.update(f.getvalue())
    return m.hexdigest()


@st.cache_data(show_spinner='Reading ETABS tables …')
def _read(key, blobs):
    parts, info = [], []
    d = tempfile.mkdtemp()
    for name, data in blobs:
        p = os.path.join(d, name); open(p, 'wb').write(data)
        t, u, i = AIO.read_upload(p)
        parts.append((t, u)); info += i
    T, U = AIO.merge(parts)
    return T, U, info


@st.cache_data(show_spinner=False)
def _read_tpl(key, name, data):
    p = os.path.join(tempfile.mkdtemp(), name); open(p, 'wb').write(data)
    return INP.read_template(p)


# ================================================================================================ 1 upload
st.header('1. Upload')
st.markdown('**ETABS exports** – one or more workbooks per model, all `TABLE:` blocks are merged '
            '(a combination sheet pasted without its header is read too).  \n'
            '**CEDA input workbook** – everything that is not in the ETABS export, or that you want to set yourself: '
            'design criteria, stories (order, elevations, basement, Lu, k, f\'c), connectivity per column, column sizes, '
            'load combinations, lap table, excluded combos, ρ approvals. Download the template below, fill it, upload it.')
c1, c2, c3, c4 = st.columns(4)
up = {}
for col, key, title in ((c1, 'seismic', '1.1 Seismic model (above ground)'), (c2, 'full_reduced', '1.2 Full model – reduced stiffness'),
                        (c3, 'full_unreduced', '1.3 Full model – unreduced (optional)')):
    fs = col.file_uploader(title, type=['xlsx', 'xlsm'], accept_multiple_files=True, key='up_' + key)
    up[key] = _read(_h(fs), [(f.name, f.getvalue()) for f in fs]) if fs else None
tf = c4.file_uploader('1.4 CEDA input workbook', type=['xlsx'], key='up_tpl')
tpl = _read_tpl(_h([tf]), tf.name, tf.getvalue()) if tf else dict(criteria={}, stories=[], columns=[], sections=[], combos_rows=[],
                                                                   combo_cases=[], lap_rows=[], exclude=[], approve=[], issues=[])
for m in up.values():
    for i in (m[2] if m else []):
        st.caption(i)
for i in tpl.get('issues', []):
    st.warning(i)

if not up['seismic'] and not up['full_reduced']:
    c4.download_button('⬇ Blank input workbook', INP.make_template(), 'CEDA_Column_Input.xlsx')
    st.info('Upload at least one ETABS model with "Element Forces - Columns".')
    st.stop()
upm = {k: (v[0], v[1]) if v else None for k, v in up.items()}
found = AIO.prepare(upm, tpl)['found']

# ================================================================================================ 2 inputs (screen = workbook)
st.header('2. Inputs – edit here or in the Excel workbook')
st.caption('Prefilled from the ETABS uploads and the input workbook. Changes here are used for the run and can be saved as an input '
           'workbook (button at the end of this section). Uploading another workbook resets the screen to that workbook.')
stamp = _h([f for k in ('seismic', 'full_reduced', 'full_unreduced') for f in (ss.get('up_' + k) or [])] + ([tf] if tf else []))
K = stamp[:10]                      # widget keys carry the upload stamp: a new upload starts fresh widgets from the files
if ss.get('ed_stamp') != stamp:
    for k in [k for k in ss.keys() if str(k).startswith('ed_') and not str(k).startswith('ed_' + K)]:
        del ss[k]
    ss['ed_stamp'] = stamp
cv = {k: (tpl['criteria'].get(k) if not INP._blank(tpl['criteria'].get(k)) else d) for k, d, u, n in INP.CRITERIA}
CAT, FRAME = ['ก', 'ข', 'ค', 'ง'], ['gravity', 'IMF', 'SMF']
FCS = [210, 240, 280, 320, 400, 450, 500, 560, 600, 700]
yn = lambda v: str(v).strip().upper().startswith('Y')


def W(container, key, label, kind='text', options=None, help_=None):
    """one criteria widget bound to the workbook key; returns the value in workbook form."""
    k = f'ed_{K}_c_' + key
    v = cv.get(key)
    if kind == 'yn':
        return 'Y' if container.checkbox(label, value=yn(v), key=k, help=help_) else 'N'
    if kind == 'sel':
        opts = [str(o) for o in options]
        sv = str(v) if v is not None else opts[0]
        return container.selectbox(label, opts, index=opts.index(sv) if sv in opts else 0, key=k, help=help_)
    if kind == 'num':
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        return container.number_input(label, value=fv, key=k, help=help_)
    if kind == 'optnum':
        s = container.text_input(label, value='' if INP._blank(v) else str(v), key=k, help=help_)
        return None if not s.strip() else float(s)
    return container.text_input(label, value='' if v is None else str(v), key=k, help=help_)


crit = {}
tb = st.tabs(['Project', 'Seismic', 'Materials & detailing', 'Stories / Lu / k', 'Columns (connectivity)', 'Sections',
              'Load combinations', 'Lap table', 'Marks & ranges', 'Exclude / ρ approval'])
with tb[0]:
    a_, b_ = st.columns(2)
    for i, (k, lab) in enumerate((('project.name', 'Project'), ('project.location', 'Location'), ('project.building', 'Building'),
                                  ('project.job', 'Job no. (file prefix)'), ('project.date', 'Date'), ('project.calc_by_1', 'Calculated by (name, licence)'),
                                  ('project.calc_by_2', 'Checked by (name, licence)'), ('project.approve_by', 'Approved by (name, licence)'))):
        crit[k] = W(a_ if i % 2 == 0 else b_, k, lab)
with tb[1]:
    a_, b_, c_ = st.columns(3)
    crit['seismic.design'] = W(a_, 'seismic.design', 'Seismic design required', 'yn')
    crit['seismic.category'] = W(b_, 'seismic.category', 'Seismic design category', 'sel', CAT)
    crit['seismic.frame'] = W(c_, 'seismic.frame', 'Columns are', 'sel', FRAME)
    crit['seismic.zone'] = W(a_, 'seismic.zone', 'Zone')
    crit['seismic.importance'] = W(b_, 'seismic.importance', 'Importance factor')
    crit['seismic.system'] = W(c_, 'seismic.system', 'Lateral system')
    crit['seismic.R'] = W(a_, 'seismic.R', 'R', 'num'); crit['seismic.Omega0'] = W(b_, 'seismic.Omega0', 'Ω0', 'num')
    crit['seismic.Cd'] = W(c_, 'seismic.Cd', 'Cd', 'num')
    if crit['seismic.category'] == 'ง':
        st.warning('Category ง with ordinary walls: height ≤ 60 m and seismic force +40 % (มยผ.) – check.')
    if crit['seismic.frame'] == 'SMF':
        st.warning('SMF detailing (ACI 18.7) is not automated – design forces only.')
with tb[2]:
    a_, b_, c_, d_ = st.columns(4)
    crit['materials.fc_typical'] = int(W(a_, 'materials.fc_typical', "Typical f'c (ksc, cylinder)", 'sel', FCS))
    crit['materials.fy'] = W(b_, 'materials.fy', 'fy (ksc)', 'num'); crit['materials.fyt'] = W(c_, 'materials.fyt', 'fyt (ksc)', 'num')
    crit['materials.fc_slab'] = W(d_, 'materials.fc_slab', "Slab f'c (ksc) – ACI 15.5", 'num')
    crit['materials.fc_mode'] = W(a_, 'materials.fc_mode', "Column f'c", 'sel', ['auto', 'fixed'],
                                  'auto = skill study (one reduction); fixed = bottom f\'c below the story given, or f\'c per story in Stories')
    crit['materials.fc_bottom'] = int(W(b_, 'materials.fc_bottom', "Bottom f'c (fixed)", 'sel', FCS))
    crit['materials.fc_reduce_at'] = W(c_, 'materials.fc_reduce_at', "Typical f'c from story (fixed)", 'sel', [''] + list(found['stories']))
    crit['detailing.cover_mm'] = W(d_, 'detailing.cover_mm', 'Cover to ties (mm)', 'num')
    crit['detailing.tie_db'] = int(W(a_, 'detailing.tie_db', 'Tie size (mm)', 'sel', [12, 16]))
    crit['detailing.size_restricted'] = W(b_, 'detailing.size_restricted', 'Column size restricted (ρ 6–8 % may be approved)', 'yn')
    crit['slender.k'] = W(c_, 'slender.k', 'Default k', 'num')
    crit['slender.beta_d'] = W(d_, 'slender.beta_d', 'βd (blank = from DL/SDL/LL cases)', 'optnum')
    crit['gravity.DL'] = W(a_, 'gravity.DL', 'DL case names'); crit['gravity.SDL'] = W(b_, 'gravity.SDL', 'SDL case names')
    crit['gravity.LL'] = W(c_, 'gravity.LL', 'LL case names')
    st.caption('Bar rules (fixed, skill §5): face ≤ 200 mm 2 bars, ≤ 540 mm 3, ≤ 660 mm 4, else c/c 125–150 mm; 1 % pattern; '
               'smallest bar by long side DB12/16/20; bundles DB32 at tie corners; ρ ≤ 6 %.')


def DF(rows, cols):
    return pd.DataFrame([list(r) + [None] * (len(cols) - len(r)) for r in rows], columns=cols)


def back(df):
    return [[None if (isinstance(v, float) and v != v) else v for v in r] for r in df.astype(object).where(pd.notna(df), None).values.tolist()
            if not all(x is None or (isinstance(x, str) and not x.strip()) or (isinstance(x, float) and x != x) for x in r)]


with tb[3]:
    st.markdown('Bottom → top. z gives Lu = z_top − z_bottom when ETABS has no connectivity; Lu_m / k override the whole story; '
                'basement Y (one model only); fc_ksc = fixed f\'c per story (fc mode fixed).')
    st0 = tpl['stories'] or [[s, *found['z'].get(s, (None, None)), None, None, None, None] for s in found['stories']]
    st_df = st.data_editor(DF(st0, INP.HDR['Stories']), hide_index=True, width='stretch', num_rows='dynamic', key=f'ed_{K}_stories',
                           column_config={'basement': st.column_config.SelectboxColumn(options=['', 'Y', 'N'])})
with tb[4]:
    st.markdown('Optional, one row per column-story: XY (m) for label matching between models, Lu / k for that column only.')
    co_df = st.data_editor(DF(tpl['columns'], INP.HDR['Columns']), hide_index=True, width='stretch', num_rows='dynamic', key=f'ed_{K}_columns')
with tb[5]:
    have = found['sec_of']
    if have:
        st.markdown('**Sizes read from ETABS**')
        st.dataframe(pd.DataFrame([dict(label=l, sizes=', '.join(f'{sh} {b}×{h}' + (' (name)' if a else '') for sh, b, h, a in sorted(s)))
                                   for l, s in sorted(have.items(), key=lambda kv: (len(kv[0]), kv[0]))]), hide_index=True, width='stretch')
    st.markdown('**Sizes set here** (replace ETABS for these labels; blank stories = all). b = t2 (My), h = t3 (Mx), mm.')
    se0 = tpl['sections'] or [[l, None, None, 'rect', None, None] for l in found['labels'] if l not in have]
    se_df = st.data_editor(DF(se0, INP.HDR['Sections']), hide_index=True, width='stretch', num_rows='dynamic', key=f'ed_{K}_sections',
                           column_config={'shape': st.column_config.SelectboxColumn(options=['rect', 'circ']),
                                          'story_from': st.column_config.SelectboxColumn(options=[''] + list(found['stories'])),
                                          'story_to': st.column_config.SelectboxColumn(options=[''] + list(found['stories']))})
with tb[6]:
    cases0 = tpl['combo_cases'] or list(found['cases']) or ['DL', 'SDL', 'LL', 'EQX', 'EQY']
    ctxt = st.text_input('Load case columns (ETABS load case names, comma separated)', ', '.join(cases0), key=f'ed_{K}_cases')
    cases = [c.strip() for c in ctxt.split(',') if c.strip()]
    st.markdown('Factors per ETABS load case for combos without a definition in ETABS, or to replace one (row here wins). '
                'Other load case names → use the Combos sheet of the workbook (its header sets the case names).')
    if tpl['combos_rows']:                       # map the workbook rows onto the current case columns
        cb0 = [[r[0]] + [dict(zip(cases0, r[1:])).get(c) for c in cases] for r in tpl['combos_rows']]
    else:
        cb0 = [[c] + [None] * len(cases) for c in found['undefined_only']]
    cb_df = st.data_editor(DF(cb0, ['combo'] + list(cases)), hide_index=True, width='stretch', num_rows='dynamic',
                           key=f'ed_{K}_combos_' + hashlib.md5(ctxt.encode()).hexdigest()[:8])
with tb[7]:
    st.markdown('Class B lap (S-00-04-04, "other bar"), mm. Blank = unknown → reported, never invented.')
    lp0 = tpl['lap_rows'] or [[f] + [INP.LAP_KNOWN.get(f, {}).get(d) for d in (12, 16, 20, 25, 28, 32)] for f in (400, 560)]
    lp_df = st.data_editor(DF(lp0, INP.HDR['Lap']), hide_index=True, width='stretch', num_rows='dynamic', key=f'ed_{K}_lap')
with tb[8]:
    a_, b_, c_ = st.columns(3)
    crit['marks.envelope'] = W(a_, 'marks.envelope', 'Mark envelope', 'yn')
    crit['marks.max_rows'] = int(W(b_, 'marks.max_rows', 'max rows that differ', 'num'))
    crit['marks.max_step'] = int(W(c_, 'marks.max_step', 'max ladder steps per row', 'num'))
    crit['marks.max_weight_pct'] = W(a_, 'marks.max_weight_pct', 'max extra longitudinal steel (%)', 'num')
    crit['story_ranges.mode'] = W(b_, 'story_ranges.mode', 'Story ranges', 'sel', ['auto', 'each'],
                                  'auto: basement every story, above ground 2–3 stories / 12 m + Lst')
with tb[9]:
    ex = st.multiselect('Exclude combos', found['combos'], default=[c for c in tpl['exclude'] if c in found['combos']], key=f'ed_{K}_excl')
    st.markdown('ρ 6–8 % approved (needs "Column size restricted"):')
    ap_df = st.data_editor(DF(tpl['approve'], INP.HDR['Approve_rho']), hide_index=True, width='stretch', num_rows='dynamic', key=f'ed_{K}_appr')

tpl_edit = dict(criteria=crit, stories=back(st_df), columns=back(co_df),
                sections=[r for r in back(se_df) if r[0] and r[4] is not None],
                combos_rows=[r for r in back(cb_df) if r[0] and any(v not in (None, '') for v in r[1:])], combo_cases=list(cases),
                lap_rows=back(lp_df), exclude=list(ex), approve=back(ap_df), issues=[])
tpl = tpl_edit
prep = AIO.prepare(upm, tpl)
single, eff, merge_rep, cfg_tpl = prep['single'], prep['eff'], prep['merge_rep'], prep['cfg_tpl']
scS, scR, labels, stories, combos, undefined = prep['scS'], prep['scR'], prep['labels'], prep['stories'], prep['combos'], prep['undefined']
label_story, found = prep['label_story'], prep['found']
st.download_button('⬇ Save the inputs on screen as an input workbook (Excel)', INP.make_template(found, tpl), 'CEDA_Column_Input.xlsx')

# ================================================================================================ 3 input check
st.header('3. Input check')
if single:
    st.warning('One model only: used for both the gravity and the seismic part – no basement load assembly (skill Rev.1).')
sec_ok = {l for l in labels if l in scS['sec_labels'] or l in scR['sec_labels']}
L_have = scR['L_keys'] | scS['L_keys']
ov_st = {s for o in cfg_tpl['slender']['overrides'] if 'Lu_m' in o and not o['labels'] for s in o['stories']}
ov_ls = {(l, s) for o in cfg_tpl['slender']['overrides'] if 'Lu_m' in o and o['labels'] for l in o['labels'] for s in o['stories']}
noL = sorted((l, s) for l, s in label_story if (l, s) not in L_have and s not in ov_st and (l, s) not in ov_ls)
order_src = 'tab Stories' if cfg_tpl['story_order'] else ('ETABS elevations' if scR['order_from_z'] or scS['order_from_z'] else 'natural order of names (ASSUMPTION)')
has_cases = scR['has_gravity_cases']
crit_src = ('input workbook + screen' if tf else 'screen (defaults where not changed)')
rows = [
    ('Column forces', 'ETABS Element Forces - Columns', f'{len(labels)} labels · {len(stories)} stories', True),
    ('Load combinations', 'ETABS definitions' + (' + tab Load combinations' if tpl['combos_rows'] else ''),
     'all defined' if not undefined else f'{len(undefined)} not defined: ' + ', '.join(undefined[:4]), not undefined),
    ('Column sizes', 'ETABS sections' + (' / tab Sections' if tpl['sections'] else ''),
     'all labels' if len(sec_ok) == len(labels) else 'missing: ' + ', '.join(sorted(set(labels) - sec_ok)[:8]), len(sec_ok) == len(labels)),
    ('Connectivity / Lu', 'ETABS connectivity' + (' / tabs Stories, Columns' if tpl['stories'] or tpl['columns'] else ''),
     'all column-stories' if not noL else f'{len(noL)} without Lu, e.g. ' + ', '.join(f'{a} {b}' for a, b in noL[:4]), not noL),
    ('Story order', order_src, ' → '.join(stories[:3]) + ' … ' + ' → '.join(stories[-2:]), True),
    ('βd', 'DL/SDL/LL load cases of the full model' if has_cases else 'Materials & detailing – βd',
     'per column-story (Rev.1)' if has_cases else (f"βd = {crit['slender.beta_d']}" if not INP._blank(crit['slender.beta_d']) else 'missing'),
     has_cases or not INP._blank(crit['slender.beta_d'])),
    ('Lap table', 'tab Lap table',
     ', '.join(f"{r[0]} ksc" for r in (tpl['lap_rows'] or [[400], [560]])), True),
    ('Design criteria', crit_src, f"f'c typ {crit['materials.fc_typical']} · category {crit['seismic.category']} · {crit['seismic.frame']}", True),
    ('Basement stories', 'engine (stories not in the seismic model)' if not single else 'tab Stories – basement',
     ', '.join(cfg_tpl['basement_stories']) or '–', True),
]
chk = pd.DataFrame(rows, columns=['input', 'source', 'content', 'ok'])
st.dataframe(chk.assign(ok=chk['ok'].map({True: '✔', False: '✖ fill in the tab above or the workbook'})), hide_index=True, width='stretch')
for r in merge_rep:
    st.caption('ℹ ' + r)
missing = not chk['ok'].all()

confirm = st.checkbox('I confirm the inputs and design criteria above (skill: never run before the criteria are confirmed)')
if missing:
    st.error('Some inputs are missing – fill them in the tabs above (or in the input workbook and upload it again).')


if st.button('▶ Run design', type='primary', disabled=not confirm or missing):
    with st.status('Running engine (run.py → make_outputs.py) …') as stt:
        try:
            cfg = AIO.build_cfg(prep, ss['workdir'])
            res, out = AIO.run_engine(ss['workdir'], cfg)
            json.dump(cfg, open(os.path.join(out, 'config_used.json'), 'w'), ensure_ascii=False, indent=1)
            open(os.path.join(out, 'CEDA_Column_Input_used.xlsx'), 'wb').write(INP.make_template(found, tpl))
            ss['out'] = out
            stt.update(label='Done', state='complete')
        except Exception as e:
            stt.update(label='Engine error', state='error'); st.exception(e); st.stop()
if 'out' not in ss:
    st.stop()

# ================================================================================================ 4 results
out = ss['out']
res = json.load(open(os.path.join(out, 'results.json')))
R = res['results']
st.header('4. Results')
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


def cell(r):
    d = AIO.LY.describe(r['counts'], r.get('phase', 0))
    return f"{r['nbar']}-DB{r['db']}" + (' (' + d.lower().replace('bundle ', 'b').replace(' @ tie corners', '') + ')' if d else '')


marks = sorted(set(res['marks'].values()), key=lambda m: int(m[1:]))
tabs = st.tabs(['Label → Mark', 'Table of Column', 'Interaction surface', 'DXF', 'Downloads', 'Decision (label × story)'])
with tabs[0]:
    rows = []
    for lab, mk in sorted(res['marks'].items(), key=lambda kv: (int(kv[1][1:]), kv[0])):
        rr = [r for r in R if r['label'] == lab]
        rows.append(dict(label=lab, mark=mk, section=f"{rr[0]['b']*10:.0f}×{rr[0]['h']*10:.0f}",
                         stories=f"{rr[0]['stories'][0]} → {rr[-1]['stories'][-1]}", rotated='yes' if rr[0].get('rotated') else '',
                         reference='●' if rr[0].get('ref') else '', max_DC=round(max(q['dc'] for r in rr for q in r['per']), 3),
                         status=', '.join(sorted({q['status'] for r in rr for q in r['per']}))))
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
with tabs[1]:
    bands = [tuple(b) for b in res['bands']]
    ref = {(r['mark'], tuple(r['band'])): r for r in R if r.get('ref')}
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
main_files, per_mark = AIO.files(out)
with tabs[3]:
    dxf = next((p for p, n, d in main_files if n.endswith('.dxf')), None)
    if dxf:
        @st.cache_data(show_spinner='Rendering DXF …')
        def _png(p, stamp):
            return AIO.dxf_png(p)
        st.download_button('Download DXF', open(dxf, 'rb').read(), os.path.basename(dxf))
        st.image(_png(dxf, os.path.getmtime(dxf)), width='stretch')
with tabs[4]:
    job = res['config']['project'].get('job', 'job')
    st.download_button('⬇ All outputs (ZIP)', AIO.zip_all(out), f'{job}_Column_outputs.zip', type='primary')
    st.download_button('⬇ Input workbook used (re-use / archive)', open(os.path.join(out, 'CEDA_Column_Input_used.xlsx'), 'rb').read(),
                       f'{job}_Column_Input_used.xlsx')
    st.subheader('Project files')
    for p, n, d in main_files:
        st.download_button(f'{n}  –  {d}', open(p, 'rb').read(), n, key='dl_' + n)
    st.subheader('Per mark: calculation sheets + back-up calculation')
    for mk_ in sorted(per_mark, key=lambda m: int(''.join(ch for ch in m if ch.isdigit()) or 0)):
        cA, cB, cC = st.columns([1, 2, 2])
        cA.markdown(f'**{mk_}** – ' + ', '.join(sorted(l for l, m in res['marks'].items() if m == mk_)))
        if 'Calc.pdf' in per_mark[mk_]:
            cB.download_button(f'{mk_} calculation (PDF)', open(per_mark[mk_]['Calc.pdf'], 'rb').read(), os.path.basename(per_mark[mk_]['Calc.pdf']), key='c_' + mk_)
        if 'Backup.xlsx' in per_mark[mk_]:
            cC.download_button(f'{mk_} back-up (Excel)', open(per_mark[mk_]['Backup.xlsx'], 'rb').read(), os.path.basename(per_mark[mk_]['Backup.xlsx']), key='b_' + mk_)
    st.subheader('Detailed CEDA-style Excel (one mark-range, on request)')
    a, b, c = st.columns(3)
    dmk = a.selectbox('Mark ', marks, key='dmk')
    dbd = b.selectbox('Story range ', [tuple(r['band']) for r in R if r['mark'] == dmk and r.get('ref')], format_func=lambda x: f'{x[0]} → {x[1]}', key='dbd')
    if c.button('Make detailed Excel'):
        p = AIO.detail_excel(out, dmk, dbd[0])
        st.download_button(f'Download {os.path.basename(p)}', open(p, 'rb').read(), os.path.basename(p))
with tabs[5]:
    rows = []
    for r in R:
        for q in r['per']:
            rows.append(dict(mark=r['mark'], label=r['label'], story=q['story'], drawing=f"{q['dwg'][0]}→{q['dwg'][1]}",
                             range=f"{r['band'][0]}→{r['band'][1]}", section=f"{r['b']*10:.0f}×{r['h']*10:.0f}", fc=q['fc'], bars=cell(r),
                             rho_pct=round(q['rho'] * 100, 2), DC=round(q['dc'], 3), gov_combo=q['gov'].get('combo', ''),
                             Pu_t=round(q['gov']['P'] / 1e3, 1), kLu_r=f"{q['slr_x']:.0f}/{q['slr_y']:.0f}",
                             delta_max=round(max(q['dmax_x'], q['dmax_y']), 2), shear_DC=round(max(v['dc_lo'] for v in q['shear'].values()), 2),
                             ties=f"{r['nset']}ป DB{r['tie_db']}@{r['so']}/{r['s']}", status=q['status']))
    df = pd.DataFrame(rows)
    flt = st.multiselect('Status', sorted(df['status'].unique()), default=sorted(df['status'].unique()))
    st.dataframe(df[df['status'].isin(flt)], hide_index=True, width='stretch')
    if (df['status'] == 'ASK_RHO').any():
        st.warning('ASK_RHO rows pass only with 6 % < ρ ≤ 8 %. To approve: Criteria detailing.size_restricted = Y and list them in '
                   'sheet Approve_rho of the input workbook, then upload and run again.')
