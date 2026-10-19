"""Calculation report: tables (web), PDF (matplotlib, English) and Excel back-up."""
import io
import math
import re

import pandas as pd

from .design import ALLOWED_COMBOS


def f(x, n=2):
    if x is None:
        return "-"
    if isinstance(x, float) and math.isinf(x):
        return "unstable"
    return f"{x:.{n}f}"


def criteria_rows(res):
    inp = res["inp"]
    S, M, Z = inp["section"], inp["material"], inp["seismic"]
    sys_txt = f"{Z.get('system', '-')} (R {Z.get('R', '-')}, Ω0 {Z.get('Omega0', '-')}, Cd {Z.get('Cd', '-')})"
    return [
        ("Section b x h (b = t2, h = t3)", f"{S['b']:.0f} x {S['h']:.0f} cm", "Input"),
        ("f'c / fy / fyt", f"{M['fc']:.0f} / {M['fy']:.0f} / {M['fyt']:.0f} ksc", "Input"),
        ("Typical f'c of project / slab f'c", f"{M.get('fc_typ', '-')} / {M.get('fc_slab', '-')} ksc", "Input"),
        ("Clear cover to ties / tie size", f"{M['cover'] * 10:.0f} mm / DB{res['layout'].tie_db}", "Input"),
        ("Lu / k / kLu", f"{S['Lu']:.0f} cm / {S['k']:.2f} / {S['k'] * S['Lu']:.0f} cm", "Input (default k = 1.0)"),
        ("Seismic design", "Required" if Z["required"] else "Not required", "Input"),
        ("Zone / importance / category", f"{Z.get('zone', '-')} / {Z.get('importance', '-')} / {Z.get('category', '-')}", "มยผ. 1301/1302-61"),
        ("Lateral system", sys_txt, "มยผ. 1301/1302-61 Table 2.3-1"),
        ("Column type", Z["column_type"], "Input"),
        ("phi: tied / flexure / shear", "0.70 / 0.90 / 0.85", "Code: กฎกระทรวง 2566 ข้อ 8 วรรคสอง (QC column)"),
        ("phi transition", "εt: εy -> εy + 0.003", "Code: ACI 318-19 21.2.2"),
        ("φPn,max", "0.80 φ Po, Po = 0.85f'c(Ag-Ast)+fyAst", "Code: ACI 318-19 22.4.2"),
        ("Biaxial", "3D φ-surface (convex hull), radial D/C, no Bresler", "Engineering judgment"),
        ("Slenderness", "non-sway, r = 0.3h, limit 22 (M1/M2 = +1), Cm = 1", "Code ACI 6.2.5/6.6.4 + Practice"),
        ("βd", f"{inp['bd']:.3f}  [1.4(DL+SDL)+0.25·1.7LL]/[1.4(DL+SDL)+1.7LL]", "Practice (Rev.1)"),
        ("Stability index Q", f(inp.get("Q"), 3), "ACI 318-19 6.6.4.3 (≤ 0.05)"),
        ("ρ limit", "8 % (size restricted, approval)" if S.get("size_restricted") else "6 %", "Practice (CEDA)"),
        ("Bar grid", "c/c 125-150 mm, ladder DB20->25->28->32 -> bundles at tie corners", "Practice (CEDA)"),
        ("Minimum ties", "IMF level for every column", "Code: ประกาศ มท. 2564 ข้อ 26(1) = มยผ. 5.2.7.4"),
        ("Project", f"{inp['project'].get('name', '')} / {inp['project'].get('job_no', '')}", "Input"),
    ]


def combo_table(res):
    out = []
    for c, r in zip(res["combos"], res["rows"]):
        out.append({"Combo": r["combo"], "Type": r["type"], "ข้อ 7": c["combo_check"], "Pu (t)": r["Pu"],
                    "Mx (t-m)": r["Mx"], "My (t-m)": r["My"], "kLu/r x": r["klr_x"], "kLu/r y": r["klr_y"],
                    "δx": r["delta_x"], "δy": r["delta_y"], "Mux (t-m)": r["Mux"], "Muy (t-m)": r["Muy"],
                    "Pu/φPn,max": float(r["PuPmax"]), "D/C uncapped": r["DC_uncapped"], "D/C": r["DC"]})
    return pd.DataFrame(out)


def ladder_table(res):
    return pd.DataFrame([{"Step": r["step"], "Ladder step": r["name"], "Bars": r["bars"], "ρ (%)": r["rho"] * 100,
                          "Clear spacing": "OK" if r["clear_ok"] else "NG", "max D/C": r["DC"], "Status": r["status"]}
                         for r in res["ladder"]])


def shear_table(res):
    t = res["ties"]
    rows = []
    for z, key, s in (("lo", "lo_check", t["s_lo"]), ("outside lo", "out_check", t["s_out"])):
        for d in "xy":
            w = t[key][d]
            rows.append({"Zone": z, "Dir": "Vx (along b)" if d == "x" else "Vy (along h)", "Gov. case": w["case"],
                         "Vu (t)": w["Vu"], "Nu (t)": w["Nu"], "bw (cm)": w["bw"], "d (cm)": w["d"], "Vc (t)": w["Vc"],
                         "legs": w["legs"], "Av (cm2)": w["Av"], "s (cm)": s, "Vs (t)": w["Vs"],
                         "Vs,max (t)": w["Vs_max"], "φVn (t)": w["phiVn"], "Av,min (cm2)": w["Av_min"],
                         "Vu/φVn": w["ratio"], "OK": "OK" if w["ok"] else "NG"})
    return pd.DataFrame(rows)


def bar_table(res):
    lay = res["layout"]
    S = res["inp"]["section"]
    rows = []
    for i, g in enumerate(lay.groups, 1):
        cx, cy = g.centroid(S["b"], S["h"])
        rows.append({"No": i, "x (mm)": round(g.x * 10, 1), "y (mm)": round(g.y * 10, 1), "bars": g.n, "DB": g.db,
                     "centroid x (mm)": round(cx * 10, 1), "centroid y (mm)": round(cy * 10, 1), "face": g.face,
                     "tie corner": "column corner" if g.hoop_rank == 0 else (f"hoop {g.hoop_rank}" if g.hoop_rank > 0 else "-"),
                     "supported": "Y" if g.supported else "N", "As (cm2)": round(g.area, 3)})
    return pd.DataFrame(rows)


def summary_lines(res):
    lay, t = res["layout"], res["ties"]
    g = max(res["rows"], key=lambda r: r["DC"])
    return [
        f"Status: {res['status']}",
        f"Main bars: {lay.describe()}   ladder step: {lay.step_name}",
        f"As = {lay.As:.1f} cm2, ρ = {lay.rho * 100:.2f} %",
        f"max D/C = {res['maxDC']:.3f} ({g['combo']}: Pu {g['Pu']:.1f} t, Mux {g['Mux']:.1f}, Muy {g['Muy']:.1f} t-m)",
        f"φPn,max = {res['section'].phiPn_max / 1e3:.1f} t  (Po = {res['section'].Po / 1e3:.1f} t)",
        f"δ max = {res['delta_max']:.3f}",
        f"Ties: DB{lay.tie_db} @{t['s_lo'] * 10:.0f} mm within lo = {t['rules']['lo'] * 10:.0f} mm, "
        f"@{t['s_out'] * 10:.0f} mm outside; legs x/y = {lay.legs()[0]}/{lay.legs()[1]}",
        f"so = min(8db, 24dt, c/2, 300) = {t['rules']['so_raw'] * 10:.0f} -> {t['rules']['so'] * 10:.0f} mm; "
        f"outside ≤ min(2so, 16db, 48dt, cmin, shear smax)",
        "Shear actions: " + (", ".join(t["actions"]) if t["actions"] else "none"),
        "Lap Lst (Class B): " + ", ".join(f"DB{d} {v:.0f} mm" if v else f"DB{d} [CHECK - not given]" for d, v in res["lap"].items()),
    ]


# ---------------------------------------------------------------- PDF
TH_FONTS = ("Tahoma", "Leelawadee UI", "Leelawadee", "TH Sarabun New", "Noto Sans Thai", "Loma", "Garuda", "Norasi")
TH_MAP = {"กฎกระทรวง 2566 ข้อ 8 วรรคสอง": "Ministerial Reg. B.E.2566 cl.8 para 2",
          "กฎกระทรวง 2566 ข้อ 7": "Ministerial Reg. B.E.2566 cl.7", "ข้อ 7": "cl.7",
          "ประกาศ มท. 2564 ข้อ 26(1)": "MOI Notif. B.E.2564 cl.26(1)", "มยผ.": "DPT", "ไม่ระบุ": "-",
          "ก": "Kor (ก)", "ข": "Khor (ข)", "ค": "Khor-khwai (ค)", "ง": "Ngor (ง)"}


def _thai_font():
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in TH_FONTS if n in names), None)


def _ascii(t):
    """Fallback when no Thai font is installed: replace known Thai references by English."""
    for k in sorted(TH_MAP, key=len, reverse=True):
        t = t.replace(k, TH_MAP[k] if len(k) > 1 else TH_MAP[k].split(" (")[0])
    return re.sub(r"[\u0E00-\u0E7F]+", "?", t)


def make_pdf(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    th = _thai_font()
    plt.rcParams["font.family"] = ["DejaVu Sans", th] if th else ["DejaVu Sans"]
    clean = (lambda t: t) if th else _ascii
    from matplotlib.backends.backend_pdf import PdfPages
    from . import plots

    P = res["inp"]["project"]
    pages = []

    def new_page():
        fig = plt.figure(figsize=(8.27, 11.69))
        pages.append(fig)
        return fig

    def header(fig, title):
        fig.text(0.06, 0.965, "CEDA Co., Ltd. - RC COLUMN DESIGN", fontsize=9, weight="bold")
        fig.text(0.06, 0.95, f"Project: {P.get('name', '')}   Location: {P.get('location', '')}   Building: {P.get('building', '')}",
                 fontsize=7)
        fig.text(0.06, 0.938, f"Job no.: {P.get('job_no', '')}   Column mark: {P.get('mark', '')}   Band: {P.get('band', '')}",
                 fontsize=7)
        fig.text(0.94, 0.965, title, fontsize=8, ha="right")
        fig.add_artist(plt.Line2D([0.06, 0.94], [0.93, 0.93], lw=0.6, color="k", transform=fig.transFigure))

    def text_block(fig, lines, y0, size=7, dy=0.0145, x=0.06):
        for ln in lines:
            fig.text(x, y0, clean(ln), fontsize=size)
            y0 -= dy
        return y0

    def table(fig, df, rect, fs=5.5, fmt=2):
        ax = fig.add_axes(rect)
        ax.axis("off")
        cells = [[f(v, fmt) if isinstance(v, float) else clean(str(v)) for v in row] for row in df.values]
        heads = [clean(c) for c in df.columns]
        w = [max([len(h)] + [len(r[i]) for r in cells]) + 2 for i, h in enumerate(heads)]
        w = [x / sum(w) for x in w]
        tb = ax.table(cellText=cells, colLabels=heads, loc="upper center", cellLoc="center", colWidths=w)
        tb.auto_set_font_size(False)
        tb.set_fontsize(fs)
        tb.scale(1, 1.25)
        return ax

    # page 1 - criteria and summary
    fig = new_page()
    header(fig, "1. Design criteria & summary")
    y = text_block(fig, ["1. DESIGN CRITERIA"], 0.91, 9)
    crit = pd.DataFrame(criteria_rows(res), columns=["Item", "Value", "Basis"])
    table(fig, crit, [0.04, 0.53, 0.92, 0.36], fs=5.8)
    y = text_block(fig, ["2. RESULT SUMMARY"], 0.47, 9)
    y = text_block(fig, summary_lines(res), y - 0.005, 7)
    y = text_block(fig, ["3. REVIEW CHECKPOINTS (designer decision required)"], y - 0.01, 9)
    y = text_block(fig, [f"- {c}"[:150] for c in res["checkpoints"]] or ["- none"], y - 0.005, 6.5)
    y = text_block(fig, ["4. NOTES"], y - 0.01, 9)
    text_block(fig, [f"- [{t}] {s}"[:160] for t, s in res["notes"]], y - 0.005, 6.5)

    # page 2 - figures
    fig = new_page()
    header(fig, "2. Section & interaction")
    plots.mpl_section(fig.add_axes([0.08, 0.55, 0.38, 0.35]), res)
    plots.mpl_surface(fig.add_axes([0.52, 0.55, 0.44, 0.35], projection="3d"), res)
    plots.mpl_pm(fig.add_axes([0.08, 0.28, 0.38, 0.22]), res, "x")
    plots.mpl_pm(fig.add_axes([0.56, 0.28, 0.38, 0.22]), res, "y")
    plots.mpl_mm(fig.add_axes([0.08, 0.04, 0.38, 0.19]), res)
    sl = res["slender"]
    text_block(fig, ["Section properties", f"Ag = {res['section'].Ag:.0f} cm2, As = {res['layout'].As:.1f} cm2",
                     f"Ig,x = {sl['Igx']:.4g} cm4, Ig,y = {sl['Igy']:.4g} cm4",
                     f"Ise,x = {sl['Ise_x']:.4g} cm4, Ise,y = {sl['Ise_y']:.4g} cm4 (true bar positions)",
                     f"Ec = 15100√f'c = {15100 * res['inp']['material']['fc'] ** 0.5:.0f} ksc, Es = 2.04e6 ksc",
                     f"(EI)eff = (0.2EcIg + EsIse)/(1+βd); Pc = π²(EI)eff/(kLu)²",
                     f"δ = 1/(1 - Pu/0.75Pc) ≥ 1; M2,min = Pu(1.5 + 0.03h) cm",
                     "Mu = sign(M)·max(|M|, M2,min)·δ when kLu/r > 22"], 0.21, 6.5, x=0.52)

    # page 3 - combos
    fig = new_page()
    header(fig, "3. Load combinations, slenderness & D/C")
    ct = combo_table(res)
    n = 34
    for k in range(0, max(len(ct), 1), n):
        if k:
            fig = new_page()
            header(fig, "3. Load combinations (cont.)")
        table(fig, ct.iloc[k:k + n], [0.02, 0.1, 0.96, 0.8], fs=5)
    text_block(fig, ["Allowed combinations (กฎกระทรวง 2566 ข้อ 7, SDL as D): " + "; ".join(ALLOWED_COMBOS),
                     "Wind combinations follow the skill rule (1.6W) - verify against ข้อ 7 of the regulation."], 0.06, 6)

    # page 4 - ladder & shear
    fig = new_page()
    header(fig, "4. Bar ladder, shear & ties")
    text_block(fig, ["Bar build-up ladder (lowest passing step governs)"], 0.91, 8)
    table(fig, ladder_table(res), [0.04, 0.55, 0.92, 0.34], fs=5.5, fmt=3)
    text_block(fig, ["Shear (each direction separately, Vc = 0.53√f'c bw d, φ = 0.85)"], 0.5, 8)
    table(fig, shear_table(res), [0.02, 0.3, 0.96, 0.18], fs=4.6)
    ve = [res["ties"]["lo_check"][d]["Ve_note"] for d in "xy" if res["ties"]["lo_check"][d]["Ve_note"]]
    text_block(fig, ve + summary_lines(res)[6:9], 0.26, 6.5)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for i, fg in enumerate(pages, 1):
            fg.text(0.06, 0.02, f"Calculated: {P.get('calc_by', '')}   Approved: {P.get('approved_by', '')}   "
                                f"Date: {P.get('date', '')}", fontsize=6)
            fg.text(0.94, 0.02, f"Page {i}/{len(pages)}", fontsize=6, ha="right")
            pdf.savefig(fg)
            plt.close(fg)
    return buf.getvalue()


def make_excel(res):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(criteria_rows(res), columns=["Item", "Value", "Basis"]).to_excel(xw, sheet_name="Criteria", index=False)
        pd.DataFrame({"Summary": summary_lines(res)}).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame({"Checkpoints": res["checkpoints"] or ["none"]}).to_excel(xw, sheet_name="Checkpoints", index=False)
        pd.DataFrame(res["notes"], columns=["Tag", "Note"]).to_excel(xw, sheet_name="Notes", index=False)
        combo_table(res).to_excel(xw, sheet_name="Combos_DC", index=False)
        ladder_table(res).to_excel(xw, sheet_name="Ladder", index=False)
        shear_table(res).to_excel(xw, sheet_name="Shear", index=False)
        bar_table(res).to_excel(xw, sheet_name="Bars_for_Revit", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col) + 2))
    return buf.getvalue()
