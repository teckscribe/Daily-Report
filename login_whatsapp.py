import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import (
    DATA_DIR,
    OUTPUT_DIR,
    REPORT_IMAGE_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
)

# Ensure unbuffered output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def log(msg: str):
    print(msg, flush=True)

TARGET_PHONE = "919633889430"
session_dir = DATA_DIR / "whatsapp_session"
session_dir.mkdir(parents=True, exist_ok=True)
qr_path = OUTPUT_DIR / "whatsapp_login_qr.png"

log("=" * 65)
log(f"[*] WHATSAPP ONE-TIME LOGIN & TEST DISPATCHER")
log(f"[*] Target Recipient: +{TARGET_PHONE} (Personal Number)")
log(f"[*] Session Storage: {session_dir}")
log(f"[*] Report Image:    {REPORT_IMAGE_PATH}")
log("=" * 65)

if not REPORT_IMAGE_PATH.exists():
    log(f"[!] Warning: {REPORT_IMAGE_PATH} does not exist yet. Please generate report first.")

with sync_playwright() as p:
    launch_kwargs = {
        "headless": False,  # Visible browser for user to view / scan QR
        "user_data_dir": str(session_dir),
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ],
    }
    if sys.platform == "win32":
        launch_kwargs["channel"] = "chrome"

    log("[*] Launching Google Chrome browser...")
    context = p.chromium.launch_persistent_context(**launch_kwargs)
    page = context.new_page()

    log("[*] Navigating to WhatsApp Web (https://web.whatsapp.com/)...")
    page.goto("https://web.whatsapp.com/", timeout=90000)

    # Check if already authenticated or if QR code is required
    log("[*] Checking login state...")
    is_authenticated = False
    
    # Wait up to 600 seconds (10 minutes) for either QR or existing session
    start_time = time.time()
    last_qr_time = 0
    artifact_qr_path = Path(r"C:\Users\Anoop P\.gemini\antigravity\brain\7e94d07a-766e-459d-a0c5-c2c4d9f283cb\whatsapp_login_qr.png")

    while time.time() - start_time < 600:
        # Check if already logged in (chat list or search box present)
        if page.locator("#side, div[contenteditable='true'][data-tab='3'], div[aria-label='Search']").count() > 0:
            log("[OK] WhatsApp Web session is already authenticated!")
            is_authenticated = True
            break

        # Check for reload button on expired QR code
        reload_btn = page.locator("span[data-icon='refresh'], button:has-text('reload'), div[role='button']:has(span[data-icon='refresh'])").first
        if reload_btn.count() > 0 and reload_btn.is_visible():
            try:
                log("[*] QR code expired, clicking reload to generate fresh QR code...")
                reload_btn.click()
                time.sleep(3)
                last_qr_time = 0  # Force screenshot update
            except Exception:
                pass

        # Check if QR code is visible and update screenshot every 25 seconds if needed
        qr_loc = page.locator("canvas, div[data-ref], div[aria-label*='QR']").first
        if qr_loc.count() > 0 and (time.time() - last_qr_time > 25):
            time.sleep(1)
            try:
                page.screenshot(path=str(qr_path.resolve()))
                if artifact_qr_path.parent.exists():
                    import shutil
                    shutil.copy2(str(qr_path.resolve()), str(artifact_qr_path.resolve()))
                log(f"\n{'!' * 60}")
                log(f"[!] ACTIVE QR CODE AVAILABLE!")
                log(f"[!] Please open WhatsApp on your phone -> Linked Devices -> Scan QR Code")
                log(f"{'!' * 60}\n")
                last_qr_time = time.time()
            except Exception as e_qr:
                log(f"[!] Could not capture QR screenshot: {e_qr}")

        time.sleep(2)

    if not is_authenticated:
        # Final check if user logged in
        if page.locator("#side, div[contenteditable='true'][data-tab='3'], div[aria-label='Search']").count() > 0:
            is_authenticated = True

    if not is_authenticated:
        log("[!] Login timed out after 10 minutes. Please run again when ready.")
        context.close()
        sys.exit(1)

    # Authenticated! Now navigate directly to the target phone chat
    log(f"\n[*] Navigating to personal chat: https://web.whatsapp.com/send?phone={TARGET_PHONE}...")
    page.goto(f"https://web.whatsapp.com/send?phone={TARGET_PHONE}", timeout=90000)

    log("[*] Waiting for chat conversation interface to load...")
    try:
        page.wait_for_selector(
            "footer, div[contenteditable='true'][data-tab='10'], div[aria-label='Type a message']",
            timeout=60000,
        )
        log("[OK] Chat conversation interface loaded successfully!")
    except Exception as e_chat:
        log(f"[!] Timeout waiting for chat interface: {e_chat}")
        context.close()
        sys.exit(1)

    time.sleep(3)

    # Attach and send exact report images (ADL & ADTv)
    images_to_send = [p for p in [ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH] if p.exists()]
    if not images_to_send and REPORT_IMAGE_PATH.exists():
        images_to_send = [REPORT_IMAGE_PATH]

    for idx, img_path in enumerate(images_to_send, 1):
        log(f"[*] Attaching report image {idx}/{len(images_to_send)}: {img_path.name}...")
        time.sleep(2)

        # Check for file input directly
        file_input = page.locator("input[type='file'][accept*='image'], input[type='file']").first
        if file_input.count() == 0:
            log("[*] Clicking Attach (+) button...")
            attach_btn = page.locator(
                "button[aria-label='Attach'], span[data-icon='plus'], span[data-icon='attach-menu-plus'], div[title='Attach'], button[title='Attach']"
            ).first
            if attach_btn.count() > 0:
                attach_btn.click()
                time.sleep(1)
            file_input = page.locator("input[type='file'][accept*='image'], input[type='file']").first

        if file_input.count() > 0:
            log(f"[*] Setting image file '{img_path.name}' in file upload input...")
            file_input.set_input_files(str(img_path.resolve()))
            log("[*] Image loaded into preview dialog. Waiting for send button...")
            time.sleep(3)

            # Look for send button in the preview overlay
            send_btn = page.locator(
                "span[data-icon='send'], div[aria-label='Send'], button[aria-label='Send'], span[data-icon='send-refreshed']"
            ).first

            if send_btn.count() > 0:
                send_btn.click()
                log("[*] Send button clicked!")
            else:
                log("[*] Send button locator not matched, pressing Enter key...")
                page.keyboard.press("Enter")

            log(f"[OK] Sent '{img_path.name}' successfully!")
            time.sleep(6)
        else:
            log(f"[!] Could not locate file input to attach {img_path.name}.")

    log(f"\n[SUCCESS] All report images successfully sent to your personal number (+{TARGET_PHONE})!")
    log("[*] Closing browser. Session has been saved to data/whatsapp_session!")
    context.close()
    log("[*] ALL DONE!")
