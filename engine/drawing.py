"""Draft Table of Column (DXF, mm, 1:1 model space) + PNG preview rendered from the same DXF.

Layers (CEDA): G-ANNO-TEXT, A-DETL-GENF, CED_0_10/13/18_Solid, S-DIMS, G-ANNO-CHECK (freeze before issue).
Layer-to-object assignment of the CED_0_xx_Solid layers is an Assumption - confirm with the CEDA CAD standard.
"""
import io
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

LAYERS = {
    "G-ANNO-TEXT": 7, "A-DETL-GENF": 8, "CED_0_10_Solid": 1, "CED_0_13_Solid": 3,
    "CED_0_18_Solid": 2, "S-DIMS": 4, "G-ANNO-CHECK": 6,
}
TXT = 2.5 * 20      # 2.5 mm text at 1:20


def _text(msp, s, x, y, h=TXT, layer="G-ANNO-TEXT", align=TextEntityAlignment.MIDDLE_CENTER):
    msp.add_text(s, height=h, dxfattribs={"layer": layer, "style": "CEDA"}).set_placement((x, y), align=align)


def _hoop(msp, x1, y1, x2, y2, r, layer, hook=True):
    """Closed hoop through bar centres offset by r (bar radius + tie radius) with a 135-deg hook at top-left."""
    x1, x2 = min(x1, x2) - r, max(x1, x2) + r
    y1, y2 = min(y1, y2) - r, max(y1, y2) + r
    rb = r * 0.9
    pl = msp.add_lwpolyline([(x1 + rb, y1), (x2 - rb, y1), (x2, y1 + rb), (x2, y2 - rb), (x2 - rb, y2),
                             (x1 + rb, y2), (x1, y2 - rb), (x1, y1 + rb)], close=True, dxfattribs={"layer": layer})
    if hook:
        L = 6 * 12 + rb
        msp.add_line((x1 + rb, y2), (x1 + rb + L * 0.707, y2 - L * 0.707), dxfattribs={"layer": layer})
        msp.add_line((x1, y2 - rb), (x1 + L * 0.707, y2 - rb - L * 0.707), dxfattribs={"layer": layer})
    return pl


def section_entities(msp, res, ox, oy):
    """Draw one section with its centroid at (ox, oy) in mm."""
    lay, S = res["layout"], res["inp"]["section"]
    b, h = S["b"] * 10, S["h"] * 10
    msp.add_lwpolyline([(ox - b / 2, oy - h / 2), (ox + b / 2, oy - h / 2), (ox + b / 2, oy + h / 2),
                        (ox - b / 2, oy + h / 2)], close=True, dxfattribs={"layer": "A-DETL-GENF"})
    dbmax = max(g.db for g in lay.groups)
    rt = dbmax / 2 + lay.tie_db / 2
    xs = (S["b"] / 2 - lay.cover - lay.tie_db / 10 - dbmax / 20) * 10
    ys = (S["h"] / 2 - lay.cover - lay.tie_db / 10 - dbmax / 20) * 10
    _hoop(msp, ox - xs, oy - ys, ox + xs, oy + ys, rt, "CED_0_13_Solid")
    for r in lay.hoops:
        x1, y1, x2, y2 = r[0] * 10, r[1] * 10, r[2] * 10, r[3] * 10
        _hoop(msp, ox + x1, oy + y1, ox + x2, oy + y2, rt * 0.75, "CED_0_10_Solid")
    for t in lay.crossties:
        c = t[1] * 10
        if t[0] == 'x':
            p1, p2 = (ox + c, oy - ys - rt), (ox + c, oy + ys + rt)
        else:
            p1, p2 = (ox - xs - rt, oy + c), (ox + xs + rt, oy + c)
        msp.add_line(p1, p2, dxfattribs={"layer": "CED_0_10_Solid"})
        for p, sg in ((p1, -1), (p2, 1)):
            if t[0] == 'x':
                msp.add_line(p, (p[0] + 60, p[1] - sg * 60), dxfattribs={"layer": "CED_0_10_Solid"})
            else:
                msp.add_line(p, (p[0] - sg * 60, p[1] + 60), dxfattribs={"layer": "CED_0_10_Solid"})
    for g in lay.groups:
        r = g.db / 2
        offs = {1: [(0, 0)], 2: [(-r, 0), (r, 0)], 3: [(-r, 0), (r, 0), (0, -1.732 * r)],
                4: [(-r, 0), (r, 0), (-r, -2 * r), (r, -2 * r)]}[g.n]
        horiz = g.face in ("T", "B", "TL", "TR", "BL", "BR")
        for dx, dy in offs:
            # rotate the bundle so it extends inward from the tie line
            if horiz:
                px, py = dx, dy if g.y > 0 else -dy
            else:
                px, py = (dy if g.x > 0 else -dy), dx
            cx, cy = ox + g.x * 10 + px, oy + g.y * 10 + py
            hatch = msp.add_hatch(color=256, dxfattribs={"layer": "CED_0_18_Solid"})
            hatch.paths.add_edge_path().add_arc((cx, cy), r, 0, 360)
            msp.add_circle((cx, cy), r, dxfattribs={"layer": "CED_0_18_Solid"})
    # dimensions
    dim = msp.add_linear_dim(base=(ox, oy - h / 2 - 250), p1=(ox - b / 2, oy - h / 2), p2=(ox + b / 2, oy - h / 2),
                             dimstyle="CEDA", dxfattribs={"layer": "S-DIMS"})
    dim.render()
    dim = msp.add_linear_dim(base=(ox - b / 2 - 250, oy), p1=(ox - b / 2, oy - h / 2), p2=(ox - b / 2, oy + h / 2),
                             angle=90, dimstyle="CEDA", dxfattribs={"layer": "S-DIMS"})
    dim.render()


def make_dxf(res):
    inp = res["inp"]
    S, M, P = inp["section"], inp["material"], inp["project"]
    lay, ties = res["layout"], res["ties"]
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    doc.styles.add("CEDA", font="arial.ttf")
    ds = doc.dimstyles.duplicate_entry("EZDXF", "CEDA")
    ds.dxf.dimscale = 20
    ds.dxf.dimtxt = 2.5
    ds.dxf.dimdec = 0
    ds.dxf.dimlfac = 1.0
    ds.dxf.dimpost = ""
    for n, c in LAYERS.items():
        if n not in doc.layers:
            doc.layers.add(n, color=c)
    msp = doc.modelspace()

    b, h = S["b"] * 10, S["h"] * 10
    cw = max(b, 600) + 1400            # cell width
    sh = max(h, 600) + 900             # section row height
    rows = [("MARK", P.get("mark", "C?")), ("STORY", P.get("band", "-")), ("SIZE (mm)", f"{b:.0f} x {h:.0f}"),
            ("f'c (ksc)", f"{M['fc']:.0f}"), ("MAIN BARS", lay.describe().split("  (")[0]),
            ("TIES", f"DB{lay.tie_db} @{ties['s_lo'] * 10:.0f} (lo = {ties['rules']['lo'] * 10:.0f}) / @{ties['s_out'] * 10:.0f}"),
            ("LAP Lst (mm)", ", ".join(f"DB{d}: {v:.0f}" if v else f"DB{d}: [CHECK]" for d, v in res["lap"].items()))]
    hw, rh = 1500, 220
    x0, y0 = 0.0, 0.0
    W = hw + cw
    top = y0 + sh + rh * len(rows)
    # title
    _text(msp, "TABLE OF COLUMN (DRAFT)", x0 + W / 2, top + 250, h=5 * 20)
    _text(msp, f"{P.get('name', '')}  |  JOB {P.get('job_no', '')}", x0 + W / 2, top + 110, h=3 * 20)
    # frame
    msp.add_lwpolyline([(x0, y0), (x0 + W, y0), (x0 + W, top), (x0, top)], close=True, dxfattribs={"layer": "A-DETL-GENF"})
    msp.add_line((x0 + hw, y0), (x0 + hw, top), dxfattribs={"layer": "A-DETL-GENF"})
    msp.add_line((x0, y0 + sh), (x0 + W, y0 + sh), dxfattribs={"layer": "A-DETL-GENF"})
    _text(msp, "SECTION", x0 + hw / 2, y0 + sh / 2)
    for i, (k, v) in enumerate(reversed(rows)):
        yy = y0 + sh + rh * i
        msp.add_line((x0, yy), (x0 + W, yy), dxfattribs={"layer": "A-DETL-GENF"})
        _text(msp, k, x0 + hw / 2, yy + rh / 2)
        _text(msp, v, x0 + hw + cw / 2, yy + rh / 2, h=TXT if len(v) < 40 else TXT * 0.8)
    section_entities(msp, res, x0 + hw + cw / 2 + 100, y0 + sh / 2 + 120)
    # notes / check lines
    ny = y0 - 200
    _text(msp, "NOTES:", x0, ny, align=TextEntityAlignment.LEFT)
    gen = [f"1. Concrete f'c = {M['fc']:.0f} ksc, main bars fy = {M['fy']:.0f} ksc, ties fyt = {M['fyt']:.0f} ksc.",
           f"2. Clear cover to ties {M['cover'] * 10:.0f} mm. 135-deg hooks, 6db extension (min 75 mm).",
           f"3. Ties within lo = {ties['rules']['lo'] * 10:.0f} mm from each joint face at @{ties['s_lo'] * 10:.0f} mm; elsewhere @{ties['s_out'] * 10:.0f} mm.",
           "4. Lap splices Class B per project table S-00-04-04; laps only where bundles <= 2 bars.",
           "5. DRAFT ONLY - NOT FOR CONSTRUCTION."]
    for i, s in enumerate(gen):
        _text(msp, s, x0, ny - 120 * (i + 1), h=TXT * 0.9, align=TextEntityAlignment.LEFT)
    chk = list(res["checkpoints"])
    for i, s in enumerate(chk):
        _text(msp, "[CHECK] " + s[:150], x0, ny - 120 * (len(gen) + 2 + i), h=TXT * 0.8,
              layer="G-ANNO-CHECK", align=TextEntityAlignment.LEFT)
    return doc


def dxf_bytes(doc):
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8")


def preview_png(doc, dpi=150):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy

    fig = plt.figure(figsize=(8, 10))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    return buf.getvalue()
