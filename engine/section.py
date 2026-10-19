"""Strain-compatibility fibre analysis, 3D phi-surface and radial D/C (rectangular tied section).

Sign: P + compression (kg), Mx = sum(F*y), My = sum(F*x) (kg-cm). x along b, y along h.
"""
import math

import numpy as np
from scipy.spatial import ConvexHull

from .materials import ES, ECU, beta1


def _clip_block(hb, hh, ux, uy, s0):
    """Area and centroid of rectangle |x|<=hb, |y|<=hh where ux*x + uy*y >= s0 (vectorised Sutherland-Hodgman)."""
    V = np.array([[-hb, -hh], [hb, -hh], [hb, hh], [-hb, hh]])
    n = len(ux)
    A = np.zeros(n)
    X = np.zeros(n)
    Y = np.zeros(n)
    for k in range(n):
        poly = []
        val = V[:, 0] * ux[k] + V[:, 1] * uy[k] - s0[k]
        for i in range(4):
            j = (i + 1) % 4
            if val[i] >= 0:
                poly.append(V[i])
            if (val[i] >= 0) != (val[j] >= 0):
                t = val[i] / (val[i] - val[j])
                poly.append(V[i] + t * (V[j] - V[i]))
        if len(poly) < 3:
            continue
        P = np.array(poly)
        x, y = P[:, 0], P[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        cr = x * y1 - x1 * y
        a = cr.sum() / 2
        if abs(a) < 1e-12:
            continue
        A[k] = a
        X[k] = ((x + x1) * cr).sum() / (6 * a)
        Y[k] = ((y + y1) * cr).sum() / (6 * a)
    return np.abs(A), X, Y


class Section:
    def __init__(self, b, h, fc, fy, bars, nfib=40, phi_c=0.70, phi_t=0.90, cap=0.80):
        self.b, self.h, self.fc, self.fy = b, h, fc, fy
        self.bars = np.array(bars, dtype=float)            # (n,3) x, y, A
        self.phi_c, self.phi_t, self.cap = phi_c, phi_t, cap
        nx = max(10, int(nfib * b / max(b, h)))
        ny = max(10, int(nfib * h / max(b, h)))
        xs = (np.arange(nx) + 0.5) * b / nx - b / 2
        ys = (np.arange(ny) + 0.5) * h / ny - h / 2
        X, Y = np.meshgrid(xs, ys)
        self.cx, self.cy = X.ravel(), Y.ravel()
        self.cA = b * h / (nx * ny)
        self.b1 = beta1(fc)
        self.ey = fy / ES
        self.Ag = b * h
        self.As = self.bars[:, 2].sum()
        self.Po = 0.85 * fc * (self.Ag - self.As) + fy * self.As                 # ACI 22.4.2.2
        self.phiPn_max = cap * phi_c * self.Po                                     # ACI 22.4.2.1 (tied)
        self.Pnt = -fy * self.As

    def phi_of(self, et):
        """ACI 318-19 21.2.2: compression-controlled phi_c for et <= ey, 0.90 for et >= ey + 0.003."""
        t = np.clip((et - self.ey) / 0.003, 0.0, 1.0)
        return self.phi_c + (self.phi_t - self.phi_c) * t

    def forces(self, theta, c):
        """Nominal (Pn, Mnx, Mny, et) for NA direction theta (compression side unit vector) and depth c (arrays)."""
        theta = np.atleast_1d(theta)[:, None]
        c = np.atleast_1d(c)[:, None]
        ux, uy = np.cos(theta), np.sin(theta)
        corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * [self.b / 2, self.h / 2]
        dmax = np.max(ux * corners[:, 0] + uy * corners[:, 1], axis=1, keepdims=True)
        # concrete (ACI rectangular block) - exact area/centroid of rectangle clipped by the block line
        a = (self.b1 * c).ravel()
        Ac, xc, yc = _clip_block(self.b / 2, self.h / 2, ux.ravel(), uy.ravel(), dmax.ravel() - a)
        Cc = (0.85 * self.fc * Ac)[:, None]
        # steel
        bx, by, bA = self.bars[:, 0], self.bars[:, 1], self.bars[:, 2]
        dep_s = dmax - (ux * bx + uy * by)
        eps = ECU * (c - dep_s) / c
        fs = np.clip(eps * ES, -self.fy, self.fy)
        fs = fs - np.where((dep_s <= self.b1 * c) & (eps > 0), 0.85 * self.fc, 0.0)   # displaced concrete
        Fs = fs * bA
        P = Cc[:, 0] + Fs.sum(1)
        Mx = Cc[:, 0] * yc + (Fs * by).sum(1)
        My = Cc[:, 0] * xc + (Fs * bx).sum(1)
        et = -eps.min(axis=1)                       # net tensile strain at extreme tension steel
        return P, Mx, My, et

    def surface_points(self, ntheta=72, nc=45):
        dim = math.hypot(self.b, self.h)
        cs = dim * np.geomspace(0.01, 30.0, nc)
        th = np.linspace(0, 2 * np.pi, ntheta, endpoint=False)
        T, C = np.meshgrid(th, cs)
        P, Mx, My, et = self.forces(T.ravel(), C.ravel())
        phi = self.phi_of(et)
        pts = np.column_stack([phi * Mx, phi * My, phi * P])
        extra = np.array([[0, 0, self.phi_c * self.Po], [0, 0, self.phi_t * self.Pnt]])
        self.raw = np.vstack([pts, extra])
        self.nominal = np.column_stack([Mx, My, P])
        self.theta_c = np.column_stack([T.ravel(), C.ravel(), phi])
        return self.raw

    def build_hull(self):
        if not hasattr(self, "raw"):
            self.surface_points()
        self.scale = np.abs(self.raw).max(axis=0)
        self.scale[self.scale == 0] = 1.0
        self.hull = ConvexHull(self.raw / self.scale)
        return self.hull

    def dc(self, Pu, Mux, Muy):
        """Radial D/C from the origin; capped surface => max(uncapped, Pu/phiPn,max)."""
        if not hasattr(self, "hull"):
            self.build_hull()
        u = np.array([Mux, Muy, Pu], dtype=float) / self.scale
        if np.allclose(u, 0):
            return 0.0, 0.0
        n, d = self.hull.equations[:, :3], self.hull.equations[:, 3]
        nu = n @ u
        with np.errstate(divide="ignore"):
            t = np.where(nu > 1e-12, -d / nu, np.inf)
        dc_unc = 1.0 / t.min()
        dc_cap = Pu / self.phiPn_max if Pu > 0 else 0.0
        return float(max(dc_unc, dc_cap)), float(dc_unc)

    def capped_mesh(self):
        """Vertices/triangles of the capped phi-surface for plotting (t, t-m)."""
        pts = self.raw.copy()
        pts[:, 2] = np.minimum(pts[:, 2], self.phiPn_max)
        sc = np.abs(pts).max(axis=0)
        sc[sc == 0] = 1
        hull = ConvexHull(pts / sc)
        return pts, hull.simplices

    def uniaxial(self, axis, n=200, nominal=False):
        """P-M curve about one axis ('x': Mx, compression at +y; 'x-': at -y; 'y', 'y-')."""
        th = {"x": np.pi / 2, "x-": -np.pi / 2, "y": 0.0, "y-": np.pi}[axis]
        dim = self.h if axis.startswith("x") else self.b
        cs = dim * np.geomspace(0.01, 30.0, n)
        P, Mx, My, et = self.forces(np.full(n, th), cs)
        M = Mx if axis.startswith("x") else My
        f = np.ones(n) if nominal else self.phi_of(et)
        Pc = f * P
        if not nominal:
            Pc = np.minimum(Pc, self.phiPn_max)
        return np.append(Pc, (1 if nominal else self.phi_t) * self.Pnt), np.append(f * M, 0.0)

    def mm_contour(self, Pu, ntheta=72):
        """phi-Mx/phi-My contour at axial load Pu (capped surface section)."""
        if Pu > self.phiPn_max:
            return np.zeros((1, 2))
        T, C, phi = self.theta_c[:, 0], self.theta_c[:, 1], self.theta_c[:, 2]
        out = []
        ths = np.unique(T)
        for th in ths:
            m = T == th
            P = self.raw[:-2][m, 2]
            o = np.argsort(P)
            P, Mx, My = P[o], self.raw[:-2][m, 0][o], self.raw[:-2][m, 1][o]
            if Pu < P.min() or Pu > P.max():
                continue
            out.append([np.interp(Pu, P, Mx), np.interp(Pu, P, My)])
        out = np.array(out)
        if len(out) > 2:
            ang = np.arctan2(out[:, 1], out[:, 0])
            out = out[np.argsort(ang)]
            out = np.vstack([out, out[:1]])
        return out
