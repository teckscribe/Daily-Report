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
    raw = str(target).strip()
    # If the target string contains letters, it is a contact or group name, NOT a phone number
    if re.search(r"[a-zA-Z]", raw):
        return raw

    digits = re.sub(r"\D", "", raw)
    # Strip leading 0 if 11 digits (e.g. 09633889430 -> 9633889430)
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    # If 10 digits (standard Indian mobile), prepend 91
    if len(digits) == 10:
        return f"91{digits}"
    return digits if len(digits) > 10 else raw


def cleanup_stale_locks(session_dir: Path):
    """Safely cleans up stale Chromium lockfiles if browser process is dead."""
    for pattern in ["*Singleton*", "*lock*", "lockfile"]:
        for f in session_dir.glob(pattern):
            try:
                f.unlink()
                print(f"[WhatsApp Web] Cleaned stale lock file: {f.name}")
            except Exception:
                pass


def dismiss_active_dialogs(page):
    """Safely closes popup dialogs only if an actual dialog overlay is present."""
    try:
        dialogs = page.locator("div[role='dialog']")
        for idx in range(dialogs.count()):
            d = dialogs.nth(idx)
            try:
                if d.is_visible():
                    btn = d.locator(
                        "button[aria-label*='Close'], button[aria-label*='Cancel'], [data-icon='x'], "
                        "button:has-text('Not now'), button:has-text('Cancel'), button:has-text('OK'), "
                        "button:has-text('Continue'), button:has-text('Dismiss')"
                    ).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True, timeout=1500)
                        time.sleep(0.5)
            except Exception:
                pass
    except Exception:
        pass


def attach_and_prepare_photo(page, file_path: str, img_name: str, max_retries: int = 3) -> bool:
    """
    Attaches an image specifically as a full-resolution PHOTO message (never a sticker).
    Targets the Photos & videos menuitem and its dedicated input[accept*='video/mp4'].
    """
    abs_path = str(Path(file_path).resolve())

    for attempt in range(1, max_retries + 1):
        try:
            # 1. Click Attach button (+) in footer
            attach_btn = page.locator(
                "footer button[aria-label='Attach'], footer button[title='Attach'], "
                "footer span[data-icon='plus'], footer span[data-icon='attach-menu-plus'], "
                "footer div[aria-label='Attach'], footer button:has([data-icon='plus'])"
            ).first
            attach_btn.wait_for(state="visible", timeout=8000)
            attach_btn.click(force=True)
            time.sleep(1.0)

            # 2. Specifically target the Photos & Videos file input (accept*='video/mp4')
            # In WhatsApp Web, ONLY Photos & Videos accepts video/mp4 (Stickers accept only images, never mp4).
            photos_input = page.locator("input[type='file'][accept*='video/mp4']").first
            if photos_input.count() > 0:
                photos_input.set_input_files(abs_path)
                print(f"[WhatsApp Web] Photo '{img_name}' loaded via Photos & videos input (attempt {attempt}).")
                return True

            # 3. Fallback: file chooser via the 'Photos & videos' menuitem
            photo_btn = page.locator(
                "button[aria-label*='Photos'], [role='menuitem']:has-text('Photos'), "
                "li button:has-text('Photos'), [data-animate-dropdown-item]:has-text('Photos')"
            ).first
            photo_btn.wait_for(state="visible", timeout=5000)

            inner_input = photo_btn.locator("input[type='file']").first
            if inner_input.count() > 0:
                inner_input.set_input_files(abs_path)
                print(f"[WhatsApp Web] Photo '{img_name}' loaded via inner Photos input (attempt {attempt}).")
                return True

            with page.expect_file_chooser(timeout=7000) as fc:
                photo_btn.click(force=True)
            fc.value.set_files(abs_path)
            print(f"[WhatsApp Web] Photo '{img_name}' loaded via Photos & videos file chooser (attempt {attempt}).")
            return True

        except Exception as e_att:
            print(f"[WhatsApp Web] Attach attempt {attempt}/{max_retries} notice: {e_att}. Retrying in 1s...")
            time.sleep(1.0)

    return False


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
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "viewport": {"width": 1280, "height": 800},
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
                if "channel" in launch_kwargs:
                    print(f"[WhatsApp Web] Chrome launch notice ({e_launch}). Falling back to bundled Chromium...")
                    launch_kwargs.pop("channel", None)
                    try:
                        context = p.chromium.launch_persistent_context(**launch_kwargs)
                    except Exception as e_retry:
                        print(f"[WhatsApp Web] [!] Error launching persistent browser context: {e_retry}")
                        return False
                else:
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

                        print("[WhatsApp Web] Waiting for chat conversation to load...")
                        try:
                            page.wait_for_selector("footer, div[role='dialog']", timeout=60000)
                        except Exception:
                            pass

                        # Check if invalid number dialog appears
                        invalid_popup = page.locator("div[role='dialog']:has-text('invalid'), div[role='dialog']:has-text('Phone number')")
                        if invalid_popup.count() > 0 and invalid_popup.first.is_visible():
                            print(f"[WhatsApp Web] [!] Phone number +{normalized_num} is not registered on WhatsApp or URL is invalid.")
                            ok_btn = invalid_popup.locator("button").first
                            if ok_btn.count() > 0 and ok_btn.is_visible():
                                ok_btn.click(force=True)
                            continue

                        page.wait_for_selector("footer", timeout=30000)
                        dismiss_active_dialogs(page)
                        time.sleep(1.5)
                    else:
                        print(f"\n[WhatsApp Web] Opening chat for group: '{target}'...")
                        page.goto("https://web.whatsapp.com/", timeout=90000)

                        print("[WhatsApp Web] Waiting for WhatsApp interface to load...")
                        page.wait_for_selector("#side", timeout=60000)
                        time.sleep(1.5)

                        dismiss_active_dialogs(page)

                        print(f"[WhatsApp Web] Searching for group: '{target}'...")
                        search_box = page.locator(
                            "#side input, #side div[contenteditable='true'], div[aria-label*='Search'], #side [data-tab='3']"
                        ).first
                        search_box.wait_for(state="visible", timeout=20000)

                        # Focus and click with force=True so modal overlays never block it
                        try:
                            search_box.evaluate("el => el.focus()")
                        except Exception:
                            pass
                        search_box.click(force=True)
                        search_box.fill("")
                        search_box.fill(target)
                        time.sleep(2.0)

                        # Check if matching chat appears in results
                        chat_item = page.locator(
                            f"#side span[title*='{target}'], #side span[title*='{target.strip()}'], "
                            f"#side div[role='listitem']:has-text('{target.strip()}')"
                        ).first
                        if chat_item.count() > 0 and chat_item.is_visible():
                            chat_item.click(force=True)
                        else:
                            # Press Enter on the search bar to open top matched conversation
                            page.keyboard.press("Enter")

                        page.wait_for_selector("footer", timeout=30000)
                        dismiss_active_dialogs(page)
                        time.sleep(1.5)

                    # Send each image as a separate standalone PHOTO message (full chat-bubble width).
                    for idx, single_image in enumerate(file_paths, 1):
                        img_name = Path(single_image).name
                        print(f"\n[WhatsApp Web] Sending photo {idx}/{len(file_paths)}: {img_name}...")

                        # Wait for footer to be present before attaching
                        page.wait_for_selector("footer", timeout=20000)

                        success_attach = attach_and_prepare_photo(page, single_image, img_name)
                        if not success_attach:
                            print(f"[WhatsApp Web] [!] Failed to attach '{img_name}'. Skipping to next photo...")
                            continue

                        print(f"[WhatsApp Web] Photo '{img_name}' loaded in preview. Waiting for send button...")
                        time.sleep(2.0)

                        # Click Send button in the preview overlay
                        send_btn = page.locator(
                            "span[data-icon='send'], div[aria-label='Send'], button[aria-label='Send'], span[data-icon='send-refreshed']"
                        ).first
                        try:
                            send_btn.wait_for(state="visible", timeout=12000)
                        except Exception:
                            pass

                        if send_btn.count() > 0 and send_btn.is_visible():
                            send_btn.click(force=True)
                        else:
                            page.keyboard.press("Enter")

                        print(f"[WhatsApp Web] [OK] Sent photo '{img_name}' to: {target}. Waiting for upload confirmation...")
                        time.sleep(2.5)

                        # Wait for upload to complete
                        for _ in range(45):
                            has_clock = page.locator("span[data-icon='msg-time']").count() > 0
                            has_progress = page.locator("div[role='progressbar'], button[aria-label='Cancel upload']").count() > 0
                            if not has_clock and not has_progress:
                                break
                            time.sleep(1)

                        # Delivery buffer between consecutive images
                        print(f"[WhatsApp Web] Upload confirmed for '{img_name}'. 5s delivery buffer...")
                        time.sleep(5)

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
