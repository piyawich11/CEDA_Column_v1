"""Design orchestration for one column mark / band (CEDA column design rules v1).

Input forces per combo in t and t-m (P + compression). Internally kg, cm.
"""
import copy
import math

import numpy as np

from .layout import build_layout, ladder_steps, apply_step, add_crossties
from .materials import BAR_AREA, ES, Ec, fyt_shear
from .section import Section

CODE, PRACT, EJ, ASSUME = "Code requirement", "Common practice", "Engineering judgment", "Assumption"

# กฎกระทรวงกำหนดการออกแบบโครงสร้างอาคาร ... พ.ศ. 2566 ข้อ 7 (SDL counted as D); factors (D, L, E, W)
ALLOWED_COMBOS = {
    "1.4D+1.7L": (1.4, 1.7, 0.0, 0.0),
    "0.75(1.4D+1.7L)+1.0E": (1.05, 1.275, 1.0, 0.0),
    "0.9D+1.0E": (0.9, 0.0, 1.0, 0.0),
    "0.75(1.4D+1.7L)+1.6W": (1.05, 1.275, 0.0, 1.6),
    "0.9D+1.6W": (0.9, 0.0, 0.0, 1.6),
}


def floor_to(x, step):
    return math.floor(x / step + 1e-9) * step


def ceil_to(x, step):
    return math.ceil(x / step - 1e-9) * step


def check_combo(fD, fL, fE, fW, tol=0.011):
    vals = [fD, fL, fE, fW]
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in vals):
        return None
    for name, ref in ALLOWED_COMBOS.items():
        if all(abs(abs(v) - r) <= tol if i >= 2 else abs(v - r) <= tol for i, (v, r) in enumerate(zip(vals, ref))):
            return name
    return False


def beta_d(DL, SDL, LL):
    """beta_d (Rev.1, conservative) = [1.4(DL+SDL) + 0.25*1.7LL] / [1.4(DL+SDL) + 1.7LL]."""
    den = 1.4 * (DL + SDL) + 1.7 * LL
    return 0.0 if den <= 0 else (1.4 * (DL + SDL) + 0.25 * 1.7 * LL) / den


# ---------------------------------------------------------------------------------------------
def slender_dir(Pu, M, dim, Ig, Ise, fc, kLu, bd):
    """Non-sway magnification in one direction (ACI 318-19 6.6.4). Units kg, cm."""
    r = 0.3 * dim
    klr = kLu / r
    out = {"klr": klr, "delta": 1.0, "Mu": M, "Pc": None, "M2min": None, "slender": klr > 22.0}
    if not out["slender"] or Pu <= 0:
        return out
    EI = (0.2 * Ec(fc) * Ig + ES * Ise) / (1.0 + bd)                 # ACI 6.6.4.4.4(b) form with Ise
    Pc = math.pi ** 2 * EI / kLu ** 2
    M2min = Pu * (1.5 + 0.03 * dim)                                    # ACI 6.6.4.5.4 (cm)
    out.update(Pc=Pc, M2min=M2min, EI=EI)
    if Pu >= 0.75 * Pc:
        out.update(delta=float("inf"), Mu=float("inf"))
        return out
    delta = max(1.0, 1.0 / (1.0 - Pu / (0.75 * Pc)))                  # Cm = 1.0 (practice)
    sgn = 1.0 if M >= 0 else -1.0
    out.update(delta=delta, Mu=sgn * max(abs(M), M2min) * delta)
    return out


def evaluate(lay, inp, combos):
    m, s = inp["material"], inp["section"]
    sec = Section(s["b"], s["h"], m["fc"], m["fy"], lay.bars_xyA(), nfib=inp.get("nfib", 40))
    sec.build_hull()
    bars = np.array(lay.bars_xyA())
    Ise_x = float((bars[:, 2] * bars[:, 1] ** 2).sum())
    Ise_y = float((bars[:, 2] * bars[:, 0] ** 2).sum())
    Igx, Igy = s["b"] * s["h"] ** 3 / 12, s["h"] * s["b"] ** 3 / 12
    kLu = s["k"] * s["Lu"]
    rows = []
    for c in combos:
        Pu, Mx, My = c["Pu"] * 1e3, c["Mx"] * 1e5, c["My"] * 1e5
        bd = c.get("bd", inp["bd"])
        sx = slender_dir(Pu, Mx, s["h"], Igx, Ise_x, m["fc"], kLu, bd)
        sy = slender_dir(Pu, My, s["b"], Igy, Ise_y, m["fc"], kLu, bd)
        if math.isinf(sx["delta"]) or math.isinf(sy["delta"]):
            dc, dcu = float("inf"), float("inf")
        else:
            dc, dcu = sec.dc(Pu, sx["Mu"], sy["Mu"])
        rows.append({"combo": c["name"], "type": c["type"], "Pu": c["Pu"], "Mx": c["Mx"], "My": c["My"],
                     "klr_x": sx["klr"], "klr_y": sy["klr"], "delta_x": sx["delta"], "delta_y": sy["delta"],
                     "Pc_x": None if sx["Pc"] is None else sx["Pc"] / 1e3,
                     "Pc_y": None if sy["Pc"] is None else sy["Pc"] / 1e3,
                     "Mux": sx["Mu"] / 1e5, "Muy": sy["Mu"] / 1e5, "bd": bd, "DC": dc, "DC_uncapped": dcu,
                     "PuPmax": Pu / sec.phiPn_max})
    return sec, rows, {"Ise_x": Ise_x, "Ise_y": Ise_y, "Igx": Igx, "Igy": Igy, "kLu": kLu}


# ---------------------------------------------------------------------------------------------
def tie_rules(lay, inp):
    s, m = inp["section"], inp["material"]
    dt = lay.tie_db / 10
    db_min = min(g.db for g in lay.groups) / 10
    cmin, cmax = min(s["b"], s["h"]), max(s["b"], s["h"])
    so_raw = min(8 * db_min, 24 * dt, cmin / 2, 30.0)
    so = floor_to(so_raw, 2.5)
    lo = ceil_to(max(s["Lu"] / 6, cmax, 50.0), 5.0)
    sout_raw = min(2 * so, 16 * db_min, 48 * dt, cmin)
    return {"so_raw": so_raw, "so": so, "lo": lo, "sout_raw": sout_raw, "db_min": db_min}


def shear_check(lay, inp, combos, sec, s_zone, fyt_v):
    """Shear in each direction separately. Returns per-direction governing dict."""
    S, M = inp["section"], inp["material"]
    fc = M["fc"]
    Ab = BAR_AREA[lay.tie_db]
    db_max = max(g.db for g in lay.groups) / 10
    edge = M["cover"] + lay.tie_db / 10 + db_max / 2
    legs_x, legs_y = lay.legs()
    Ag = S["b"] * S["h"]
    res = {}
    seis = [c for c in combos if c["type"] == "Seismic"]
    for d, bw, dd, legs, key, axis in (("x", S["h"], S["b"] - edge, legs_x, "Vx", "y"),
                                       ("y", S["b"], S["h"] - edge, legs_y, "Vy", "x")):
        Av = legs * Ab
        cases = [(c["name"], abs(c[key]) * 1e3, c["Pu"] * 1e3) for c in combos]
        Ve_note = ""
        if inp["seismic"]["column_type"] in ("IMF", "SMF") and seis:
            Ps = [c["Pu"] * 1e3 for c in seis]
            Pn, Mn = sec.uniaxial(axis, nominal=True)
            Pn2, Mn2 = sec.uniaxial(axis + "-", nominal=True)
            o, o2 = np.argsort(Pn), np.argsort(Pn2)
            Pr = np.linspace(min(Ps), max(Ps), 60)
            Mn_max = max(np.abs(np.interp(Pr, Pn[o], Mn[o])).max(), np.abs(np.interp(Pr, Pn2[o2], Mn2[o2])).max())
            V1 = 2 * Mn_max / S["Lu"]
            V2 = 2 * max(abs(c[key]) * 1e3 for c in seis)
            Ve = min(V1, V2)
            Ve_note = (f"Ve = min(2Mn/Lu = {V1 / 1e3:.2f} t [Mn,max = {Mn_max / 1e5:.2f} t-m], "
                       f"2 x V,EQ = {V2 / 1e3:.2f} t) = {Ve / 1e3:.2f} t")
            cases.append(("IMF Ve", Ve, min(Ps)))
        worst = None
        for name, Vu, Nu in cases:
            Vc = 0.53 * math.sqrt(fc) * bw * dd
            if Nu < 0:
                Vc *= max(0.0, 1 + Nu / (35.0 * Ag))
            Vs_max = 2.1 * math.sqrt(fc) * bw * dd
            Vs = Av * fyt_v * dd / s_zone
            phiVn = 0.85 * (Vc + min(Vs, Vs_max))
            Avmin = max(0.2 * math.sqrt(fc), 3.5) * bw * s_zone / fyt_v
            need_min = Vu > 0.5 * 0.85 * Vc
            Vs_req = max(0.0, Vu / 0.85 - Vc)
            ok = (Vu <= phiVn + 1e-6) and (not need_min or Av >= Avmin - 1e-9) and Vs_req <= Vs_max
            smax_v = dd / 4 if Vs_req > 1.06 * math.sqrt(fc) * bw * dd else dd / 2
            row = {"dir": d, "case": name, "Vu": Vu / 1e3, "Nu": Nu / 1e3, "bw": bw, "d": dd, "Vc": Vc / 1e3,
                   "legs": legs, "Av": Av, "s": s_zone, "Vs": Vs / 1e3, "Vs_max": Vs_max / 1e3,
                   "phiVn": phiVn / 1e3, "Av_min": Avmin if need_min else 0.0, "Vs_req": Vs_req / 1e3,
                   "ratio": Vu / phiVn if phiVn > 0 else float("inf"), "ok": ok, "smax_v": smax_v,
                   "section_ok": Vs_req <= Vs_max, "legs_req": math.ceil(max(Vs_req * s_zone / (fyt_v * dd),
                                                                         Avmin if need_min else 0) / Ab - 1e-9)}
            if worst is None or (not ok and worst["ok"]) or (ok == worst["ok"] and row["ratio"] > worst["ratio"]):
                worst = row
        worst["Ve_note"] = Ve_note
        res[d] = worst
    return res


def design_ties(lay, inp, combos, sec, notes):
    """Ties per IMF minimum (all columns) + shear; escalation per CEDA rule."""
    m = inp["material"]
    tr = tie_rules(lay, inp)
    fyt_v = fyt_shear(lay.tie_db, m["fyt"])
    s_lo = tr["so"]
    sh0 = shear_check(lay, inp, combos, sec, 10.0, fyt_v)
    smax_v = min(sh0["x"]["smax_v"], sh0["y"]["smax_v"], 60.0)
    s_out = floor_to(min(tr["sout_raw"], smax_v), 2.5)
    actions = []
    for step in ("s15", "crossties", "s10", "fail"):
        sh_lo = shear_check(lay, inp, combos, sec, s_lo, fyt_v)
        sh_out = shear_check(lay, inp, combos, sec, s_out, fyt_v)
        bad = [z for z, sh in (("lo", sh_lo), ("out", sh_out)) if not (sh["x"]["ok"] and sh["y"]["ok"])]
        if not bad:
            break
        if step == "s15":
            if "lo" in bad and s_lo > 15:
                s_lo = 15.0
            if "out" in bad and s_out > 15:
                s_out = 15.0
            actions.append("spacing reduced to 150 mm")
        elif step == "crossties":
            added = 0
            for d in ("x", "y"):
                w = sh_out[d]
                if not w["ok"]:
                    need = max(0, w["legs_req"] - w["legs"])
                    added += add_crossties(lay, "y" if d == "x" else "x", need)
            if added:
                actions.append(f"{added} full-depth crosstie(s) added")
        elif step == "s10":
            s_lo, s_out = min(s_lo, 10.0), min(s_out, 10.0)
            actions.append("spacing reduced to 100 mm")
    else:
        sh_lo = shear_check(lay, inp, combos, sec, s_lo, fyt_v)
        sh_out = shear_check(lay, inp, combos, sec, s_out, fyt_v)
    ok = all(sh[d]["ok"] for sh in (sh_lo, sh_out) for d in "xy")
    sec_ok = all(sh[d]["section_ok"] for sh in (sh_lo, sh_out) for d in "xy")
    return {"rules": tr, "s_lo": s_lo, "s_out": s_out, "fyt_v": fyt_v, "lo_check": sh_lo, "out_check": sh_out,
            "ok": ok, "section_ok": sec_ok, "actions": actions}


# ---------------------------------------------------------------------------------------------
def run_design(inp):
    notes, checkpoints = [], []
    S, M, Z = inp["section"], inp["material"], inp["seismic"]
    status = "OK"

    # ---- combos
    combos = []
    for c in inp["combos"]:
        if not c.get("include", True):
            continue
        chk = check_combo(c.get("fD"), c.get("fL"), c.get("fE"), c.get("fW"))
        c = dict(c)
        c["combo_check"] = "factors not given - not checked" if chk is None else (chk if chk else "NOT per ข้อ 7")
        combos.append(c)
        if chk is False:
            checkpoints.append(f"Combo '{c['name']}' factors (D {c['fD']}, L {c['fL']}, E {c['fE']}, W {c['fW']}) "
                               "do not match กฎกระทรวง 2566 ข้อ 7 - include or exclude?")
        if chk is None:
            checkpoints.append(f"Combo '{c['name']}': factors not given - combo check (ข้อ 7) not done.")
        if c["type"] == "Unclassified":
            checkpoints.append(f"Combo '{c['name']}' type not set (gravity/seismic/wind) - IMF Ve uses seismic combos only.")
    if not combos:
        return {"status": "NO LOADS", "notes": notes, "checkpoints": ["No load combination included."]}

    # ---- sway
    if inp.get("Q") is None:
        checkpoints.append("Stability index Q not given - sway check (ACI 6.6.4.3) not done.")
    elif inp["Q"] > 0.05:
        return {"status": "STOP - SWAY", "notes": notes,
                "checkpoints": [f"Q = {inp['Q']:.3f} > 0.05 (ACI 318-19 6.6.4.3): sway frame - delta_s not automated. STOP."]}

    # ---- seismic reminders
    if Z["required"]:
        if Z["category"] == "ง":
            notes.append((CODE, "Design category ง with ordinary RC walls: building height <= 60 m and seismic force +40 % (มยผ. 1301/1302-61) - confirm the seismic model."))
            notes.append((CODE, "Category ง: deformation compatibility of gravity columns (มยผ. 2.11.5 -> ACI 318-14 18.14) - not covered in v1."))
        if Z["column_type"] == "SMF":
            checkpoints.append("SMF detailing (ACI 18.7: Ash, s <= 6db, hx <= 350 mm, strong column-weak beam) is NOT covered - designed with IMF minimum only.")
            status = "CHECK"
    notes.append((CODE, "Joint transverse reinforcement Av (3.5 c1 s / fy) is not automated - check at beam-column joints."))

    # ---- grid and ladder
    base = build_layout(S["b"], S["h"], M["cover"], M["tie_db"], nx=S.get("nx"), ny=S.get("ny"))
    if base.grid_note:
        notes.append((PRACT, "Bar grid: " + base.grid_note))
    steps = ladder_steps(base)
    rho_lim = 0.08 if S.get("size_restricted") else 0.06
    ladder, chosen = [], None
    manual = inp.get("manual_step")
    for i, st in enumerate(steps):
        lay = apply_step(base, st)
        clear_ok, margin = lay.clear_check(M.get("dagg", 2.5))
        row = {"step": i, "name": st["name"], "bars": lay.describe(), "rho": lay.rho, "clear_ok": clear_ok,
               "DC": None, "status": ""}
        if not clear_ok:
            row["status"] = "skip - clear spacing"
        elif lay.rho > rho_lim + 1e-9:
            row["status"] = f"skip - rho > {rho_lim * 100:.0f} %"
        else:
            sec, rows, _ = evaluate(lay, inp, combos)
            row["DC"] = max(r["DC"] for r in rows)
            row["status"] = "PASS" if row["DC"] <= 1.0 else "fail"
        ladder.append(row)
        if manual is not None:
            if i == manual:
                chosen = (i, lay)
        elif chosen is None and row["status"] == "PASS":
            chosen = (i, lay)
            if not inp.get("full_ladder"):
                break

    if chosen is None:
        if manual is not None:
            return {"status": "INVALID STEP", "notes": notes, "checkpoints": ["Selected step not available."]}
        evaluated = [i for i, r in enumerate(ladder) if r["DC"] is not None]
        lay = apply_step(base, steps[evaluated[-1] if evaluated else 0])
        status = "REVISE"
        checkpoints.append("REVISE: no bar step passes. Recommended: enlarge the weak dimension "
                           "(check kLu first). Detailing rules are not relaxed.")
    else:
        lay = chosen[1]

    sec, rows, sl = evaluate(lay, inp, combos)
    maxdc = max(r["DC"] for r in rows)
    if manual is not None and maxdc > 1.0:
        status = "REVISE"
    if lay.rho > 0.06 + 1e-9:
        if not S.get("approved_rho_over_6"):
            status = "ASK_RHO"
            checkpoints.append(f"ASK_RHO: rho = {lay.rho * 100:.2f} % (6 % < rho <= 8 %) - designer approval required (approved_rho_over_6).")
        else:
            notes.append((EJ, f"rho = {lay.rho * 100:.2f} % > 6 % approved by the designer (size restricted)."))
    if lay.rho < 0.01:
        notes.append((CODE, f"rho = {lay.rho * 100:.2f} % < 1 % (ACI 318-19 10.6.1.1) - check."))
    dmax = max(max(r["delta_x"], r["delta_y"]) for r in rows)
    if dmax > 1.4:
        checkpoints.append(f"delta = {dmax:.2f} > 1.4 (ACI 318-19 6.2.5.3): engineer review - fix by stiffness (larger section) or shorter kLu, not more steel.")
    if lay.max_unsupported_clear() > 15.0 + 1e-6:
        checkpoints.append(f"Unsupported bar clear distance {lay.max_unsupported_clear() * 10:.0f} mm > 150 mm (ACI 25.7.2.3).")

    # ---- ties and shear
    ties = design_ties(lay, inp, combos, sec, notes)
    if not ties["ok"]:
        if M["tie_db"] < 16:
            inp2 = copy.deepcopy(inp)
            inp2["material"]["tie_db"] = 16
            inp2["_tie_upgraded"] = True
            res = run_design(inp2)
            res["checkpoints"].insert(0, "Shear: DB12 ties insufficient after s 150 -> crossties -> s 100; ties upgraded to DB16.")
            return res
        status = "REVISE"
        checkpoints.append("Shear fails with DB16 ties at 100 mm - revise section.")
    if not ties["section_ok"]:
        status = "REVISE"
        checkpoints.append("Vs required > 2.1 sqrt(f'c) bw d - section too small for shear.")

    # ---- f'c / slab
    if M.get("fc_slab") and M["fc"] > 1.4 * M["fc_slab"]:
        notes.append((CODE, f"Column f'c {M['fc']:.0f} > 1.4 x slab f'c {M['fc_slab']:.0f} ksc: ACI 318-19 15.5 - "
                            "provide column concrete through the slab/joint (puddling) or check per 15.5.3."))

    # ---- lap
    sizes = sorted({g.db for g in lay.groups})
    lap = {}
    for d in sizes:
        v = inp["lap"].get(d)
        lap[d] = v if v else None
        if not v:
            checkpoints.append(f"Lap length for DB{d} at f'c {M['fc']:.0f} ksc not given - fill from project table S-00-04-04 (never invented).")
    maxb = max(g.n for g in lay.groups)
    if maxb >= 3:
        notes.append((PRACT, f"{maxb}-bar bundles: laps only where bundles <= 2 bars (12 m stock). If a lap inside a "
                              f"3/4-bar bundle cannot be avoided: x1.2 / x1.33 (ACI 25.6.1.5) or coupler."))
    if lay.rho > 0.04:
        notes.append((PRACT, f"rho = {lay.rho * 100:.2f} % > 4 %: couplers recommended (lap congestion)."))
    if inp.get("_tie_upgraded"):
        notes.append((EJ, "Ties upgraded to DB16 for shear (fyt for shear <= 4200 ksc)."))

    if status == "OK" and maxdc > 1.0:
        status = "REVISE"
    if status == "OK" and checkpoints:
        status = "OK - see checkpoints"
    return {"status": status, "layout": lay, "section": sec, "rows": rows, "slender": sl, "ladder": ladder,
            "ties": ties, "lap": lap, "notes": notes, "checkpoints": checkpoints, "combos": combos,
            "maxDC": maxdc, "delta_max": dmax, "inp": inp}
