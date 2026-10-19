"""App tests – run:  python3 tests/test_app.py   -> ALL PASS
A  engine self-test (skill scripts bundled in engine/) must print ALL PASS
B  parity: app pipeline (upload reader -> normalised workbook -> engine) == engine run directly on the ETABS files
C  one-model upload + combo sheet without header (VOCO test files format) -> runs, combo check flags wrong factors,
   every output file + per-mark calc/back-up exist, DXF renders, interaction surface builds
"""
import os, sys, json, subprocess, tempfile, shutil, copy
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import app_io as AIO  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info else ''))
    if not cond:
        fails.append(name)


ENG = os.path.join(HERE, 'engine')
tmp = tempfile.mkdtemp()
# ---------------------------------------------------------------- A
r = subprocess.run([sys.executable, '-I', os.path.join(ENG, 'selftest.py'), ENG], cwd=tmp, capture_output=True, text=True)
check('A engine self-test ALL PASS', 'ALL PASS' in r.stdout, r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-300:])

# ---------------------------------------------------------------- B parity on the synthetic 3-model ETABS set
subprocess.run([sys.executable, '-I', os.path.join(ENG, 'selftest_data', 'make_synthetic_etabs.py'), tmp], check=True)
base = json.load(open(os.path.join(ENG, 'config_template.json')))
base['project'] = dict(name='PARITY', job='PAR')
base['seismic']['frame'] = 'gravity'
base['slender']['overrides'] = []
base['exclude_combos'] = ['U_B_99']
cfgA = copy.deepcopy(base)
cfgA['inputs'] = dict(seismic='seis.xlsx', full_reduced='full_red.xlsx', full_unreduced='full_unred.xlsx')
dA = os.path.join(tmp, 'A'); os.makedirs(dA)
for f in ('seis.xlsx', 'full_red.xlsx', 'full_unred.xlsx'):
    shutil.copy(os.path.join(tmp, f), dA)
resA, outA = AIO.run_engine(dA, cfgA)
dB = os.path.join(tmp, 'B'); os.makedirs(dB)
paths = {}
for key, f in (('seismic', 'seis.xlsx'), ('full_reduced', 'full_red.xlsx'), ('full_unreduced', 'full_unred.xlsx')):
    t, u, _ = AIO.read_upload(os.path.join(tmp, f))
    AIO.write_tables(os.path.join(dB, key + '.xlsx'), t, u)
    paths[key] = key + '.xlsx'
cfgB = copy.deepcopy(base); cfgB['inputs'] = paths
resB, outB = AIO.run_engine(dB, cfgB)
sig = lambda R: sorted((r['label'], tuple(r['band']), r['mark'], r['nbar'], r['db'], round(max(q['dc'] for q in r['per']), 4)) for r in R['results'])
check('B app pipeline == engine on the original files (labels, ranges, marks, bars, D/C)', sig(resA) == sig(resB), str(sig(resB))[:200])
check('B basement assembled through the app path', bool(resB['input_report'].get('basement_stories')), str(resB['input_report'].get('basement_stories')))

# ---------------------------------------------------------------- C one model + headerless combos (VOCO test format)
tdir = sys.argv[1] if len(sys.argv) > 1 else None
if tdir and os.path.exists(os.path.join(tdir, 'Column Load.xlsx')):
    parts, info = [], []
    for f in ('Column Load.xlsx', 'load combination.xlsx'):
        t, u, i = AIO.read_upload(os.path.join(tdir, f)); parts.append((t, u)); info += i
    T, U = AIO.merge(parts)
    check('C headerless combo sheet read', any('without header' in i for i in info), '; '.join(info))
    sc = AIO.scan(T, U)
    dC = os.path.join(tmp, 'C'); os.makedirs(dC)
    AIO.write_tables(os.path.join(dC, 'seismic.xlsx'), T, U)
    cfgC = copy.deepcopy(base)
    cfgC['project'] = dict(name='VOCO test', job='VT')
    cfgC['inputs'] = dict(seismic='seismic.xlsx', full_reduced='seismic.xlsx')
    cfgC['exclude_combos'] = []
    cfgC['sections'] = {lab: dict(shape='rect', b=45, h=200) for lab in sc['labels']}          # test only
    cfgC['slender'] = dict(k=1.0, beta_d=0.888, overrides=[dict(stories=sc['stories'], labels=[], Lu_m=4.5, k=0.9)])
    cfgC['materials']['fc_by_story'] = {s: (560 if s in ('1st', '2nd', '3rd') else 400) for s in sc['stories']}
    cfgC['story_order'] = sc['stories']
    resC, outC = AIO.run_engine(dC, cfgC)
    check('C story order 1st … 20th', resC['stories'][0] == '1st' and resC['stories'][-1] == '20th', str(resC['stories'][:3]))
    check('C combo check flags U_A_00_02 (factors 1.2/1.2/1.6, name says 1.4/1.7)',
          any('U_A_00_02' in n and 'do not match' in n for n in resC['notes']))
    main_f, per = AIO.files(outC)
    names = [n for _, n, _ in main_f]
    check('C all project outputs written', all(any(n.endswith(x) for n in names) for x in
          ('_Decision.xlsx', '_Calc.pdf', '_Backup.xlsx', '_DRAFT.dxf', '_DRAFT.pdf', '_Schedule_DRAFT.xlsx')), str(names))
    marks = set(resC['marks'].values())
    check('C per-mark calc PDF + back-up Excel for every mark', set(per) == marks and all(len(v) == 2 for v in per.values()),
          f'{len(per)} / {len(marks)}')
    png = AIO.dxf_png([p for p, n, _ in main_f if n.endswith('.dxf')][0], dpi=60)
    check('C DXF renders', len(png) > 10000, f'{len(png)} bytes')
    r0 = next(r for r in resC['results'] if r.get('ref'))
    f3, f2, fc, gov = AIO.surface_figures(AIO.mark_band_eval(outC, r0['mark'], tuple(r0['band'])))
    dcs = [q['dc'] for r in resC['results'] if r['mark'] == r0['mark'] and tuple(r['band']) == tuple(r0['band']) for q in r['per']]
    check('C interaction surface: governing D/C = engine result', abs(gov['ev']['dcmax'] - max(dcs)) < 1e-9, f"{gov['ev']['dcmax']:.4f}")
else:
    print('SKIP C (pass the folder with "Column Load.xlsx" and "load combination.xlsx")')
shutil.rmtree(tmp, ignore_errors=True)
print('ALL PASS' if not fails else f'{len(fails)} FAILED: {fails}')
sys.exit(1 if fails else 0)
