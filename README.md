# CEDA RC Column Design – Streamlit

Web app for one column mark / one band, following the `ceda-column-design` skill (v1) rules.

## Run
```bash
pip install -r requirements.txt
python3 tests/selftest.py        # must print ALL PASS
streamlit run app.py
```

## Inputs (sidebar = skill Step 1)
1.1 Project header/footer · 1.2 Seismic (category ก–ง, R/Ω0/Cd, Gravity/IMF/SMF, Q) · 1.3 Materials (f'c, typical f'c,
fy, fyt, cover, tie, slab f'c) · 1.4 Section b = t2, h = t3, Lu, k, size restriction / ρ > 6 % approval, bar counts ·
1.5 βd (from DL/SDL/LL or direct) · 1.6 Lap table S-00-04-04 · 1.7 Auto ladder or a manual step.
Load combinations: table (P + compression, Mx = M3, My = M2, Vx = V3, Vy = V2, factors fD/fL/fE/fW for the ข้อ 7 check)
or import from an ETABS Excel export (Element Forces – Columns + Load Combination Definitions). Run is disabled until the
designer ticks the criteria confirmation.

## Outputs
3D capped φ-surface with demand points and the governing ray · P-Mx, P-My, Mx-My · calc report on screen ·
Table of Column preview rendered from the exported DXF · downloads: PDF calc, Excel back-up (incl. bar coordinates for Revit),
DXF (mm, CEDA layers).

## Engine (engine/)
| file | content |
|---|---|
| section.py | strain compatibility, exact ACI block (rectangle clipped by the block line), φ by εt, 0.80φPo cap, convex hull, radial D/C |
| layout.py | c/c 125–150 mm grid, CEDA symmetric tie pattern, hoops/crossties, build-up ladder, clear-spacing check |
| design.py | combo check (ข้อ 7), sway stop, slenderness (non-sway), ladder search, ρ rules, ties (IMF minimum), shear escalation, lap |
| drawing.py / report.py / plots.py | DXF + preview, PDF/Excel, figures |
| etabs.py | `TABLE:` block reader, unit conversion, combo factor mapping |

## Not covered (same as skill v1, plus app limits)
Sway frames (δs) · SMF detailing (ACI 18.7) · joint Av · deformation compatibility (category ง) · circular columns ·
spiral φ · multi-story/multi-column runs: basement load assembly, f'c reduction study, band merging, marks ·
bundles at non-tie-corner positions (ladder phase 2) · detailed X/Y Excel per mark.

## Assumptions to confirm
- Group width along the face: single db, bundle 2–4 bars 2db; clear ≥ max(1.5 db·√n, 40 mm, 4/3 d_agg).
- Bundle centroid shifted inward 0.29 db (3 bars) / 0.50 db (4 bars).
- so rounded down to 25 mm, lo rounded up to 50 mm.
- M2,min applied only when kLu/r > 22 (ACI 6.6.4.5.4).
- ETABS import: per combo, Pu at max compression and max |M|, |V| over stations (conservative).
- Wind combos 0.75(1.4D+1.7L)+1.6W and 0.9D+1.6W – verify against ข้อ 7.
- CED_0_10/13/18_Solid layer assignment in the DXF.
