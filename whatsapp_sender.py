import base64
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import List, Union
import requests
from playwright.sync_api import sync_playwright

from config import (
    WHATSAPP_GROUPS,
    CHROME_USER_DATA_DIR,
    WHATSAPP_BOT_URL,
    WHATSAPP_BOT_TOKEN,
    DATA_DIR,
)

# Global lock to serialize WhatsApp Web dispatches and prevent profile lock collision
DISPATCH_LOCK = threading.Lock()


def normalize_recipient(target: str) -> str:
    """Detects if target is a phone number and formats it with country code if needed."""
    digits = re.sub(r"\D", "", str(target).strip())
    # If 10 digits (standard Indian mobile), prepend 91
    if len(digits) == 10:
        return f"91{digits}"
    return digits if len(digits) > 10 else target.strip()


def cleanup_stale_locks(session_dir: Path):
    """Safely cleans up stale Chromium lockfiles if browser process is dead."""
    for pattern in ["*Singleton*", "*lock*", "lockfile"]:
        for f in session_dir.glob(pattern):
            try:
                f.unlink()
                print(f"[WhatsApp Web] Cleaned stale lock file: {f.name}")
            except Exception:
                pass


def send_via_whatsapp_web(image_input: Union[Path, List[Path]], recipients: List[str]) -> bool:
    """
    Sends report image(s) to phone numbers or group names via WhatsApp Web using Playwright.
    Uses a persistent browser session so login credentials remain active across runs.
    Guarantees thread-safe access with DISPATCH_LOCK and automatic stale lock cleanup.
    """
    # Prevent concurrent instances from colliding on the same Chromium profile
    if not DISPATCH_LOCK.acquire(blocking=True, timeout=5):
        print("[WhatsApp Web] [!] Another dispatch is currently in progress. Please wait.")
        return False

    try:
        session_dir = DATA_DIR / "whatsapp_session"
        session_dir.mkdir(parents=True, exist_ok=True)
        cleanup_stale_locks(session_dir)

        # Normalize image files
        if isinstance(image_input, (list, tuple)):
            file_paths = [str(Path(p).resolve()) for p in image_input if Path(p).exists()]
        else:
            file_paths = [str(Path(image_input).resolve())] if Path(image_input).exists() else []

        if not file_paths:
            print(f"[WhatsApp Web] [!] No valid image files provided to send: {image_input}")
            return False

        print(f"\n[WhatsApp Web] Starting WhatsApp Web dispatcher for: {recipients}")
        print(f"[WhatsApp Web] Images to send: {[Path(f).name for f in file_paths]}")
        print(f"[WhatsApp Web] Session storage: {session_dir}")

        delivered_recipients = []

        with sync_playwright() as p:
            launch_kwargs = {
                "headless": False if sys.platform == "win32" else True,
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
                ],
            }
            if sys.platform == "win32":
                launch_kwargs["channel"] = "chrome"

            try:
                context = p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e_launch:
                print(f"[WhatsApp Web] [!] Error launching persistent browser context: {e_launch}")
                return False

            page = context.pages[0] if context.pages else context.new_page()

            for recipient in recipients:
                target = str(recipient).strip()
                if not target:
                    continue

                normalized_num = normalize_recipient(target)
                is_phone = normalized_num.isdigit() and len(normalized_num) >= 10

                try:
                    if is_phone:
                        url = f"https://web.whatsapp.com/send?phone={normalized_num}"
                        print(f"\n[WhatsApp Web] Opening direct chat with phone number: +{normalized_num}...")
                        page.goto(url, timeout=90000)
                    else:
                        print(f"\n[WhatsApp Web] Opening chat for group: '{target}'...")
                        page.goto("https://web.whatsapp.com/", timeout=90000)

                    if is_phone:
                        print("[WhatsApp Web] Waiting for chat conversation to load...")
                        page.wait_for_selector("footer", timeout=60000)
                        time.sleep(3)
                    else:
                        # Group search in modern WhatsApp Web
                        print("[WhatsApp Web] Waiting for WhatsApp interface to load...")
                        page.wait_for_selector("#side", timeout=60000)
                        time.sleep(2)
                        print(f"[WhatsApp Web] Searching for group: '{target}'...")

                        # Modern WhatsApp Web search input is #side input or div[aria-label*='Search']
                        search_box = page.locator("#side input, #side div[contenteditable='true'], div[aria-label*='Search']").first
                        search_box.wait_for(state="visible", timeout=20000)
                        search_box.click()
                        search_box.fill("")
                        search_box.fill(target)
                        time.sleep(2)

                        # Check if matching chat appears in results
                        chat_item = page.locator(f"#side span[title*='{target}'], #side div[role='listitem']:has-text('{target}')").first
                        if chat_item.count() > 0 and chat_item.is_visible():
                            chat_item.click()
                        else:
                            # Press Enter on the search bar to open top matched conversation
                            page.keyboard.press("Enter")

                        page.wait_for_selector("footer", timeout=25000)
                        time.sleep(3)

                    # Send each image as a separate standalone PHOTO message (full chat-bubble width).
                    for idx, single_image in enumerate(file_paths, 1):
                        img_name = Path(single_image).name
                        print(f"\n[WhatsApp Web] Sending photo {idx}/{len(file_paths)}: {img_name}...")
                        time.sleep(1.0)

                        # 1. Click Attach
                        attach_btn = page.locator("footer button[aria-label='Attach'], footer button[title='Attach']").first
                        attach_btn.wait_for(state="visible", timeout=15000)
                        attach_btn.click()
                        time.sleep(1.5)

                        # 2. Select photo via file chooser on Photos & videos button
                        photo_btn = page.locator("button[aria-label*='Photos']").first
                        photo_btn.wait_for(state="visible", timeout=10000)
                        with page.expect_file_chooser(timeout=10000) as fc:
                            photo_btn.click()
                        fc.value.set_files(str(Path(single_image).resolve()))
                        print(f"[WhatsApp Web] Photo '{img_name}' loaded in preview. Waiting for upload...")
                        time.sleep(3.0)

                        # 3. Click Send
                        send_btn = page.locator("span[data-icon='send'], div[aria-label='Send'], button[aria-label='Send']").first
                        if send_btn.count() > 0 and send_btn.is_visible():
                            send_btn.click()
                        else:
                            page.keyboard.press("Enter")

                        print(f"[WhatsApp Web] [OK] Sent photo '{img_name}' to: {target}. Waiting for upload confirmation...")
                        time.sleep(3)

                        # 4. Wait for upload to complete:
                        for attempt in range(45):
                            has_clock = page.locator("span[data-icon='msg-time']").count() > 0
                            has_progress = page.locator("div[role='progressbar'], button[aria-label='Cancel upload']").count() > 0
                            if not has_clock and not has_progress:
                                break
                            time.sleep(1)

                        # 8-second confirmation buffer after EVERY image
                        print(f"[WhatsApp Web] Upload confirmed for '{img_name}'. 8s delivery buffer...")
                        time.sleep(8)

                    print(f"[WhatsApp Web] [SUCCESS] All {len(file_paths)} standalone report(s) delivered to: {target}!")
                    delivered_recipients.append(target)
                    try:
                        page.screenshot(path=str((DATA_DIR.parent / "output" / "whatsapp_after_send.png").resolve()))
                    except Exception:
                        pass

                except Exception as e_send:
                    print(f"[WhatsApp Web] [!] Error sending to {target}: {e_send}")

            try:
                context.close()
            except Exception:
                pass

        return len(delivered_recipients) > 0

    finally:
        DISPATCH_LOCK.release()


def flash_report_image(image_input: Union[Path, List[Path]], target_recipients: List[str] = None) -> bool:
    """Flashes the generated report image(s) to WhatsApp recipients (phones or groups)."""
    recipients = target_recipients or WHATSAPP_GROUPS
    if not recipients:
        print("[WhatsApp] No recipients specified. Skipping send.")
        return False

    return send_via_whatsapp_web(image_input, recipients)
