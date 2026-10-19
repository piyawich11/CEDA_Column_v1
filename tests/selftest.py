"""Engine self-test (hand checks). Run: python3 tests/selftest.py  -> ALL PASS"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.materials import BAR_AREA, beta1          # noqa: E402
from engine.section import Section, _clip_block       # noqa: E402
from engine.layout import build_layout, supported_indices  # noqa: E402

ok = True


def check(name, got, ref, tol):
    global ok
    good = abs(got - ref) <= tol * max(1.0, abs(ref))
    ok &= good
    print(f"{'PASS' if good else 'FAIL'}  {name}: {got:.4f} (ref {ref:.4f})")


# T1 uniaxial point vs hand (40x60, 8-DB25, f'c 320, fy 4000, c = 30 cm about x)
A = BAR_AREA[25]
d1 = 4 + 1.2 + 1.25
ys = [30 - d1] * 3 + [0] * 2 + [-(30 - d1)] * 3
xs = [-(20 - d1), 0, 20 - d1, -(20 - d1), 20 - d1, -(20 - d1), 0, 20 - d1]
bars = [(x, y, A) for x, y in zip(xs, ys)]
s = Section(40, 60, 320, 4000, bars)
P, Mx, My, _ = s.forces(np.array([np.pi / 2]), np.array([30.0]))
a = beta1(320) * 30
Cc = 0.85 * 320 * a * 40
Ps = Ms = 0.0
for x, y, Ai in bars:
    dep = 30 - y
    e = 0.003 * (30 - dep) / 30
    f = max(-4000, min(4000, e * 2.04e6)) - (0.85 * 320 if dep <= a and e > 0 else 0)
    Ps += f * Ai
    Ms += f * Ai * y
check("T1 Pn (t)", P[0] / 1e3, (Cc + Ps) / 1e3, 1e-6)
check("T1 Mnx (t-m)", Mx[0] / 1e5, (Cc * (30 - a / 2) + Ms) / 1e5, 1e-6)
# T2 Po and cap
Po = 0.85 * 320 * (2400 - 8 * A) + 4000 * 8 * A
check("T2 Po (t)", s.Po / 1e3, Po / 1e3, 1e-9)
check("T2 D/C at phiPn,max", s.dc(0.8 * 0.7 * Po, 0, 0)[0], 1.0, 1e-9)
# T3 point on the uniaxial curve -> D/C ~ 1
Pc, Mc = s.uniaxial("x")
check("T3 D/C on curve", s.dc(Pc[60], Mc[60], 0)[0], 1.0, 5e-3)
# T4 exact block clip vs analytic triangle (corner cut)
Ac, xc, yc = _clip_block(20, 30, np.array([math.cos(math.pi / 4)]), np.array([math.sin(math.pi / 4)]),
                         np.array([(20 + 30) / math.sqrt(2) - 10 / math.sqrt(2)]))
check("T4 corner triangle area", Ac[0], 0.5 * 10 * 10, 1e-9)
# T5 CEDA tie pattern and grid
global_ok = supported_indices(6) == [0, 2, 3, 5] and supported_indices(5) == [0, 2, 4] and \
    supported_indices(8) == [0, 1, 3, 4, 6, 7]
ok &= global_ok
print(("PASS" if global_ok else "FAIL") + "  T5 symmetric tie pattern")
L = build_layout(45, 200, 4, 12)
check("T6 45x200 grid bars (C1 = 30)", L.nx * 2 + (L.ny - 2) * 2, 30, 0)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
