"""CEDA column design – main driver.

usage:  python3 -I run.py config.json OUTDIR
config: see SKILL.md (project, seismic, materials, detailing, slender, lap_table, inputs ...).
Writes OUTDIR/results.json, OUTDIR/<job>_Column_Decision.xlsx and returns quickly; drawings/calcs are made by
make_outputs.py from results.json.
"""
import sys, os, json, math, pickle, collections
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import etabs_io as E
import layout as LY
import design as DS

FC_STD = [210, 240, 280, 320, 400, 450, 500, 560, 600, 700]


def load_inputs(cfg, base):
    rep = {}
    inp = cfg['inputs']
    gn = cfg.get('gravity_cases')
    if 'forces_json' in inp:                                   # normalised rows (tests / adapters)
        data = json.load(open(os.path.join(base, inp['forces_json'])))
        return data['rows'], data.get('geometry', {}), data.get('stories'), {}, None
    rd = lambda k: dict(zip(('tables', 'units'), E.read_tables(os.path.join(base, inp[k])))) if inp.get(k) else None
    S, FR, FU = rd('seismic'), rd('full_reduced'), rd('full_unreduced')
    rows, rep = E.assemble(S, FR, FU, gn)
    excl = set(cfg.get('exclude_combos', []))
    rows = [q for q in rows if q['combo'] not in excl]
    geo = E.geometry(FR['tables'], FR['units'])
    # sway check (ACI 6.6.4.3) from the seismic model story tables, if exported
    gS = E.geometry(S['tables'], S['units'])
    sh = {}
    for (lab, st), g in gS.items():
        if 'L' in g:
            sh.setdefault(st, []).append(g['L'])
    sh = {k: sorted(v)[len(v) // 2] for k, v in sh.items()}
    facS, kindS = E.combo_factors(S['tables'], gn)
    rep['sway'] = E.sway_Q(S['tables'], S['units'], kindS, sh)
    secs = E.sections(FR['tables'], FR['units'])
    for k, g in geo.items():
        s = g.get('section')
        if s:
            g['dims'] = secs.get(s) or E.section_from_name(s)
    return rows, {f'{k[0]}|{k[1]}': v for k, v in geo.items()}, rep['stories_full'], rep, FR


def story_rank(s):
    """natural order of story names when ETABS connectivity is missing: B6 < … < B1 < GF/0.00 < 1st < 2F … < Roof."""
    import re as _re
    t = str(s).strip().upper()
    m = _re.match(r'^B(\d+)', t)
    if m:
        return -int(m.group(1))
    if t.startswith(('ROOF', 'RF', 'TOP')):
        return 10000
    m = _re.match(r'^(\d+(?:\.\d+)?)', t)
    if m:
        return float(m.group(1))
    if t in ('GF', 'G', 'GROUND'):
        return 0
    return 5000


def dwg_level(stories, s):
    i = stories.index(s)
    return (stories[i - 1] if i > 0 else 'FDN', s)


def main(cfg_path, outdir):
    cfg = json.load(open(cfg_path))
    base = os.path.dirname(os.path.abspath(cfg_path))
    os.makedirs(outdir, exist_ok=True)
    mat, det, sl = cfg['materials'], cfg.get('detailing', {}), cfg.get('slender', {})
    fy = mat.get('fy', 5000)
    cover = det.get('cover_mm', 40); tie_db = det.get('tie_db', 12)
    sizes = det.get('bar_sizes', [12, 16, 20, 25, 28, 32]); kmax = det.get('kmax', 4)
    cc = tuple(det.get('cc', [125, 150]))
    small = tuple(tuple(x) for x in det.get('small_face', LY.SMALL_FACE))
    rho_max, rho_ask = det.get('rho_max', 0.06), det.get('rho_ask', 0.08)
    approved = set(tuple(x) for x in cfg.get('approved_rho_over_6', []))
    frame = cfg.get('seismic', {}).get('frame', 'gravity')
    rows, geo, stories, rep_in, FR = load_inputs(cfg, base)
    notes = []
    for c in rep_in.get('combo_check_seismic', []) + rep_in.get('combo_check_full', []):
        if not c['ok'] and c['combo'] not in cfg.get('exclude_combos', []):
            notes.append(f"combo {c['combo']} ({c['kind']}) factors {c['factors']} do not match {c['expected']} – confirm or exclude")
    sw = [q for q in rep_in.get('sway', []) if q['sway']]
    if sw:
        notes.append(f"SWAY: Q > 0.05 at {sorted(set(q['story'] for q in sw))} – δs (ACI 6.6.4.6) not automated: STOP and ask")
    elif FR is not None and not rep_in.get('sway'):
        notes.append('sway check not done – export Story Forces + Story Drifts (seismic model)')
    if rep_in.get('basement_stories'):
        notes.append(f"basement stories assembled by the CEDA method: {rep_in['basement_stories']}")
    if frame == 'SMF':
        notes.append('SMF: ACI 18.7 detailing (Ash, s <= 6db, hx, strong column-weak beam) is NOT automated – design forces only.')
    # ---------------------------------------------------------------- group rows per column-story
    grp = collections.defaultdict(list)
    for r in rows:
        grp[(r['label'], r['story'])].append(r)
    if not stories:                                   # no connectivity exported: designer's story_order, else natural order
        so = cfg.get('story_order') or []
        stories = sorted(set(k[1] for k in grp), key=lambda s: (so.index(s), 0) if s in so else (len(so), story_rank(s)))
        notes.append('story order not from ETABS connectivity – ' + ('designer story_order used' if so else
                     'natural order of the story names used (ASSUMPTION – confirm)'))
    secs_cfg = cfg.get('sections', {})
    cols, grids, steps, jmin = {}, {}, {}, {}
    for (lab, st), rr in grp.items():
        g = geo.get(f'{lab}|{st}', {})
        d = secs_cfg.get(lab) or g.get('dims')
        if d is None:
            notes.append(f'{lab} {st}: no section – skipped'); continue
        if d.get('assumed'):
            notes.append(f'{lab} {st}: section dims from name "{g.get("section")}" (ASSUMPTION: first number = t3)')
        shape = d.get('shape', 'rect')
        b, h = (d['b'], d['h']) if 'b' in d else (d['t2'], d['t3'])          # b = t2 (M2), h = t3 (M3)
        Lu = g.get('L')
        Hst = g.get('L')                                  # story height (column length) before Lu overrides
        k = sl.get('k', 1.0)
        for ov in sl.get('overrides', []):
            if st in ov.get('stories', []) and (not ov.get('labels') or lab in ov['labels']):
                Lu = ov.get('Lu_m', Lu / 100 if Lu else None) * 100 if ov.get('Lu_m') else Lu
                k = ov.get('k', k)
        if Lu is None:
            Lu = sl.get('Lu_default_m', 3.0) * 100
            notes.append(f'{lab} {st}: Lu not found – {Lu/100:.2f} m used')
        bd = sl.get('beta_d')
        if bd is None and FR is not None:
            bd = E.beta_d(FR, lab, st, cfg.get('gravity_cases'))
        if bd is None:
            bd = 0.6; notes.append(f'{lab} {st}: βd not available – 0.6 used (ASSUMPTION)')
        gkey = (shape, b, h)
        if gkey not in grids:
            dmin = DS.min_bar_size(shape, b * 10, h * 10)
            sz = [d for d in sizes if d >= dmin] or [max(sizes)]
            grids[gkey] = LY.Grid(b * 10, h * 10, cover, tie_db, max(sz), cc, shape, small)
            steps[gkey] = LY.ladder(grids[gkey], sz, kmax)
            Ag = math.pi * b ** 2 / 4 if shape == 'circ' else b * h
            jmin[gkey] = DS.pattern_step(steps[gkey], Ag, det.get('rho_min', 0.01))
        arr = {key: np.array([q.get(key, 0.0) for q in rr], float) for key in ('P', 'M2', 'M3', 'V2', 'V3')}
        cols[(lab, st)] = dict(label=lab, story=st, shape=shape, b=b, h=h, Lu=Lu, k=k, betad=bd, gkey=gkey, rows=arr, H=Hst or Lu,
                              meta=[dict(combo=q['combo'], step=q.get('step', ''), model=q.get('model', ''), station=q.get('station', 0)) for q in rr],
                              seis=np.array([q.get('kind') in ('seismic', 'wind') for q in rr]))
    stories = [s for s in stories if any(k[1] == s for k in cols)]
    cache = DS.Cache()
    # ---------------------------------------------------------------- f'c
    if 'fc_by_story' in mat:
        fc_of = {s: mat['fc_by_story'].get(s, mat['fc_typical']) for s in stories}
        fcinfo = dict(fixed=True)
    else:
        fcinfo = DS.choose_fc(cache, grids, steps, cols, stories, mat.get('fc_list', FC_STD), mat['fc_typical'], fy, rho_max, jmin=jmin)
        ri = stories.index(fcinfo['reduce_at']) if fcinfo['reduce_at'] else len(stories)
        fc_of = {s: (fcinfo['fc_bottom'] if i < ri else fcinfo['fc_typical']) for i, s in enumerate(stories)}
    fcs = mat.get('fc_slab')
    if fcs:
        hi = sorted(set(s for s in stories if fc_of[s] > 1.4 * fcs))
        if hi:
            notes.append(f"ACI 15.5: column f'c > 1.4 × slab f'c ({fcs}) at {hi[0]}…{hi[-1]} – check joint (puddle / 15.5.2)")
    # ---------------------------------------------------------------- required step per label-story (CEDA v1.1)
    # 1 % pattern (positions from c/c 125-150, smallest bar by the long side) is the floor of every story;
    # bottom story: size up to DB32, then symmetric bundles at tie corners; going up: bundles first, then size.
    labels = sorted(set(k[0] for k in cols), key=lambda s: (len(s), s))
    req, status = {}, {}
    for lab in labels:
        p = {}
        for s in stories:
            if (lab, s) not in cols:
                continue
            c = cols[(lab, s)]
            r = DS.choose_step(cache, grids[c['gkey']], steps[c['gkey']], c, fc_of[s], fy,
                               rho_ask if (lab, s) in approved else rho_max, rho_ask, start=jmin[c['gkey']])
            p[s] = r['step']; status[(lab, s)] = r['status']
        ss = [s for s in stories if s in p]
        for i in range(len(ss) - 2, -1, -1):          # a story never carries less than the story above (same section, same f'c;
            # CEDA Oct 2026: at the f'c reduction the lower, stronger-concrete story may carry less steel than the story above)
            if cols[(lab, ss[i])]['gkey'] == cols[(lab, ss[i + 1])]['gkey'] and fc_of[ss[i]] == fc_of[ss[i + 1]]:
                p[ss[i]] = max(p[ss[i]], p[ss[i + 1]])
        req[lab] = p
    # ---------------------------------------------------------------- common story ranges (rows of the Table of Column)
    srcfg = cfg.get('story_ranges', {})
    basement = set(rep_in.get('basement_stories') or cfg.get('basement_stories', []))
    hs = collections.defaultdict(list)
    for (lab, s), c in cols.items():
        if c.get('H'):
            hs[s].append(c['H'] / 100)
    height_m = {s: sorted(v)[len(v) // 2] for s, v in hs.items()}
    laps = [float(v) for t in cfg.get('lap_table', {}).values() for v in t.values()]
    if srcfg.get('lst_m'):
        lst_m = float(srcfg['lst_m'])
    elif laps:
        lst_m = max(laps) / 1000
    else:
        lst_m = 2.0
        notes.append('story ranges: no lap table – Lst 2.0 m assumed for the 12 m bar check (ASSUMPTION)')
    lab_steps = {lab: steps[cols[next(k for k in cols if k[0] == lab)]['gkey']] for lab in labels}
    ranges = DS.story_ranges(stories, basement, height_m, fc_of, req, lab_steps, lst_m, srcfg.get('stock_m', 12.0),
                             srcfg.get('max_group', 3), srcfg.get('mode', 'auto'), srcfg.get('groups'))
    # each label: one step per range (governing story of the range), monotonic from the top down
    picks = {}
    for lab in labels:
        pr = {}
        for (s0, s1) in ranges:
            ss = [s for s in stories[stories.index(s0):stories.index(s1) + 1] if s in req[lab]]
            if ss:
                pr[(s0, s1)] = max(req[lab][s] for s in ss)
        keys = [r for r in ranges if r in pr]
        for i in range(len(keys) - 2, -1, -1):
            a_, b_ = keys[i], keys[i + 1]
            ga = next(cols[(lab, s)]['gkey'] for s in stories[stories.index(a_[0]):stories.index(a_[1]) + 1] if (lab, s) in cols)
            gb = next(cols[(lab, s)]['gkey'] for s in stories[stories.index(b_[0]):stories.index(b_[1]) + 1] if (lab, s) in cols)
            if ga == gb and fc_of[a_[0]] == fc_of[b_[0]]:
                pr[a_] = max(pr[a_], pr[b_])
            elif ga == gb:
                if pr[a_] < pr[b_]:
                    sa, sb = lab_steps[lab][pr[a_]], lab_steps[lab][pr[b_]]
                    notes.append(f"{lab}: less steel below the f'c change at {b_[0]} ({sum(sa[1])}-DB{sa[0]} below / {sum(sb[1])}-DB{sb[0]} above, "
                                 f"same grid) – bars change at {b_[0]}: splice there with Lst of the upper bars")
            else:
                notes.append(f"{lab}: section changes {ga[1]*10:.0f}×{ga[2]*10:.0f} → {gb[1]*10:.0f}×{gb[2]*10:.0f} at {b_[0]} – "
                             f"bar continuity / offset bars at the splice to be detailed by the engineer")
        picks[lab] = pr
    bnds = list(ranges)        # CEDA: every story range stays a row (no merging); a mark that runs on with the same
    if False:                  # bars is shown as merged cells (no dividing line) in the drawing
        newp = {}
        for lab in labels:
            newp[lab] = {}
            for (s0, s1) in bnds:
                i0, i1 = stories.index(s0), stories.index(s1)
                v = [j for (a_, b_), j in picks[lab].items() if i0 <= stories.index(a_) and stories.index(b_) <= i1]
                if v:
                    newp[lab][(s0, s1)] = max(v)
        picks = newp
    # 12 m stock: laps only where bundles <= 2 – flag a 3/4-bar bundle run longer than one bar can cover
    for lab in labels:
        run_h, run = 0.0, []
        for rg in bnds + [None]:
            j = picks[lab].get(rg) if rg else None
            big = j is not None and max(lab_steps[lab][j][1]) > 2
            if big:
                s0, s1 = rg
                run_h += sum(height_m.get(s, 3.0) for s in stories[stories.index(s0):stories.index(s1) + 1]); run.append(s0)
            else:
                if run and run_h + lst_m > srcfg.get('stock_m', 12.0):
                    notes.append(f'{lab}: 3/4-bar bundles over {run_h:.1f} m ({run[0]}…) – a lap inside the bundle zone cannot be '
                                 f'avoided with 12 m bars: coupler, or ACI 25.6.1.5 ×1.2/×1.33 on Lst')
                run_h, run = 0.0, []
    # ---------------------------------------------------------------- final evaluation per label-band
    so0, s0 = det.get('so_mm', 150), det.get('s_mm', 300)
    Ef = cfg.get('seismic', {}).get('imf_E_factor', 2.0)

    def final_eval(lab, pk, forced=None):
        """results of one label for the step picks pk {band: step}; forced {band: dict(so, s, extra)} = ties fixed by the mark."""
        out_l = []
        for (s0_, s1_) in bnds:
            ss = stories[stories.index(s0_):stories.index(s1_) + 1]
            have = [s for s in ss if (lab, s) in cols]
            if not have:
                continue
            j = pk[(s0_, s1_)]
            c0 = cols[(lab, have[0])]
            g = grids[c0['gkey']]
            db, counts = steps[c0['gkey']][j][0], steps[c0['gkey']][j][1]
            phase = steps[c0['gkey']][j][2] if len(steps[c0['gkey']][j]) > 2 else 0
            T = LY.ties(g, db)
            evs = [(cols[(lab, s)], DS.evaluate(cache, grids[cols[(lab, s)]['gkey']], cols[(lab, s)], fc_of[s], fy, db, counts), fc_of[s])
                   for s in have]
            fz = (forced or {}).get((s0_, s1_))
            if fz:
                res_ = [DS.shear_check(c, ev, T, fcs, tie_db, mat.get('fyt', 4000), fz['so'] / 10, fz['s'] / 10, frame, cover / 10, Ef,
                                       fz['extra']) for c, ev, fcs in evs]
                okk = all(max(r[k]['lo']['dc'], r[k]['mid']['dc']) <= 1.0 and r[k]['lo']['avmin_ok'] and r[k]['mid']['avmin_ok']
                          for r in res_ for k in ('V2', 'V3'))
                SH = dict(so=fz['so'], s=fz['s'], extra=fz['extra'], res=res_, ok=okk, note=fz.get('note', ''))
            else:
                SH = DS.design_shear(evs, T, tie_db, mat.get('fyt', 4000), so0, s0, frame, cover / 10, Ef)
            per = []
            for (c, ev, fcs), sh, s in zip(evs, SH['res'], have):
                it = DS.imf_ties(c, db, tie_db, SH['so'])
                gi = ev['gov']
                per.append(dict(story=s, dwg=dwg_level(stories, s), fc=fc_of[s], dc=ev['dcmax'], rho=ev['rho'], Lu=c['Lu'], k=c['k'],
                                betad=c['betad'], slr_x=ev['mg']['x']['slr'], slr_y=ev['mg']['y']['slr'],
                                dmax_x=float(np.max(ev['mg']['x']['delta'])), dmax_y=float(np.max(ev['mg']['y']['delta'])),
                                n_delta_14=int(np.sum((ev['mg']['x']['delta'] > 1.4) | (ev['mg']['y']['delta'] > 1.4))),
                                gov=dict(c['meta'][gi], P=float(c['rows']['P'][gi]), Mx=float(ev['mg']['x']['Md'][gi]),
                                         My=float(ev['mg']['y']['Md'][gi])),
                                shear={k_: dict(dc_lo=v['lo']['dc'], dc_mid=v['mid']['dc'], Ve=v['Ve'], legs=v['lo']['legs'],
                                               avmin_ok=v['lo']['avmin_ok'] and v['mid']['avmin_ok']) for k_, v in sh.items()},
                                ties=it, status=status.get((lab, s), 'OK') if ev['dcmax'] <= 1.0 or status.get((lab, s)) != 'OK' else 'REVISE'))
            kmax_used = max(counts)
            out_l.append(dict(label=lab, band=(s0_, s1_), stories=have, shape=c0['shape'], b=c0['b'], h=c0['h'], db=db,
                              counts=list(counts), nbar=sum(counts), phase=phase, fc=fc_of[have[0]], step=j, gkey=list(c0['gkey']),
                              As=sum(counts) * math.pi * db ** 2 / 400, nset=T['nset'], ncross=T['ncross'] + sum(SH['extra'].values()),
                              tie_db=tie_db, so=SH['so'], s=SH['s'], extra_legs=SH['extra'], shear_note=SH['note'], shear_ok=SH['ok'],
                              lap=DS.lap_length(cfg.get('lap_table', {}), fc_of[have[0]], db, kmax_used),
                              per=per, grid_notes=g.notes))
        return out_l

    res_of = {lab: final_eval(lab, picks[lab]) for lab in labels}
    # ---------------------------------------------------------------- marks (CEDA, Oct 2026)
    # same label = same mark in every story; labels with the same section (a 90° rotation counts as the same section),
    # same rows and same bars + ties share a mark; with mark_envelope on, a label may join a heavier mark when the
    # envelope differs from it in <= max_rows rows by <= max_step ladder steps and adds <= max_weight longitudinal steel.
    mcfg = dict(dict(envelope=True, max_rows=2, max_step=1, max_weight=0.20), **cfg.get('mark_envelope', {}))

    def canon_key(gk):
        return (gk[0], min(gk[1], gk[2]), max(gk[1], gk[2]))

    def is_rot(gk):
        return gk[0] == 'rect' and gk[1] > gk[2]

    def canon_grid(gk):
        ck = canon_key(gk)
        if ck not in grids:
            dmin = DS.min_bar_size(ck[0], ck[1] * 10, ck[2] * 10)
            sz = [d for d in sizes if d >= dmin] or [max(sizes)]
            grids[ck] = LY.Grid(ck[1] * 10, ck[2] * 10, cover, tie_db, max(sz), cc, ck[0], small)
            steps[ck] = LY.ladder(grids[ck], sz, kmax)
        return ck

    def bar_sig(gk, j):
        g = grids[gk]; db, counts = steps[gk][j][0], steps[gk][j][1]
        P, _ = g.positions(db)
        rot = is_rot(gk)
        return (db, tuple(sorted((round(p['y'] if rot else p['x'], 1), round(p['x'] if rot else p['y'], 1), c) for p, c in zip(P, counts))))

    sig_cache = {}

    def to_canon(gk, j):
        if not is_rot(gk):
            return j
        if (gk, j) not in sig_cache:
            ck = canon_grid(gk)
            target = bar_sig(gk, j)
            sig_cache[(gk, j)] = next((i for i in range(len(steps[ck])) if bar_sig(ck, i) == target), None)
        return sig_cache[(gk, j)]

    def from_canon(gk, i):
        if not is_rot(gk):
            return i
        ck = canon_grid(gk)
        target = bar_sig(ck, i)
        return next((j for j in range(len(steps[gk])) if bar_sig(gk, j) == target), None)

    def swap(e, rot):
        return {('Vx' if k == 'Vy' else 'Vy') if rot else k: v for k, v in e.items()}

    info = {}
    for lab in labels:
        R = res_of[lab]
        gk0 = tuple(R[0]['gkey'])
        rot = is_rot(gk0)
        V = {tuple(r['band']): to_canon(tuple(r['gkey']), r['step']) for r in R}
        ties_c = {tuple(r['band']): (r['so'], r['s'], tuple(sorted(swap(r['extra_legs'], rot).items()))) for r in R}
        H = {tuple(r['band']): sum(height_m.get(s, 3.0) for s in r['stories']) for r in R}
        gkey_rows = tuple((tuple(r['band']), canon_key(tuple(r['gkey']))) for r in R)
        info[lab] = dict(V=V, ties=ties_c, H=H, rot=rot, gk=gk0, group=gkey_rows, ok=all(v is not None for v in V.values()))

    def weight(lab, V):
        out_w = 0.0
        for bd, i in V.items():
            ck = canon_key(tuple(next(r['gkey'] for r in res_of[lab] if tuple(r['band']) == bd)))
            canon_grid(ck)
            out_w += DS._as(steps[ck][i]) * info[lab]['H'][bd]
        return out_w

    groups_m = collections.defaultdict(list)
    for lab in labels:
        groups_m[info[lab]['group']].append(lab)
    mark_list = []                    # dict(members, V, ties)
    for gkey_rows, labs in groups_m.items():
        labs = sorted(labs, key=lambda l: (-weight(l, info[l]['V']) if info[l]['ok'] else 0, len(l), l))
        local = []
        for lab in labs:
            I = info[lab]
            placed = False
            for m in local:
                if not I['ok'] or not all(info[x]['ok'] for x in m['members']):
                    continue
                if not mcfg['envelope']:
                    if m['V'] == I['V'] and m['ties'] == I['ties']:
                        m['members'].append(lab); placed = True; break
                    continue
                env = {bd: max(m['V'][bd], I['V'][bd]) for bd in m['V']}
                good = True
                for x in m['members'] + [lab]:
                    Vx = info[x]['V']
                    diff = [bd for bd in env if env[bd] != Vx[bd]]
                    if len(diff) > mcfg['max_rows'] or any(env[bd] - Vx[bd] > mcfg['max_step'] for bd in diff):
                        good = False; break
                    if weight(x, env) > (1 + mcfg['max_weight']) * weight(x, Vx) + 1e-9:
                        good = False; break
                if good:
                    m['V'] = env
                    m['members'].append(lab); placed = True; break
            if not placed:
                local.append(dict(members=[lab], V=dict(I['V']), ties=dict(I['ties'])))
        mark_list += local
    # ties of a mark: critical of its members (smallest so, s; most added legs) per row
    for m in mark_list:
        tz = {}
        for bd in m['V']:
            so_ = min(info[x]['ties'][bd][0] for x in m['members'])
            s_ = min(info[x]['ties'][bd][1] for x in m['members'])
            ex = {}
            for x in m['members']:
                for k_, v in info[x]['ties'][bd][2]:
                    ex[k_] = max(ex.get(k_, 0), v)
            tz[bd] = (so_, s_, ex)
        m['tz'] = tz
    # re-evaluate members whose bars or ties changed
    for m in mark_list:
        for lab in m['members']:
            I = info[lab]
            changed_b = any(m['V'][bd] != I['V'][bd] for bd in m['V'])
            changed_t = any((m['tz'][bd][0], m['tz'][bd][1], tuple(sorted(m['tz'][bd][2].items()))) != I['ties'][bd] for bd in m['V'])
            if not (changed_b or changed_t):
                continue
            pk = {}
            for r in res_of[lab]:
                bd = tuple(r['band'])
                j = from_canon(tuple(r['gkey']), m['V'][bd])
                pk[bd] = j if j is not None else r['step']
            forced = {bd: dict(so=m['tz'][bd][0], s=m['tz'][bd][1], extra=swap(m['tz'][bd][2], I['rot']),
                               note='ties = critical of the mark') for bd in m['V']}
            res_of[lab] = final_eval(lab, pk, forced)
            if changed_b:
                add = weight(lab, m['V']) / weight(lab, I['V']) - 1
                rows_ = [f'{bd[0]}-{bd[1]}' for bd in m['V'] if m['V'][bd] != I['V'][bd]]
                notes.append(f"mark envelope: {lab} takes the bars of {m['members'][0]} at {', '.join(rows_)} (+{add*100:.0f} % steel)")
    # numbering C1, C2 … by section size (largest first)
    def area(m):
        return max(r['b'] * r['h'] for x in m['members'] for r in res_of[x])
    mark_list.sort(key=lambda m: (-area(m), m['members'][0]))
    marks = {}
    results = []
    for i, m in enumerate(mark_list, 1):
        ref = m['members'][0]
        for lab in m['members']:
            marks[lab] = f'C{i}'
            for r in res_of[lab]:
                r['mark'] = f'C{i}'
                r['ref'] = lab == ref
                r['rotated'] = info[lab]['rot'] != info[ref]['rot']
                results.append(r)
        rots = [x for x in m['members'] if info[x]['rot'] != info[ref]['rot']]
        if rots:
            notes.append(f"C{i}: {', '.join(rots)} rotated 90° relative to {ref} – same mark, orientation to be shown on plan")
    out = dict(config=cfg, stories=stories, bands=bnds, ranges_before_merge=ranges, story_height_m=height_m, lst_m=lst_m, fc_of=fc_of, fcinfo=fcinfo, results=results, marks=marks,
               notes=list(dict.fromkeys(notes + sum((g.notes for g in grids.values()), []))), input_report=_jsonable(rep_in),
               grids={f'{k}': dict(shape=k[0], b=k[1], h=k[2]) for k in grids})
    json.dump(_jsonable(out), open(os.path.join(outdir, 'results.json'), 'w'), ensure_ascii=False, indent=1)
    pickle.dump(dict(cols=cols, grids=grids, steps=steps, fc_of=fc_of, stories=stories, cfg=cfg),
                open(os.path.join(outdir, 'state.pkl'), 'wb'))
    import outputs_table
    outputs_table.decision_table(out, os.path.join(outdir, f'{cfg["project"].get("job", "job")}_Column_Decision.xlsx'))
    return out


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k) if not isinstance(k, str) else k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not math.isfinite(o):
        return 'inf'
    return o


if __name__ == '__main__':
    o = main(sys.argv[1], sys.argv[2])
    print('labels', len(o['marks']), 'marks', len(set(o['marks'].values())), 'story ranges', o['bands'])
    for n in o['notes']:
        print('NOTE', n)
