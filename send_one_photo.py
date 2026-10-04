import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import DATA_DIR, ADL_REPORT_IMAGE_PATH

phone_number = "919633889430"
img_path = Path(ADL_REPORT_IMAGE_PATH).resolve()

print(f"Testing real Photo send to: +{phone_number}")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(DATA_DIR / "whatsapp_session"),
        headless=False,
        channel="chrome"
    )
    page = ctx.new_page()
    page.goto(f"https://web.whatsapp.com/send?phone={phone_number}")
    page.wait_for_selector("footer", timeout=60000)
    time.sleep(3)

    # 1. Click Attach
    attach_btn = page.locator("footer button[aria-label='Attach']").first
    attach_btn.wait_for(state="visible", timeout=15000)
    attach_btn.click()
    time.sleep(1.5)

    # 2. Click Photos & videos with file chooser
    photo_btn = page.locator("button[aria-label*='Photos']").first
    photo_btn.wait_for(state="visible", timeout=10000)
    with page.expect_file_chooser(timeout=10000) as fc:
        photo_btn.click()
    fc.value.set_files(str(img_path))
    print("Photo selected in file chooser. Waiting for preview...")
    time.sleep(3)

    # 3. Click Send
    send_btn = page.locator("span[data-icon='send'], div[aria-label='Send'], button[aria-label='Send']").first
    if send_btn.count() > 0 and send_btn.is_visible():
        print("Clicking Send button...")
        send_btn.click()
    else:
        print("Pressing Enter to send...")
        page.keyboard.press("Enter")

    # 4. Wait for upload to finish
    print("Waiting for message to deliver...")
    for _ in range(30):
        time.sleep(1)
        if page.locator("span[data-icon='msg-time']").count() == 0:
            break

    time.sleep(4)
    # Take screenshot of chat
    page.screenshot(path="output/send_one_photo_result.png")
    print("Screenshot saved to output/send_one_photo_result.png")
    time.sleep(2)
    ctx.close()
