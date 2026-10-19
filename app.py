"""CEDA RC Column Design - Streamlit app (ceda-column-design rules v1).

Run:  streamlit run app.py
"""
import datetime as dt

import pandas as pd
import streamlit as st

from engine import plots
from engine.design import run_design, beta_d, ALLOWED_COMBOS
from engine.drawing import make_dxf, dxf_bytes, preview_png
from engine.etabs import read_tables, column_forces, combo_factors
from engine.layout import build_layout, ladder_steps
from engine.report import (criteria_rows, combo_table, ladder_table, shear_table, bar_table, summary_lines,
                           make_pdf, make_excel)

st.set_page_config(page_title="CEDA Column Design", page_icon="🏗️", layout="wide")

# Known CEDA lap lengths (Class B, "other bar", S-00-04-04) from the skill - all others must come from the project table
KNOWN_LAP = {400: {25: 1550, 28: 1875, 32: 2325}, 560: {25: 1325, 28: 1600, 32: 1975}}
COMBO_COLS = ["include", "name", "type", "fD", "fL", "fE", "fW", "Pu", "Mx", "My", "Vx", "Vy"]
DEFAULT_COMBOS = pd.DataFrame([
    [True, "U1 = 1.4D+1.7L", "Gravity", 1.4, 1.7, 0.0, 0.0, 850.0, 12.0, 6.0, 3.0, 5.0],
    [True, "U2 = 0.75(1.4D+1.7L)+EX", "Seismic", 1.05, 1.275, 1.0, 0.0, 640.0, 45.0, 10.0, 6.0, 18.0],
    [True, "U3 = 0.9D-EX", "Seismic", 0.9, 0.0, -1.0, 0.0, 330.0, -42.0, -8.0, 6.0, 17.0],
], columns=COMBO_COLS)

ss = st.session_state
ss.setdefault("combos", DEFAULT_COMBOS.copy())
ss.setdefault("res", None)

st.title("CEDA RC Column Design")
st.caption("Rectangular tied column · one mark / one band · กฎกระทรวง 2566 + ACI 318-19 + มยผ. 1301/1302-61 · "
           "units: cm, ksc, t, t-m · ผลลัพธ์เป็น DRAFT ต้องตรวจโดยวิศวกรผู้ออกแบบ")

# =============================================================== SIDEBAR - design criteria (skill Step 1)
sb = st.sidebar
sb.header("1. Design criteria")
with sb.expander("1.1 Project (header / footer)", expanded=False):
    proj = {
        "name": st.text_input("Project", "Siam Pan Pacific Hotel"),
        "location": st.text_input("Location", "Bangkok"),
        "building": st.text_input("Building", "Tower"),
        "job_no": st.text_input("Job no.", ""),
        "mark": st.text_input("Column mark", "C1"),
        "band": st.text_input("Band / story range (drawing level)", "B2 - 2F",
                              help="ETABS story N = column below level N; drawing level = from the level below to N"),
        "date": str(st.date_input("Date", dt.date.today())),
        "calc_by": st.text_input("Calculated by", ""),
        "approved_by": st.text_input("Approved by", ""),
    }

with sb.expander("1.2 Seismic", expanded=True):
    seis_req = st.checkbox("Seismic design required", True)
    zone = st.text_input("Seismic zone", "2", disabled=not seis_req)
    imp = st.text_input("Importance factor Ie", "1.0", disabled=not seis_req)
    cat = st.selectbox("Design category", ["ก", "ข", "ค", "ง"], index=2, disabled=not seis_req)
    system = st.text_input("Lateral system (มยผ. Table 2.3-1)", "Building frame + ordinary RC shear wall",
                           disabled=not seis_req)
    c1, c2, c3 = st.columns(3)
    R = c1.number_input("R", 0.0, 10.0, 5.0, 0.5, disabled=not seis_req)
    Om = c2.number_input("Ω0", 0.0, 5.0, 2.5, 0.5, disabled=not seis_req)
    Cd = c3.number_input("Cd", 0.0, 10.0, 4.5, 0.5, disabled=not seis_req)
    col_type = st.selectbox("Column type", ["Gravity", "IMF", "SMF"], index=1,
                            help="Minimum ties = IMF level for every column (ประกาศ มท. 2564 ข้อ 26(1)). "
                                 "SMF detailing (ACI 18.7) not covered in v1.")
    Q = st.number_input("Stability index Q (max of story)", 0.0, 1.0, 0.02, 0.005, format="%.3f",
                        help="ACI 318-19 6.6.4.3: Q > 0.05 → sway → STOP (δs not automated)")
    q_given = st.checkbox("Q from Story Forces/Drifts available", True)
    if seis_req and cat == "ง":
        st.warning("Category ง + ordinary walls: H ≤ 60 m and seismic force +40 % (มยผ.)")

with sb.expander("1.3 Materials", expanded=True):
    c1, c2 = st.columns(2)
    fc = c1.number_input("f'c of this band (ksc)", 210.0, 700.0, 400.0, 10.0)
    fc_typ = c2.number_input("Typical f'c of project (ksc)", 210.0, 700.0, 400.0, 10.0)
    fy = c1.number_input("fy main (ksc)", 2400.0, 5000.0, 4000.0, 100.0)
    fyt = c2.number_input("fyt ties (ksc)", 2400.0, 5000.0, 4000.0, 100.0)
    cover = c1.number_input("Clear cover to tie (mm)", 20.0, 75.0, 40.0, 5.0)
    tie_db = c2.selectbox("Tie size", [12, 16], index=0)
    fc_slab = c1.number_input("Slab f'c (ksc) – ACI 15.5", 0.0, 700.0, 280.0, 10.0)
    dagg = c2.number_input("Max aggregate (mm)", 10.0, 40.0, 25.0, 5.0)

with sb.expander("1.4 Section & slenderness", expanded=True):
    c1, c2 = st.columns(2)
    b = c1.number_input("b = t2 (cm)", 20.0, 400.0, 60.0, 5.0)
    h = c2.number_input("h = t3 (cm)", 20.0, 400.0, 60.0, 5.0)
    Lu = c1.number_input("Lu (cm)", 50.0, 3000.0, 350.0, 5.0)
    k = c2.number_input("k (non-sway)", 0.5, 1.0, 1.0, 0.05)
    size_restricted = st.checkbox("Column size restricted (ρ up to 8 % with approval)", False)
    approved_rho = st.checkbox("Approved ρ > 6 % (approved_rho_over_6)", False, disabled=not size_restricted)
    c1, c2 = st.columns(2)
    nx = c1.number_input("Bars on b-face (0 = auto)", 0, 40, 0)
    ny = c2.number_input("Bars on h-face (0 = auto)", 0, 40, 0)

with sb.expander("1.5 βd (creep)", expanded=False):
    bd_mode = st.radio("βd from", ["Unfactored axial DL/SDL/LL", "Direct value"], horizontal=True)
    if bd_mode.startswith("Unf"):
        c1, c2, c3 = st.columns(3)
        PDL = c1.number_input("P DL (t)", 0.0, 1e5, 400.0)
        PSDL = c2.number_input("P SDL (t)", 0.0, 1e5, 80.0)
        PLL = c3.number_input("P LL (t)", 0.0, 1e5, 120.0)
        bd = beta_d(PDL, PSDL, PLL)
    else:
        bd = st.number_input("βd", 0.0, 1.0, 0.6, 0.05)
    st.caption(f"βd = {bd:.3f}  (Rev.1: [1.4(DL+SDL)+0.25·1.7LL]/[1.4(DL+SDL)+1.7LL])")

with sb.expander("1.6 Lap table S-00-04-04 (Class B, mm)", expanded=False):
    known = KNOWN_LAP.get(int(fc), {})
    lap_df = st.data_editor(pd.DataFrame({"bar": ["DB20", "DB25", "DB28", "DB32"],
                                          "Lst (mm)": [known.get(d) for d in (20, 25, 28, 32)]}),
                            key=f"lap_{int(fc)}", hide_index=True, disabled=["bar"])
    st.caption("ค่าที่ทราบ: 400 ksc / 560 ksc (DB25/28/32). ค่าอื่นต้องกรอกจากตารางของโครงการ — ห้ามเดา")
    lap = {int(r["bar"][2:]): (None if pd.isna(r["Lst (mm)"]) else float(r["Lst (mm)"])) for _, r in lap_df.iterrows()}

# bar step options (ladder) for manual selection
_base = build_layout(b, h, cover / 10, tie_db, nx=nx or None, ny=ny or None)
_steps = ladder_steps(_base)
with sb.expander("1.7 Bar selection", expanded=False):
    opts = ["Auto – lowest passing ladder step"] + [f"{i}: {s['name']}" for i, s in enumerate(_steps)]
    pick = st.selectbox("Main bars", opts)
    manual_step = None if pick.startswith("Auto") else int(pick.split(":")[0])
    full_ladder = st.checkbox("Evaluate the full ladder (slower, for the table)", False)
    st.caption(f"Grid: {_base.nx} bars on b-face × {_base.ny} on h-face. {_base.grid_note}")

# =============================================================== LOADS
st.header("2. Load combinations (factored, t / t-m)")
st.markdown("P + compression. **Mx = M3 (about axis bending h)**, **My = M2**, **Vx = V3 (along b)**, **Vy = V2 (along h)**. "
            "fD/fL/fE/fW = combo factors for the ข้อ 7 check (SDL counted as D) – leave blank if unknown.")

with st.expander("Import from ETABS (Excel export: Element Forces - Columns [+ Load Combination Definitions])"):
    up = st.file_uploader("ETABS workbook (.xlsx)", type=["xlsx", "xls"])
    if up is not None:
        try:
            tables = read_tables(up)
            ef_name = next((n for n in tables if "Element Forces - Columns" in n), None)
            if ef_name is None:
                st.error("ไม่พบตาราง 'Element Forces - Columns'")
            else:
                ef = tables[ef_name]
                st.caption(f"Units: P [{ef.attrs['units'].get('P')}], M3 [{ef.attrs['units'].get('M3')}]")
                c1, c2 = st.columns(2)
                story = c1.selectbox("Story", list(dict.fromkeys(ef["Story"].astype(str))))
                column = c2.selectbox("Column label", list(dict.fromkeys(ef["Column"].astype(str))))
                lcd = next((tables[n] for n in tables if "Load Combination Definitions" in n), None)
                facs = {}
                if lcd is not None:
                    lc_col = next((c for c in lcd.columns if c.lower() in ("load name", "case name", "load case")), None)
                    loads = sorted(set(lcd[lc_col].dropna().astype(str))) if lc_col else []
                    st.markdown("**Map load cases to D / L / E / W** (for the ข้อ 7 combo check)")
                    c1, c2, c3, c4 = st.columns(4)
                    dl = c1.multiselect("D (DL, SDL)", loads, [x for x in loads if x.upper() in ("DL", "SDL", "DEAD", "SD")])
                    ll = c2.multiselect("L", loads, [x for x in loads if x.upper() in ("LL", "LIVE", "LR")])
                    el = c3.multiselect("E", loads, [])
                    wl = c4.multiselect("W", loads, [])
                    facs = combo_factors(lcd, set(dl), set(ll), set(el), set(wl))
                if st.button("Load forces into the combo table"):
                    rows = column_forces(ef, story, column)
                    new = []
                    for r in rows:
                        fD, fL, fE, fW = facs.get(r["name"].split(" ")[0], (None, None, None, None))
                        new.append([True, r["name"], "Unclassified", fD, fL, fE, fW,
                                    r["Pu"], r["Mx"], r["My"], r["Vx"], r["Vy"]])
                    ss.combos = pd.DataFrame(new, columns=COMBO_COLS)
                    ss.res = None
                    st.success(f"{len(new)} cases loaded ({story} / {column}). ตั้ง Type ของทุก combo ก่อน run "
                               "(ห้ามตัดสินจากชื่อ combo)")
        except Exception as e:  # noqa: BLE001 - show reader errors to the user
            st.error(f"Read error: {e}")

combos_df = st.data_editor(
    ss.combos, num_rows="dynamic", width="stretch", key="combo_editor",
    column_config={
        "include": st.column_config.CheckboxColumn("Use"),
        "type": st.column_config.SelectboxColumn("Type", options=["Gravity", "Seismic", "Wind", "Unclassified"]),
        **{c: st.column_config.NumberColumn(c, format="%.3f") for c in ("fD", "fL", "fE", "fW")},
        **{c: st.column_config.NumberColumn(c + (" (t)" if c in ("Pu", "Vx", "Vy") else " (t-m)"), format="%.2f")
           for c in ("Pu", "Mx", "My", "Vx", "Vy")},
    })
st.caption("Combo check per กฎกระทรวง 2566 ข้อ 7: " + " · ".join(ALLOWED_COMBOS) +
           " (wind per skill rule 1.6W – verify)")

# =============================================================== RUN
st.header("3. Run")
confirm = st.checkbox("ยืนยันว่า design criteria ทั้งหมด (ข้อ 1.1–1.7) ได้รับการยืนยันจากผู้ออกแบบแล้ว "
                      "— ไม่ใช้ค่าจากโครงการอื่นโดยไม่ยืนยัน")


def build_input():
    combos = []
    for _, r in combos_df.iterrows():
        if pd.isna(r["name"]) or pd.isna(r["Pu"]):
            continue
        num = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
        combos.append({"include": bool(r["include"]), "name": str(r["name"]), "type": r["type"] or "Unclassified",
                       "fD": num(r["fD"]), "fL": num(r["fL"]), "fE": num(r["fE"]), "fW": num(r["fW"]),
                       "Pu": float(r["Pu"]), "Mx": num(r["Mx"]) or 0.0, "My": num(r["My"]) or 0.0,
                       "Vx": num(r["Vx"]) or 0.0, "Vy": num(r["Vy"]) or 0.0})
    return {
        "project": proj,
        "seismic": {"required": seis_req, "zone": zone, "importance": imp, "category": cat if seis_req else "-",
                    "system": system, "R": R, "Omega0": Om, "Cd": Cd, "column_type": col_type},
        "material": {"fc": fc, "fc_typ": fc_typ, "fy": fy, "fyt": fyt, "cover": cover / 10, "tie_db": tie_db,
                     "fc_slab": fc_slab or None, "dagg": dagg / 10},
        "section": {"b": b, "h": h, "Lu": Lu, "k": k, "size_restricted": size_restricted,
                    "approved_rho_over_6": approved_rho and size_restricted, "nx": nx or None, "ny": ny or None},
        "lap": lap, "bd": bd, "Q": Q if q_given else None, "combos": combos,
        "manual_step": manual_step, "full_ladder": full_ladder,
    }


if st.button("▶ Run design", type="primary", disabled=not confirm):
    ss.combos = combos_df
    with st.spinner("Building 3D φ-surface and checking ladder steps ..."):
        res = run_design(build_input())
    if "layout" in res:
        res["dxf"] = make_dxf(res)
        res["png"] = preview_png(res["dxf"])
    ss.res = res
if not confirm:
    st.info("ทำเครื่องหมายยืนยัน design criteria ก่อน จึงจะ run ได้ (Skill Step 1: ห้ามคำนวณก่อนยืนยัน)")

res = ss.res
if res is None:
    st.stop()

# =============================================================== RESULTS
st.header("4. Results")
status = res["status"]
color = "green" if status.startswith("OK") else ("orange" if status in ("ASK_RHO", "CHECK") else "red")
st.markdown(f"### Status: :{color}[{status}]")
if "layout" not in res:
    for c in res["checkpoints"]:
        st.error(c)
    st.stop()

lay, sec = res["layout"], res["section"]
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Main bars", f"{lay.nbars} bars", lay.step_name, delta_color="off")
m2.metric("ρ", f"{lay.rho * 100:.2f} %")
m3.metric("max D/C", f"{res['maxDC']:.3f}")
m4.metric("δ max", f"{res['delta_max']:.2f}")
m5.metric(f"Ties DB{lay.tie_db} (mm)", f"@{res['ties']['s_lo'] * 10:.0f}/{res['ties']['s_out'] * 10:.0f}",
          f"lo {res['ties']['rules']['lo'] * 10:.0f} mm", delta_color="off")

if res["checkpoints"]:
    with st.container(border=True):
        st.markdown("**Review checkpoints – ผู้ออกแบบต้องตัดสินใจ**")
        for c in res["checkpoints"]:
            st.warning(c)

tabs = st.tabs(["3D interaction surface", "P-M / Mx-My", "Calculation report", "Drawing preview", "Export"])

with tabs[0]:
    st.plotly_chart(plots.surface_3d(res), width="stretch")
    st.caption("Capped φ-surface (convex hull of NA angle θ × depth c). D/C radial from origin; "
               "capped ⇒ D/C = max(uncapped, Pu/φPn,max). Red = D/C > 1. Orange line = ray of the governing combo.")

with tabs[1]:
    c1, c2 = st.columns(2)
    c1.plotly_chart(plots.pm_2d(res, "x"), width="stretch")
    c2.plotly_chart(plots.pm_2d(res, "y"), width="stretch")
    st.plotly_chart(plots.mm_2d(res), width="stretch")

with tabs[2]:
    st.subheader("1. Design criteria")
    st.dataframe(pd.DataFrame(criteria_rows(res), columns=["Item", "Value", "Basis"]), hide_index=True,
                 width="stretch")
    st.subheader("2. Summary")
    st.code("\n".join(summary_lines(res)), language=None)
    st.subheader("3. Load combinations, slenderness & D/C")
    st.dataframe(combo_table(res).style.format(precision=3), hide_index=True, width="stretch")
    st.subheader("4. Bar build-up ladder")
    st.dataframe(ladder_table(res).style.format(precision=3), hide_index=True, width="stretch")
    st.subheader("5. Shear & ties")
    st.dataframe(shear_table(res).style.format(precision=2), hide_index=True, width="stretch")
    for d in "xy":
        if res["ties"]["lo_check"][d]["Ve_note"]:
            st.caption(f"{'Vx' if d == 'x' else 'Vy'}: {res['ties']['lo_check'][d]['Ve_note']}  (มยผ. 5.2.7.2)")
    st.subheader("6. Bar coordinates (for Revit)")
    st.dataframe(bar_table(res), hide_index=True, width="stretch")
    st.subheader("7. Notes")
    for t, s in res["notes"]:
        st.markdown(f"- **[{t}]** {s}")

with tabs[3]:
    c1, c2 = st.columns([3, 2])
    c1.image(res["png"], caption="Table of Column – DRAFT (rendered from the exported DXF)", width="stretch")
    c2.markdown("**DXF layers**\n\n- A-DETL-GENF – outline / table\n- CED_0_13_Solid – outer hoop\n"
                "- CED_0_10_Solid – inner hoops, crossties\n- CED_0_18_Solid – main bars (solid)\n"
                "- S-DIMS – dimensions\n- G-ANNO-TEXT – text\n- G-ANNO-CHECK – [CHECK] lines (freeze before issue)")
    c2.caption("Layer assignment ของ CED_0_xx_Solid เป็น Assumption – ตรวจกับ CAD standard ของ CEDA")

with tabs[4]:
    job = (proj["job_no"] or proj["name"] or "Job").replace(" ", "_")
    mark = proj["mark"] or "C"
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Calculation report (PDF)", make_pdf(res), f"{job}_{mark}_Column_Calc.pdf",
                       "application/pdf", width="stretch")
    c2.download_button("⬇ Calculation back-up (Excel)", make_excel(res), f"{job}_{mark}_Column_Calc.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    c3.download_button("⬇ Drawing (DXF, mm)", dxf_bytes(res["dxf"]), f"{job}_{mark}_Table_of_Column_DRAFT.dxf",
                       "application/dxf", width="stretch")
    st.caption("Draft only – not a construction drawing. Report in English (PDF); Thai references are kept when a "
               "Thai font (Tahoma/Leelawadee/TH Sarabun New) is installed, otherwise they are transliterated.")
