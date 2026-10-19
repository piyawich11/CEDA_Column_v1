"""UI: Excel workbook + edits on screen (criteria text, data-editor cell) -> run uses the screen values."""
import sys, time, glob, os, json
from playwright.sync_api import sync_playwright
D = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1600, 'height': 1300})
    pg.goto('http://localhost:8599'); pg.wait_for_selector('text=1. Upload', timeout=60000)
    pg.locator('input[type=file]').nth(0).set_input_files('/mnt/user-data/uploads/Column/Test/Column Load.xlsx'); time.sleep(6)
    pg.locator('input[type=file]').nth(3).set_input_files(f'{D}/CEDA_Column_Input_VOCO_test.xlsx'); time.sleep(8)
    pg.wait_for_selector('text=2. Inputs', timeout=120000); time.sleep(2)
    # criteria edit: job no.
    job = pg.get_by_label('Job no. (file prefix)')
    job.fill('SCREEN'); job.press('Enter'); time.sleep(3)
    # data-editor edit: Stories, first row Lu_m = 3.0
    pg.get_by_role('tab', name='Stories / Lu / k').click(); time.sleep(2)
    grid = pg.locator('[data-testid="stDataFrame"]').filter(has=pg.locator('canvas')).first
    box = pg.locator('[data-testid="stDataFrameResizable"]').first.bounding_box()
    # columns: story, z_bottom_m, z_top_m, basement, Lu_m, k, fc_ksc  -> click Lu_m of row 1
    hdr = pg.get_by_text('Lu_m', exact=True).first.bounding_box() if pg.get_by_text('Lu_m', exact=True).count() else None
    x = (hdr['x'] + hdr['width'] / 2) if hdr else box['x'] + box['width'] * 0.62
    y = box['y'] + 35 + 17
    pg.mouse.dblclick(x, y); time.sleep(1); pg.keyboard.type('3'); pg.keyboard.press('Enter'); time.sleep(3)
    pg.screenshot(path=f'{D}/w_stories_edit.png', full_page=False)
    pg.get_by_text('I confirm the inputs').click(); time.sleep(2)
    pg.get_by_role('button', name='▶ Run design').click()
    pg.wait_for_selector('text=4. Results', timeout=900000); time.sleep(3)
    print('exceptions:', pg.locator('[data-testid="stException"]').count())
    b.close()
outs = sorted(glob.glob('/tmp/ceda_col_*/OUT/results.json'), key=os.path.getmtime)
r = json.load(open(outs[-1]))
print('job:', r['config']['project']['job'])
lu1 = {q['Lu'] for x in r['results'] for q in x['per'] if q['story'] == '1st'}
lu2 = {q['Lu'] for x in r['results'] for q in x['per'] if q['story'] == '2nd'}
print('Lu 1st:', lu1, ' Lu 2nd:', lu2)
