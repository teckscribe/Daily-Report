import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import DATA_DIR, ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH

phone_number = "919633889430"
images = [ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH]

print(f"Starting real Photo send test to: +{phone_number}")

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

    for idx, img_path in enumerate(images, 1):
        name = img_path.name
        print(f"\n[{idx}/2] Preparing to send real Photo: {name}")
        page.keyboard.press("Escape")
        time.sleep(1.5)

        # 1. Click Attach
        attach_btn = page.locator("footer button[aria-label='Attach'], footer button[title='Attach']").first
        print(f"[{idx}/2] Clicking Attach...")
        attach_btn.click()
        time.sleep(1.5)

        # 2. Click Photos & videos with file chooser
        photo_btn = page.locator("button[aria-label*='Photos']").first
        print(f"[{idx}/2] Selecting photo via file chooser...")
        with page.expect_file_chooser(timeout=10000) as fc:
            photo_btn.click()
        fc.value.set_files(str(Path(img_path).resolve()))
        print(f"[{idx}/2] Photo loaded into preview dialog.")
        time.sleep(3)

        # 3. Click Send button in the preview
        send_btn = page.locator("span[data-icon='send'], span[data-icon='wds-ic-send-filled'], button[aria-label='Send']").first
        if send_btn.count() > 0 and send_btn.is_visible():
            print(f"[{idx}/2] Clicking preview Send button...")
            send_btn.click()
        else:
            print(f"[{idx}/2] Pressing Enter to send...")
            page.keyboard.press("Enter")

        print(f"[{idx}/2] Photo sent! Waiting for upload to complete...")
        # Wait until the pending clock icon disappears
        for _ in range(30):
            time.sleep(1)
            if page.locator("span[data-icon='msg-time']").count() == 0:
                break
        
        # Buffer between the two photos so WhatsApp NEVER bundles them into an album
        print(f"[{idx}/2] Done. Waiting 8s buffer before next photo...")
        time.sleep(8)

    # Take a screenshot of the chat to verify how it appears
    page.screenshot(path="output/real_photos_after_send.png")
    print("\nSUCCESS! Both real photos dispatched as standalone messages.")
    time.sleep(2)
    ctx.close()
