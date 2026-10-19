# CEDA RC Column Design – Streamlit (v2)

Front end for the **ceda-column-design** skill. `engine/` is a verbatim copy of the skill scripts
(version in `engine/ENGINE_VERSION`); the app does **not** re-implement any design rule.
When the skill is updated, copy the skill `scripts/` folder over `engine/` and run the tests.

## Run
```bash
pip install -r requirements.txt
python3 tests/test_app.py "<folder with Column Load.xlsx + load combination.xlsx>"   # must print ALL PASS
streamlit run app.py
```

## Flow
1. **Upload**
   - ETABS exports per model (1.1 seismic, 1.2 full reduced, 1.3 full unreduced – optional); several workbooks per model are merged.
   - **CEDA input workbook** (1.4) – every input can come from Excel (`templates/CEDA_Column_Input_TEMPLATE.xlsx`, or the
     prefilled one the app offers after the ETABS upload):

     | sheet | content |
     |---|---|
     | Criteria | project header, seismic (category, R, Ω0, Cd, gravity/IMF/SMF), f'c typical / slab / fixed or auto, fy, fyt, cover, tie, size restricted, k, βd, gravity case names, mark envelope, story-range mode |
     | Stories | order bottom → top, z bottom / top (m) → Lu, basement Y/N, Lu / k override, fixed f'c |
     | Columns | connectivity per column-story: XY (label matching between models), Lu / k override |
     | Sections | column size per label (and story range): rect / circ, b = t2, h = t3 (mm) |
     | Combos | combination factors per ETABS load case (header = case names) |
     | Lap | Class B lap per f'c and bar size (mm) |
     | Exclude / Approve_rho | combos not used / label-stories with approved ρ 6–8 % |

     Template data become ETABS-style tables for the engine. Where the ETABS export already has the data the workbook wins
     per item (sizes per label, connectivity per column-story, factors per combo) and the app says so.
2. **Inputs on screen** – the same items as the workbook in tabs (Project, Seismic, Materials & detailing, Stories / Lu / k, Columns,
   Sections, Load combinations, Lap table, Marks & ranges, Exclude / ρ approval), prefilled from ETABS + workbook and editable;
   "Save the inputs on screen as an input workbook" writes them back to Excel. A new upload resets the screen to the files.
3. **Input check** – every input, its source and ✔ / ✖ (missing → fill the tab or the workbook).
4. **Confirm → Run** (engine `run.py` + `make_outputs.py --per-mark`).
5. **Results**: label → mark, Table of Column, checkpoints, interaction surface by mark + story range, DXF view + download,
   downloads (Decision, calc PDF and back-up Excel – all and per mark, DXF/PDF draft, schedule for Revit, input workbook used, ZIP),
   detailed CEDA-style Excel per mark-range.

## Tests (`tests/test_app.py`)
- A engine self-test (skill) ALL PASS
- B parity: app pipeline == engine run directly on the same ETABS files (synthetic 3-model set incl. basement)
- C forces only (VOCO test) → missing inputs reported → CEDA input workbook filled (Criteria, Stories, Sections, Combos) → run;
  f'c / k / βd / Lu from the workbook, combo check, all outputs, per-mark files, DXF, surface D/C = engine, workbook round trip
- D workbook Sections override one ETABS size, other labels keep ETABS, basement assembly kept

## Not covered (same as the skill)
Sway frames (δs), SMF detailing, joint shear, L-shaped columns, spiral φ. Outputs are drafts for engineer review.
