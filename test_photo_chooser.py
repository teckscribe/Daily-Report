from playwright.sync_api import sync_playwright
import time
from pathlib import Path
from config import DATA_DIR, ADL_REPORT_IMAGE_PATH

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(DATA_DIR / "whatsapp_session"),
        headless=False,
        channel="chrome"
    )
    page = ctx.new_page()
    page.goto("https://web.whatsapp.com/send?phone=919633889430")
    page.wait_for_selector("footer", timeout=60000)
    time.sleep(3)
    
    # Click Attach
    page.locator("footer button[aria-label='Attach']").first.click()
    time.sleep(1.5)
    
    # Click Photos & videos
    btn = page.locator("button[aria-label*='Photos']").first
    print("Photos & videos button found:", btn.count())
    
    with page.expect_file_chooser(timeout=10000) as fc:
        btn.click()
    fc.value.set_files(str(Path(ADL_REPORT_IMAGE_PATH).resolve()))
    print("File set via Photos & videos file chooser!")
    time.sleep(3)
    
    page.screenshot(path="output/test_photo_preview.png")
    print("Saved preview screenshot: output/test_photo_preview.png")
    
    # Press Escape twice to cancel preview
    page.keyboard.press("Escape")
    time.sleep(1)
    page.keyboard.press("Escape")
    time.sleep(1)
    ctx.close()
