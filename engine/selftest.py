"""Self-test – must print ALL PASS before real use.
usage: python3 -I selftest.py <scripts folder>   (run from an empty scratch folder)
T1 layout rules (grid c/c 125-150, symmetric ties, bundle ladder) on C1 2000x450
T2 C1 (VOCO) end-to-end with the v1.1 rule (1 % pattern, bottom-up, common story ranges) – Oct 2026
T5 small-face bar count (<=200: 2, <=540: 3, <=660: 4, else c/c 125-150) and singles clear spacing
T6 marks: same section incl. 90° rotation, ties in the mark, envelope (<=2 rows, <=1 step, <=20 % steel), no-envelope mode
T4 common story ranges (basement every story, 12 m + Lst, f'c break, early break on bundle removal / half steel)
T3 ETABS reader + basement load assembly on a synthetic 4-story model (hand-checked values)
"""
import sys, os, json, subprocess, tempfile, shutil
HERE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
fails = []


def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info else ''))
    if not cond:
        fails.append(name)


import layout as LY
g = LY.Grid(450, 2000, 40, 12, 32)
check('T1 grid 2000 face: 14 positions, c/c 143', g.nh == 14 and abs(g.sp_h - 143.4) < 0.5, f'{g.nh} {g.sp_h:.1f}')
check('T1 grid 450 face: 3 bars by the small-face rule, no note', g.nb == 3 and len(g.notes) == 0)
T = LY.ties(g, 32)
check('T1 ties symmetric 4 closed hoops, no crosstie', T['nset'] == 4 and T['ncross'] == 0 and T['sup_h'] == [0, 2, 4, 6, 7, 9, 11, 13])
check('T1 support pattern m=12 (CEDA sketch)', LY._support_pattern(12) == [0, 1, 3, 5, 6, 8, 10, 11])
st = LY.ladder(g, (25, 28, 32))
n = [sum(s[1]) * 1 for s in st]
import design as DS
check('T1 min bar by long side 200/201/500/501/2000 -> 12/16/16/20/20',
      [DS.min_bar_size('rect', 200, b) for b in (200, 201, 500, 501, 2000)] == [12, 16, 16, 20, 20])
st20 = LY.ladder(g, (20, 25, 28, 32))
check('T1 C1 1 % pattern = 30-DB20 (94.2 >= 90 cm2)', st20[DS.pattern_step(st20, 45 * 200)][0] == 20 and sum(st20[DS.pattern_step(st20, 45 * 200)][1]) == 30)
check('T1 ladder 30..58 tie corners then 62.. other positions', n[:10] == [30, 30, 30, 34, 38, 42, 46, 50, 54, 58] and st[10][2] == 2, str(n))

# T5 small-face rule (CEDA 19 Oct 2026) + singles that break clear spacing are dropped
nf = [LY.face_count(d - 136, 32, face_dim=d)[0] for d in (200, 201, 540, 541, 660, 661, 700)]
check('T5 face bars 200/201/540/541/660/661/700 -> 2/3/3/4/4/5/5', nf == [2, 3, 3, 4, 4, 5, 5], str(nf))
g5 = LY.Grid(250, 500, 40, 12, 32)
st5 = LY.ladder(g5, (16, 20, 25, 28, 32))
check('T5 250x500 (3x3 bars): DB25+ dropped for clear spacing, note', max(x[0] for x in st5) == 20 and any('DB20 is the largest' in n for n in g5.notes),
      str(sorted(set(x[0] for x in st5))))
T5 = LY.ties(LY.Grid(540, 540, 40, 12, 20), 20)
check('T5 540 face 3 x DB20: middle bar clear > 150 -> supported (ACI 25.7.2.3)', T5['sup_h'] == [0, 1, 2] and T5['ok'])


def _t6(tmpd, envelope):
    sts = ['B3', 'B2', 'B1'] + [f'{i}F' for i in range(1, 13)]
    rows = []

    def add(lab, scale, top, V=0.0):
        n = sts.index(top) + 1
        for i, s_ in enumerate(sts[:n]):
            P = (n - i) * 95000 * scale
            for c, (fp, fm) in {'G1': (1, 1), 'E1': (0.75, 1), 'E2': (0.6, -1)}.items():
                rows.append(dict(label=lab, story=s_, combo=c, P=P * fp, M3=0.04 * P * fm, M2=0.03 * P * fm, V2=V, V3=V / 3,
                                 kind='seismic' if c != 'G1' else 'gravity'))
    add('A1', 1.0, '12F'); add('A2', 1.0, '12F'); add('A3', 1.0, '12F', V=60000)
    add('B1', 1.0, '12F'); add('B2', 1.08, '12F'); add('D1', 1.0, '8F')
    json.dump(dict(rows=rows, stories=sts), open(os.path.join(tmpd, 'f6.json'), 'w'))
    sec = {k: dict(b=40, h=80) for k in ('A1', 'A2', 'A3', 'B2', 'D1')}; sec['B1'] = dict(b=80, h=40)
    fc = {x: (560 if x in ('B3', 'B2', 'B1', '1F', '2F', '3F', '4F') else 400) for x in sts}
    cfg = dict(project=dict(name='T6', job='T6'), seismic=dict(frame='gravity'),
               materials=dict(fy=5000, fyt=4000, fc_typical=400, fc_by_story=fc),
               detailing=dict(cover_mm=40, tie_db=12, kmax=4, so_mm=150, s_mm=300),
               slender=dict(k=1.0, beta_d=0.6, Lu_default_m=3.0), sections=sec,
               lap_table={'400': {'25': 1550, '28': 1875, '32': 2325}, '560': {'25': 1325, '28': 1600, '32': 1975}},
               inputs=dict(forces_json='f6.json'), basement_stories=['B3', 'B2', 'B1'], story_ranges=dict(mode='auto'),
               mark_envelope=dict(envelope=envelope))
    cp = os.path.join(tmpd, f'c6_{envelope}.json'); json.dump(cfg, open(cp, 'w'))
    od = os.path.join(tmpd, f'o6_{envelope}')
    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'run.py'), cp, od], check=True, capture_output=True)
    return json.load(open(os.path.join(od, 'results.json')))


tmp = tempfile.mkdtemp()
try:
    for f in ('c1_forces.json', 'c1_config.json'):
        shutil.copy(os.path.join(HERE, 'selftest_data', f), tmp)
    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'run.py'), os.path.join(tmp, 'c1_config.json'), os.path.join(tmp, 'out')],
                   check=True, capture_output=True)
    o = json.load(open(os.path.join(tmp, 'out', 'results.json')))
    got = {q['story']: (r['nbar'], r['db'], round(q['dc'], 3)) for r in o['results'] for q in r['per']}
    exp = {'B6-B5': (62, 32, 0.998), 'B4-B3': (30, 32, 0.971), 'B2-B1': (30, 25, 0.989), '1st-3th': (30, 25, 0.942),
           '4th-10th': (30, 28, 0.969), '11th-20th': (30, 20, 0.823)}
    for k, v in exp.items():
        gv = got.get(k)
        check(f'T2 C1 {k} {v[0]}-DB{v[1]} D/C {v[2]}', gv is not None and gv[0] == v[0] and gv[1] == v[1] and abs(gv[2] - v[2]) <= 0.002, str(gv))
    dy = {q['story']: q['dmax_y'] for r in o['results'] for q in r['per']}
    check('T2 C1 1st-3th δy max 2.18 (βd 0.888, kLu 4.05 m)', abs(dy['1st-3th'] - 2.181) < 0.01, f"{dy['1st-3th']:.3f}")
    check('T2 C1 every story range kept as a row (no merging)', [tuple(b) for b in o['bands']] ==
          [('B6-B5', 'B6-B5'), ('B4-B3', 'B4-B3'), ('B2-B1', 'B2-B1'), ('1st-3th', '1st-3th'), ('4th-10th', '4th-10th'), ('11th-20th', '11th-20th')], str(o['bands']))
    # T6 marks
    o6 = _t6(tmp, False)
    mk = o6['marks']
    check('T6 exact: A1 = A2; A3 (s 150 for shear) separate; B1 rotated, same bars? separate only if bars differ; D1 separate',
          mk['A1'] == mk['A2'] and mk['A3'] != mk['A1'] and mk['D1'] not in (mk['A1'], mk['A3']), str(mk))
    o6 = _t6(tmp, True)
    mk = o6['marks']
    check('T6 envelope: A1 = A2 = A3; rotated B1 shares a mark (not alone); D1 (stops at 8F) alone',
          len({mk[x] for x in ('A1', 'A2', 'A3')}) == 1 and list(mk.values()).count(mk['B1']) > 1 and list(mk.values()).count(mk['D1']) == 1, str(mk))
    sA = {(r['label'], r['band'][0]): (r['s'], r['nbar'], r['db']) for r in o6['results']}
    check('T6 envelope: ties of the mark = critical (A1 takes s 150 of A3)', sA[('A1', '6F')][0] == 150 and sA[('A3', '6F')][0] == 150)
    mate = next(x for x in mk if x != 'B1' and mk[x] == mk['B1'])
    same = all(sA[(mate, b[0])][1:] == sA[('B1', b[0])][1:] for b in o6['bands'])
    check('T6 envelope: rotated members carry the same bars in every row', same)
    check('T6 envelope note: steel increase <= 20 %', all(int(n.split('(+')[1].split(' %')[0]) <= 20 for n in o6['notes'] if n.startswith('mark envelope')))
    # T4 story ranges
    sts = ['B3', 'B2', 'B1'] + [f'{i}F' for i in range(1, 13)]
    fcm = {x: (560 if x in ('B3', 'B2', 'B1', '1F', '2F', '3F', '4F') else 400) for x in sts}
    hm = {x: 3.0 for x in sts}; hm['1F'] = 4.5
    stp = [(20, (1,) * 30), (25, (1,) * 30), (28, (1,) * 30), (32, (1,) * 30), (32, (2,) * 4 + (1,) * 26), (32, (2,) * 8 + (1,) * 22)]
    rA = dict(zip(sts, [5, 5, 4, 4, 3, 3, 3, 2, 2, 2, 2, 1, 1, 0, 0])); rB = dict(zip(sts, [3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1, 0, 0, 0]))
    rg = DS.story_ranges(sts, {'B3', 'B2', 'B1'}, hm, fcm, {'A': rA, 'B': rB}, {'A': stp, 'B': stp}, 2.325)
    check('T4 ranges B3|B2|B1|1F|2F-4F|5F-7F|8F-10F|11F-12F', rg == [('B3', 'B3'), ('B2', 'B2'), ('B1', 'B1'), ('1F', '1F'), ('2F', '4F'),
          ('5F', '7F'), ('8F', '10F'), ('11F', '12F')], str(rg))
    # ETABS synthetic
    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'selftest_data', 'make_synthetic_etabs.py'), tmp], check=True)
    import etabs_io as E
    L = lambda p: dict(zip(('tables', 'units'), E.read_tables(os.path.join(tmp, p))))
    S, FR, FU = L('seis.xlsx'), L('full_red.xlsx'), L('full_unred.xlsx')
    rows, rep = E.assemble(S, FR, FU)
    check('T3 story order / basement', rep['stories_full'] == ['B2', 'B1', '1F', '2F'] and rep['basement_stories'] == ['B2', 'B1'])
    chk = {c['combo']: c['ok'] for c in rep['combo_check_full']}
    check('T3 combo check ข้อ 7 (U_B_99 flagged)', chk == {'U_A_00_02': True, 'U_A_01_01': True, 'U_B_99': False}, str(chk))
    b = {(r['story']): r for r in rows if r['src'] == 'basement' and r['label'] == 'C1'}
    check('T3 basement P B1 = 502.75 t, B2 = 667.0 t', abs(b['B1']['P'] - 502750) < 1 and abs(b['B2']['P'] - 667000) < 1,
          f"{b['B1']['P']:.0f} {b['B2']['P']:.0f}")
    check('T3 basement M3 carried down 87.575 t-m, V2 51.69 t', abs(b['B2']['M3'] - 87575) < 1 and abs(b['B2']['V2'] - 51687.5) < 1)
    check('T3 βd B2 = 0.8253', abs(E.beta_d(FR, 'C1', 'B2') - 0.82534) < 1e-4)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('ALL PASS' if not fails else f'{len(fails)} FAILED: {fails}')
