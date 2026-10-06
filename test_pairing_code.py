import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import DATA_DIR, OUTPUT_DIR, REPORT_IMAGE_PATH

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def log(msg: str):
    print(msg, flush=True)
import os
OFFICE_PHONE = os.getenv("OFFICE_PHONE", "919999999998")
PERSONAL_PHONE = os.getenv("PERSONAL_PHONE", "919999999999")
session_dir = DATA_DIR / "whatsapp_session"
session_dir.mkdir(parents=True, exist_ok=True)
code_screenshot = OUTPUT_DIR / "whatsapp_pairing_code.png"

with sync_playwright() as p:
    launch_kwargs = {
        "headless": False,
        "user_data_dir": str(session_dir),
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if sys.platform == "win32":
        launch_kwargs["channel"] = "chrome"

    log("[*] Launching Chrome...")
    context = p.chromium.launch_persistent_context(**launch_kwargs)
    page = context.new_page()

    log("[*] Navigating to WhatsApp Web...")
    page.goto("https://web.whatsapp.com/", timeout=90000)

    # Wait for the loading screen to finish and login options to appear
    log("[*] Waiting for WhatsApp landing page to load...")
    page.wait_for_selector("canvas, div[data-ref], span:has-text('Log in with phone number'), div:has-text('Scan to log in')", timeout=60000)
    time.sleep(2)

    # Check if already authenticated
    if page.locator("#side, div[contenteditable='true'][data-tab='3']").count() > 0:
        log("[OK] Already authenticated!")
    else:
        log("[*] Looking for 'Log in with phone number'...")
        # Look for the link
        login_btn = page.locator("span[role='button']:has-text('Log in with phone number'), span:has-text('Log in with phone number'), div[role='button']:has-text('Log in with phone number')").first
        
        if login_btn.count() == 0:
            log("[!] Could not find direct button, searching text...")
            login_btn = page.get_by_text("Log in with phone number", exact=False).first

        if login_btn.count() > 0:
            log("[*] Clicking 'Log in with phone number'...")
            login_btn.click()
            time.sleep(3)

            # Look for phone input
            log("[*] Entering office phone number: " + OFFICE_PHONE)
            phone_input = page.locator("input[aria-label*='phone'], input[data-tab='6'], input[type='text']").last
            if phone_input.count() > 0:
                phone_input.click()
                phone_input.fill("")
                phone_input.fill(OFFICE_PHONE)
                time.sleep(1)

                # Click Next
                next_btn = page.locator("button:has-text('Next'), div[role='button']:has-text('Next')").first
                if next_btn.count() > 0:
                    next_btn.click()
                    log("[*] Clicked Next! Waiting for pairing code...")
                    time.sleep(5)

                    # Extract pairing code
                    page.screenshot(path=str(code_screenshot.resolve()))
                    log(f"[OK] Screenshot saved to: {code_screenshot}")

                    # Modern WhatsApp shows 8 digits in individual span/div blocks
                    code_elements = page.locator("div[aria-details*='code'] span, div[data-testid='link-device-phone-number-code'] span, span[aria-label]").all_inner_texts()
                    log(f"[*] Found code elements: {code_elements}")

        else:
            log("[!] 'Log in with phone number' link not found on landing page.")
            page.screenshot(path=str(code_screenshot.resolve()))

    context.close()
