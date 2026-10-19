"""Plotly (web) and matplotlib (PDF) figures. Forces in t, t-m."""
import numpy as np
import plotly.graph_objects as go


def surface_3d(res):
    sec = res["section"]
    pts, tri = sec.capped_mesh()
    x, y, z = pts[:, 0] / 1e5, pts[:, 1] / 1e5, pts[:, 2] / 1e3
    fig = go.Figure()
    fig.add_trace(go.Mesh3d(x=x, y=y, z=z, i=tri[:, 0], j=tri[:, 1], k=tri[:, 2], opacity=0.35,
                            intensity=z, colorscale="Blues", showscale=False, name="φ-surface",
                            hovertemplate="φMx %{x:.1f} t-m<br>φMy %{y:.1f} t-m<br>φPn %{z:.1f} t<extra></extra>"))
    rows = res["rows"]
    dc = np.array([min(r["DC"], 9.99) for r in rows])
    fig.add_trace(go.Scatter3d(
        x=[r["Mux"] for r in rows], y=[r["Muy"] for r in rows], z=[r["Pu"] for r in rows], mode="markers",
        marker=dict(size=5, color=["#d62728" if d > 1 else "#2ca02c" for d in dc], line=dict(width=1, color="black")),
        text=[f"{r['combo']}<br>D/C {r['DC']:.3f}" for r in rows], name="Demand (Pu, Mux, Muy)",
        hovertemplate="%{text}<br>Mux %{x:.1f}<br>Muy %{y:.1f}<br>Pu %{z:.1f}<extra></extra>"))
    g = max(rows, key=lambda r: r["DC"])
    fig.add_trace(go.Scatter3d(x=[0, g["Mux"] / max(g["DC"], 1e-9)], y=[0, g["Muy"] / max(g["DC"], 1e-9)],
                               z=[0, g["Pu"] / max(g["DC"], 1e-9)], mode="lines",
                               line=dict(color="orange", width=4), name=f"ray to surface ({g['combo']})"))
    fig.update_layout(scene=dict(xaxis_title="φMx (t-m)", yaxis_title="φMy (t-m)", zaxis_title="φPn (t)"),
                      height=620, margin=dict(l=0, r=0, t=30, b=0), legend=dict(x=0, y=1))
    return fig


def pm_2d(res, axis):
    sec = res["section"]
    P, M = sec.uniaxial(axis)
    P2, M2 = sec.uniaxial(axis + "-")
    key = "Mux" if axis == "x" else "Muy"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.r_[M, M2[::-1]] / 1e5, y=np.r_[P, P2[::-1]] / 1e3, mode="lines", name="φPn-φMn"))
    fig.add_trace(go.Scatter(x=[r[key] for r in res["rows"]], y=[r["Pu"] for r in res["rows"]], mode="markers",
                             text=[r["combo"] for r in res["rows"]], name="demand"))
    fig.add_hline(y=sec.phiPn_max / 1e3, line_dash="dot", annotation_text="φPn,max")
    fig.update_layout(xaxis_title=f"φM{axis} (t-m)", yaxis_title="φPn (t)", height=420, margin=dict(t=30))
    return fig


def mm_2d(res):
    sec = res["section"]
    g = max(res["rows"], key=lambda r: r["DC"])
    c = sec.mm_contour(g["Pu"] * 1e3)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=c[:, 0] / 1e5, y=c[:, 1] / 1e5, mode="lines", name=f"φMx-φMy at Pu = {g['Pu']:.0f} t"))
    fig.add_trace(go.Scatter(x=[g["Mux"]], y=[g["Muy"]], mode="markers", name=g["combo"]))
    fig.update_layout(xaxis_title="φMx (t-m)", yaxis_title="φMy (t-m)", height=420, margin=dict(t=30),
                      yaxis_scaleanchor="x")
    return fig


# ---------------------------------------------------------------- matplotlib (PDF)
def mpl_section(ax, res):
    from matplotlib.patches import Rectangle, Circle
    lay, S = res["layout"], res["inp"]["section"]
    b, h = S["b"], S["h"]
    ax.add_patch(Rectangle((-b / 2, -h / 2), b, h, fill=False, lw=1.2))
    dbm = max(g.db for g in lay.groups) / 10
    e = lay.cover + lay.tie_db / 20
    ax.add_patch(Rectangle((-b / 2 + e, -h / 2 + e), b - 2 * e, h - 2 * e, fill=False, lw=0.8, color="tab:blue"))
    for r in lay.hoops:
        o = dbm / 2
        ax.add_patch(Rectangle((r[0] - o, r[1] - o), r[2] - r[0] + 2 * o, r[3] - r[1] + 2 * o, fill=False,
                               lw=0.6, color="tab:blue"))
    for t in lay.crossties:
        if t[0] == "x":
            ax.plot([t[1], t[1]], [-h / 2 + e, h / 2 - e], color="tab:green", lw=0.6)
        else:
            ax.plot([-b / 2 + e, b / 2 - e], [t[1], t[1]], color="tab:green", lw=0.6)
    for g in lay.groups:
        cx, cy = g.centroid(b, h)
        ax.add_patch(Circle((cx, cy), g.db / 20 * (1 if g.n == 1 else 1.35), color="k"))
        if g.n > 1:
            ax.text(cx, cy, str(g.n), color="w", fontsize=4, ha="center", va="center")
    ax.set_xlim(-b / 2 - 5, b / 2 + 5)
    ax.set_ylim(-h / 2 - 5, h / 2 + 5)
    ax.set_aspect("equal")
    ax.set_title(f"{b:.0f} x {h:.0f} cm  -  {lay.describe()}", fontsize=7)
    ax.tick_params(labelsize=6)


def mpl_surface(ax, res):
    sec = res["section"]
    pts, tri = sec.capped_mesh()
    ax.plot_trisurf(pts[:, 0] / 1e5, pts[:, 1] / 1e5, pts[:, 2] / 1e3, triangles=tri, alpha=0.25, color="tab:blue",
                    linewidth=0)
    for r in res["rows"]:
        ax.scatter(r["Mux"], r["Muy"], r["Pu"], color="red" if r["DC"] > 1 else "green", s=8)
    ax.set_xlabel("φMx (t-m)", fontsize=6)
    ax.set_ylabel("φMy (t-m)", fontsize=6)
    ax.set_zlabel("φPn (t)", fontsize=6)
    ax.tick_params(labelsize=5)
    ax.set_title("3D φ-surface (capped) + demand", fontsize=7)


def mpl_pm(ax, res, axis):
    sec = res["section"]
    P, M = sec.uniaxial(axis)
    P2, M2 = sec.uniaxial(axis + "-")
    key = "Mux" if axis == "x" else "Muy"
    ax.plot(np.r_[M, M2[::-1]] / 1e5, np.r_[P, P2[::-1]] / 1e3, lw=1)
    ax.scatter([r[key] for r in res["rows"]], [r["Pu"] for r in res["rows"]], s=8, color="red")
    ax.axhline(sec.phiPn_max / 1e3, ls=":", lw=0.7)
    ax.set_xlabel(f"φM{axis} (t-m)", fontsize=6)
    ax.set_ylabel("φPn (t)", fontsize=6)
    ax.tick_params(labelsize=6)
    ax.grid(lw=0.3)
    ax.set_title(f"P-M{axis}", fontsize=7)


def mpl_mm(ax, res):
    sec = res["section"]
    g = max(res["rows"], key=lambda r: r["DC"])
    c = sec.mm_contour(g["Pu"] * 1e3)
    ax.plot(c[:, 0] / 1e5, c[:, 1] / 1e5, lw=1)
    ax.scatter([g["Mux"]], [g["Muy"]], s=10, color="red")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("φMx (t-m)", fontsize=6)
    ax.set_ylabel("φMy (t-m)", fontsize=6)
    ax.tick_params(labelsize=6)
    ax.grid(lw=0.3)
    ax.set_title(f"Mx-My at Pu = {g['Pu']:.0f} t ({g['combo']})", fontsize=7)
