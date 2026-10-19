"""Bar grid, CEDA tie pattern and build-up ladder (rectangular tied columns).

Coordinates: origin at section centroid, x along b (t2), y along h (t3). cm.
"""
import math
from dataclasses import dataclass, field

from .materials import BAR_AREA

LADDER_SINGLE = (20, 25, 28, 32)


@dataclass
class BarGroup:
    x: float                 # nominal grid position (tie corner / face line), cm
    y: float
    n: int                   # bars in this group (1 = single, 2-4 = bundle)
    db: int                  # mm
    corner: bool = False
    hoop_rank: int = -1      # 0 = column corner, 1.. = inner hoop corner (outside -> inside), -1 = not a tie corner
    supported: bool = False  # laterally supported by a tie corner / crosstie hook
    face: str = ""           # 'T','B','L','R' or corner 'TL' etc.

    @property
    def area(self):
        return self.n * BAR_AREA[self.db]

    def centroid(self, b, h):
        """Bundle centroid shifted toward the section interior (Engineering judgment):
        3-bar bundle 0.29 db, 4-bar bundle 0.50 db, from the tie line."""
        off = {1: 0.0, 2: 0.0, 3: 0.289, 4: 0.5}[self.n] * self.db / 10.0
        sx = -math.copysign(1, self.x) if abs(self.x) > 1e-9 and self.face in ("L", "R", "TL", "TR", "BL", "BR") else 0.0
        sy = -math.copysign(1, self.y) if abs(self.y) > 1e-9 and self.face in ("T", "B", "TL", "TR", "BL", "BR") else 0.0
        return self.x + sx * off, self.y + sy * off


@dataclass
class Layout:
    b: float
    h: float
    cover: float             # clear cover to tie, cm
    tie_db: int              # mm
    nx: int                  # bars on top/bottom face incl. corners
    ny: int                  # bars on left/right face incl. corners
    groups: list = field(default_factory=list)
    hoops: list = field(default_factory=list)       # rectangles (x1, y1, x2, y2) through bar centres
    crossties: list = field(default_factory=list)   # ('x'|'y', coord) full-depth single legs
    step_name: str = ""
    grid_note: str = ""
    extra_ties: list = field(default_factory=list)  # ('x'|'y', face index) added for shear

    # ---------- quantities ----------
    @property
    def As(self):
        return sum(g.area for g in self.groups)

    @property
    def rho(self):
        return self.As / (self.b * self.h)

    @property
    def nbars(self):
        return sum(g.n for g in self.groups)

    def bars_xyA(self):
        out = []
        for g in self.groups:
            cx, cy = g.centroid(self.b, self.h)
            out.append((cx, cy, g.area))
        return out

    def describe(self):
        """e.g. '20-DB32 + 4x2-DB32 (bundled at corners)'."""
        cnt = {}
        for g in self.groups:
            cnt.setdefault((g.db, g.n), 0)
            cnt[(g.db, g.n)] += 1
        parts = []
        for (db, n), k in sorted(cnt.items(), key=lambda t: (t[0][1], t[0][0])):
            parts.append(f"{k}-DB{db}" if n == 1 else f"{k}x{n}-DB{db}")
        return " + ".join(parts) + f"  (total {self.nbars} bars)"

    def legs(self):
        """Full-depth legs: (legs parallel to x -> Vx, legs parallel to y -> Vy)."""
        lx = 2 + sum(2 for r in self.hoops if r[4] == 'y') + sum(1 for c in self.crossties if c[0] == 'y')
        ly = 2 + sum(2 for r in self.hoops if r[4] == 'x') + sum(1 for c in self.crossties if c[0] == 'x')
        return lx, ly

    def clear_check(self, dagg_cm=2.5):
        """Clear spacing between adjacent groups along each face (ACI 25.2.3, 25.6.1.6).
        Group width along the face: single db, bundle of 2-4 2db (Assumption).
        Required clear = max(1.5 db_eq, 4 cm, 4/3 d_agg), db_eq = db*sqrt(n)."""
        worst = 1e9
        ok = True
        for face in self._faces():
            for a, c in zip(face[:-1], face[1:]):
                cc = math.hypot(a.x - c.x, a.y - c.y)
                wa = a.db / 10 * (1 if a.n == 1 else 2)
                wc = c.db / 10 * (1 if c.n == 1 else 2)
                clear = cc - (wa + wc) / 2
                req = max(1.5 * max(a.db * math.sqrt(a.n), c.db * math.sqrt(c.n)) / 10, 4.0, 4 / 3 * dagg_cm)
                worst = min(worst, clear - req)
                if clear < req - 1e-6:
                    ok = False
        return ok, worst

    def max_unsupported_clear(self):
        """Largest clear distance from an unsupported bar to the nearest supported bar (ACI 25.7.2.3: <= 15 cm)."""
        m = 0.0
        for face in self._faces():
            sup = [g for g in face if g.supported]
            for g in face:
                if not g.supported:
                    d = min(math.hypot(g.x - s.x, g.y - s.y) for s in sup) - (g.db + max(s.db for s in sup)) / 20
                    m = max(m, d)
        return m

    def _faces(self):
        def key(gs, attr):
            return sorted(gs, key=lambda g: getattr(g, attr))
        xs = self.b / 2 - self._edge()
        ys = self.h / 2 - self._edge()
        top = key([g for g in self.groups if abs(g.y - ys) < 1e-6], 'x')
        bot = key([g for g in self.groups if abs(g.y + ys) < 1e-6], 'x')
        lef = key([g for g in self.groups if abs(g.x + xs) < 1e-6], 'y')
        rig = key([g for g in self.groups if abs(g.x - xs) < 1e-6], 'y')
        return [top, bot, lef, rig]

    def _edge(self):
        return self.cover + self.tie_db / 10 + self.groups[0].db / 20 if self.groups else 0


# ---------------------------------------------------------------- grid
def face_count(L_cc, db_ref_mm=25, smin=12.5, smax=15.0):
    """Bars on a face (incl. corners) for c/c smin..smax (CEDA practice).
    Several counts fit -> fewest bars. None fits -> fewest bars with clear <= 15 cm (ACI 25.7.2.3)."""
    fits = [n for n in range(2, 60) if smin - 1e-9 <= L_cc / (n - 1) <= smax + 1e-9]
    if fits:
        return min(fits), ""
    for n in range(2, 60):
        if L_cc / (n - 1) - db_ref_mm / 10 <= 15.0 + 1e-9:
            return n, (f"face c/c {L_cc / (n - 1) * 10:.0f} mm: no count gives 125-150 mm; "
                       f"closest count with clear <= 150 mm used (ACI 25.7.2.3)")
    return 2, ""


def supported_indices(n):
    """CEDA symmetric pattern on one face (indices 0..n-1, 0 and n-1 = corners)."""
    s = {0, n - 1}
    if n % 2 == 0:
        i, j = n // 2 - 1, n // 2
        while i >= 0:
            s.update((i, j))
            i, j = i - 2, j + 2
    else:
        s.update(range(0, n, 2))
    return sorted(s)


def build_layout(b, h, cover, tie_db, db_grid_ref=25, nx=None, ny=None):
    """Grid + ties with all single bars of db_grid_ref. Bars sizes are set later by apply_step()."""
    edge = cover + tie_db / 10 + db_grid_ref / 20
    note = []
    if nx is None:
        nx, nt = face_count(b - 2 * edge, db_grid_ref)
        if nt:
            note.append("b-face " + nt)
    if ny is None:
        ny, nt = face_count(h - 2 * edge, db_grid_ref)
        if nt:
            note.append("h-face " + nt)
    lay = Layout(b, h, cover, tie_db, nx, ny, grid_note="; ".join(note))
    _place(lay, db_grid_ref)
    return lay


def _place(lay, db):
    """(Re)place groups for a single bar size db keeping counts, bundles and tie topology."""
    edge = lay.cover + lay.tie_db / 10 + db / 20
    xs, ys = lay.b / 2 - edge, lay.h / 2 - edge
    nx, ny = lay.nx, lay.ny
    X = [-xs + 2 * xs * i / (nx - 1) for i in range(nx)]
    Y = [-ys + 2 * ys * j / (ny - 1) for j in range(ny)]
    supx, supy = supported_indices(nx), supported_indices(ny)
    groups = []
    for i, x in enumerate(X):
        for y, f in ((ys, 'T'), (-ys, 'B')):
            corner = i in (0, nx - 1)
            face = (f + ('L' if i == 0 else 'R')) if corner else f
            groups.append(BarGroup(x, y, 1, db, corner, 0 if corner else -1, i in supx, face))
    for j, y in enumerate(Y[1:-1], start=1):
        for x, f in ((-xs, 'L'), (xs, 'R')):
            groups.append(BarGroup(x, y, 1, db, False, -1, j in supy, f))
    # inner hoops: supported intermediate bars paired (i, n-1-i) outside -> inside; leftover single -> crosstie
    hoops, ties = [], []
    rank = 1
    pairs_x = [(i, nx - 1 - i) for i in supx if 0 < i < nx - 1 - i]
    pairs_y = [(j, ny - 1 - j) for j in supy if 0 < j < ny - 1 - j]
    for k in range(max(len(pairs_x), len(pairs_y))):
        if k < len(pairs_x):
            i1, i2 = pairs_x[k]
            hoops.append((X[i1], -ys, X[i2], ys, 'x', rank))
            for g in groups:
                if g.face in ('T', 'B') and (abs(g.x - X[i1]) < 1e-6 or abs(g.x - X[i2]) < 1e-6):
                    g.hoop_rank = rank
        if k < len(pairs_y):
            j1, j2 = pairs_y[k]
            hoops.append((-xs, Y[j1], xs, Y[j2], 'y', rank))
            for g in groups:
                if g.face in ('L', 'R') and (abs(g.y - Y[j1]) < 1e-6 or abs(g.y - Y[j2]) < 1e-6):
                    g.hoop_rank = rank
        rank += 1
    if nx % 2 == 1 and (nx - 1) // 2 in supx and 0 < (nx - 1) // 2 < nx - 1:
        ties.append(('x', X[(nx - 1) // 2]))
    if ny % 2 == 1 and (ny - 1) // 2 in supy and 0 < (ny - 1) // 2 < ny - 1:
        ties.append(('y', Y[(ny - 1) // 2]))
    for d, idx in lay.extra_ties:
        c = X[idx] if d == 'x' else Y[idx]
        ties.append((d, c, 'extra'))
        for g in groups:
            if (d == 'x' and g.face in ('T', 'B') and abs(g.x - c) < 1e-6) or \
               (d == 'y' and g.face in ('L', 'R') and abs(g.y - c) < 1e-6):
                g.supported = True
    lay.groups, lay.hoops, lay.crossties = groups, hoops, ties


# ---------------------------------------------------------------- ladder
def ladder_steps(lay, bundle_db=32, max_bundle=4):
    """Build-up ladder (CEDA): singles DB20->25->28->32, then bundles of the largest bar at tie corners:
    column corners first, then hoop corners outside -> inside; all groups to 2, then 3, then 4."""
    steps = [{"name": f"single DB{d}", "db": d, "bundle": {}} for d in LADDER_SINGLE]
    ranks = sorted({g.hoop_rank for g in lay.groups if g.hoop_rank >= 0})
    current = {}
    for nb in range(2, max_bundle + 1):
        for r in ranks:
            current = dict(current)
            current[r] = nb
            label = "column corners" if r == 0 else f"hoop {r} corners"
            steps.append({"name": f"DB{bundle_db} + {nb}-bundle at {label}" if r == 0 else
                          f"DB{bundle_db} + {nb}-bundle up to {label}", "db": bundle_db, "bundle": current})
    return steps


def apply_step(base, step):
    """Return a new Layout for a ladder step."""
    lay = Layout(base.b, base.h, base.cover, base.tie_db, base.nx, base.ny, grid_note=base.grid_note,
                 extra_ties=list(base.extra_ties))
    _place(lay, step["db"])
    for g in lay.groups:
        g.n = step["bundle"].get(g.hoop_rank, 1) if g.hoop_rank >= 0 else 1
    lay.step_name = step["name"]
    return lay


def add_crossties(lay, direction, count):
    """Add full-depth crossties at unsupported intermediate bars, nearest centre first.
    direction 'x': legs parallel to y engaging top/bottom-face bars (resist Vy); 'y': resist Vx.
    Returns the number added; groups are re-placed so the bars become supported."""
    n = lay.nx if direction == 'x' else lay.ny
    sup = set(supported_indices(n)) | {i for d, i in lay.extra_ties if d == direction}
    cand = sorted([i for i in range(1, n - 1) if i not in sup], key=lambda i: abs(i - (n - 1) / 2))
    add = cand[:count]
    lay.extra_ties += [(direction, i) for i in add]
    keep = {g.hoop_rank: g.n for g in lay.groups if g.hoop_rank >= 0}
    _place(lay, lay.groups[0].db)
    for g in lay.groups:
        g.n = keep.get(g.hoop_rank, 1) if g.hoop_rank >= 0 else 1
    return len(add)
