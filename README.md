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
1. **Upload** ETABS exports (skill Step 2) – each model may be several workbooks, all `TABLE:` blocks are merged:
   - 1.1 Seismic model (above ground): Element Forces – Columns, Load Combination Definitions, Column/Point Object Connectivity,
     Frame Assignments – Section Properties, Concrete Rectangular/Circle, Story Forces, Story Drifts
   - 1.2 Full model, reduced stiffness: gravity combos + DL/SDL/LL load cases (basement ΔP, βd), connectivity, sections
   - 1.3 Full model, unreduced stiffness (optional): gravity combos
   - one model only is accepted (no basement assembly); a combo sheet pasted without its header is read too.
   The app lists which tables were found and asks only for what is missing (sections, Lu, combo factors).
2. **Design criteria** (skill Step 1) – prefilled, must be confirmed before Run.
3. **Run** → engine `run.py` + `make_outputs.py --per-mark`.
4. **Results**: label → mark, Table of Column (mark × story range), checkpoints (combo ข้อ 7, sway, ASK_RHO, REVISE, envelopes),
   interaction surface by mark + story range (3D φ-surface, P–Mx, P–My, Mx–My), DXF preview + download,
   downloads (Decision Excel, calc PDF, back-up Excel – all marks and per mark, DXF/PDF draft, schedule for Revit, ZIP),
   detailed CEDA-style Excel per mark-range on request.

## Tests (`tests/test_app.py`)
- A engine self-test (skill) ALL PASS
- B parity: app pipeline == engine run directly on the same ETABS files (synthetic 3-model set incl. basement)
- C one model + headerless combo sheet (VOCO test format): story order, combo check flags wrong factors, all outputs,
  per-mark files, DXF render, surface D/C = engine D/C

## Not covered (same as the skill)
Sway frames (δs), SMF detailing, joint shear, L-shaped columns, spiral φ. Outputs are drafts for engineer review.
