"""Minimal ETABS Excel reader: finds every 'TABLE:' block in a workbook (one or many sheets)."""
import math

import pandas as pd

FORCE = {"tonf": 1.0, "ton": 1.0, "t": 1.0, "kn": 1 / 9.80665, "kgf": 1e-3, "kg": 1e-3, "n": 1e-3 / 9.80665}
LENGTH = {"m": 1.0, "cm": 0.01, "mm": 1e-3}


def read_tables(file):
    """Return {table name: DataFrame (with .attrs['units'])}."""
    out = {}
    xl = pd.ExcelFile(file)
    for sh in xl.sheet_names:
        raw = xl.parse(sh, header=None, dtype=object)
        starts = [i for i, v in raw.iloc[:, 0].items() if isinstance(v, str) and v.strip().upper().startswith("TABLE:")]
        if not starts and isinstance(sh, str):
            # ETABS "one table per sheet" export without TABLE: row -> header row 0, units row 1
            starts = [-1]
        for k, i0 in enumerate(starts):
            name = raw.iloc[i0, 0].split(":", 1)[1].strip() if i0 >= 0 else sh
            end = starts[k + 1] if k + 1 < len(starts) else len(raw)
            hdr = raw.iloc[i0 + 1].tolist()
            units = raw.iloc[i0 + 2].tolist()
            data = raw.iloc[i0 + 3:end].dropna(how="all")
            cols = [str(h).strip() for h in hdr]
            df = pd.DataFrame(data.values, columns=cols)
            df.attrs["units"] = {c: (str(u).strip() if isinstance(u, str) else "") for c, u in zip(cols, units)}
            out[name] = df
    return out


def unit_factor(u, kind):
    """kind 'F' (to t) or 'M' (to t-m)."""
    u = (u or "").lower().replace(" ", "")
    if kind == "F":
        return FORCE.get(u, None)
    if "-" not in u:
        return None
    f, l = u.split("-", 1)
    if f in FORCE and l in LENGTH:
        return FORCE[f] * LENGTH[l]
    return None


def column_forces(df, story, column):
    """Element Forces - Columns -> one demand row per output case (+ step type).
    P converted to + compression. Per case: Pu at max compression, M and V = max |value| over stations
    with sign kept (Engineering judgment - conservative for short columns)."""
    u = df.attrs.get("units", {})
    fF = unit_factor(u.get("P"), "F")
    fM = unit_factor(u.get("M3"), "M")
    if fF is None or fM is None:
        raise ValueError(f"Units not recognised: P '{u.get('P')}', M3 '{u.get('M3')}'")
    d = df[(df["Story"].astype(str) == str(story)) & (df["Column"].astype(str) == str(column))].copy()
    for c in ("P", "V2", "V3", "M2", "M3"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    key = ["Output Case"] + (["Step Type"] if "Step Type" in d.columns else [])
    rows = []
    for k, g in d.groupby(key, dropna=False, sort=False):
        k = k if isinstance(k, tuple) else (k,)
        name = " ".join(str(x) for x in k if isinstance(x, str) and x and x.lower() != "nan")

        def absmax(s):
            s = s.dropna()
            return 0.0 if s.empty else float(s.loc[s.abs().idxmax()])
        rows.append({"name": name, "Pu": float(-g["P"].min()) * fF,
                     "Mx": absmax(g["M3"]) * fM, "My": absmax(g["M2"]) * fM,
                     "Vx": absmax(g["V3"]) * fF, "Vy": absmax(g["V2"]) * fF})
    return rows


def combo_factors(df, d_loads, l_loads, e_loads, w_loads):
    """Load Combination Definitions -> {combo: (fD, fL, fE, fW)}; None where unclear (e.g. DL and SDL factors differ)."""
    name_col = "Name" if "Name" in df.columns else df.columns[0]
    load_col = next((c for c in df.columns if c.lower() in ("load name", "case name", "load case")), None)
    sf_col = next((c for c in df.columns if c.upper() == "SF" or "scale" in c.lower()), None)
    if load_col is None or sf_col is None:
        return {}
    d = df.copy()
    d[name_col] = d[name_col].ffill()
    out = {}
    for name, g in d.groupby(name_col, sort=False):
        cats = {"D": set(), "L": set(), "E": [], "W": []}
        unknown = False
        for _, r in g.iterrows():
            ln, sf = str(r[load_col]), pd.to_numeric(r[sf_col], errors="coerce")
            if sf is None or (isinstance(sf, float) and math.isnan(sf)):
                continue
            if ln in d_loads:
                cats["D"].add(round(float(sf), 4))
            elif ln in l_loads:
                cats["L"].add(round(float(sf), 4))
            elif ln in e_loads:
                cats["E"].append(float(sf))
            elif ln in w_loads:
                cats["W"].append(float(sf))
            else:
                unknown = True
        fD = None if len(cats["D"]) > 1 or unknown else (next(iter(cats["D"])) if cats["D"] else 0.0)
        fL = None if len(cats["L"]) > 1 or unknown else (next(iter(cats["L"])) if cats["L"] else 0.0)
        fE = max(cats["E"], key=abs) if cats["E"] else 0.0
        fW = max(cats["W"], key=abs) if cats["W"] else 0.0
        out[str(name)] = (fD, fL, None if unknown else fE, None if unknown else fW)
    return out
