import sys, time
from playwright.sync_api import sync_playwright
D = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1600, 'height': 1300})
    pg.goto('http://localhost:8599'); pg.wait_for_selector('text=1. Upload', timeout=60000)
    pg.locator('input[type=file]').nth(0).set_input_files('/mnt/user-data/uploads/Column/Test/Column Load.xlsx'); time.sleep(6)
    pg.wait_for_selector('text=3. Input check', timeout=120000); time.sleep(2)
    pg.screenshot(path=f'{D}/v_check_before.png', full_page=True)
    print('missing before:', pg.locator('text=fill in the tab above').count())
    pg.locator('input[type=file]').nth(3).set_input_files(f'{D}/CEDA_Column_Input_VOCO_test.xlsx'); time.sleep(8)
    pg.wait_for_selector('text=3. Input check', timeout=120000); time.sleep(3)
    pg.screenshot(path=f'{D}/v_check_after.png', full_page=True)
    print('missing after:', pg.locator('text=✖ fill in the tab above').count())
    pg.get_by_text('I confirm the inputs').click(); time.sleep(2)
    pg.get_by_role('button', name='▶ Run design').click()
    pg.wait_for_selector('text=4. Results', timeout=900000); time.sleep(3)
    for t in ['Label → Mark', 'Table of Column', 'Interaction surface', 'DXF', 'Downloads', 'Decision (label × story)']:
        pg.get_by_role('tab', name=t).click(); time.sleep(12 if t in ('Interaction surface', 'DXF') else 2)
        pg.screenshot(path=f'{D}/v_{t.split()[0]}.png', full_page=True)
    print('exceptions:', pg.locator('[data-testid="stException"]').count())
    b.close()
