"""
whatsapp_auth_manager.py
========================
Provides headless browser authentication management for WhatsApp Web:
- Initiates QR code generation in a background Playwright session
- Streams QR screenshots to output directory for real-time Web UI display
- Detects successful mobile pairing and persists session state
- Provides clean session wiping to allow switching accounts/phones
"""

import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from playwright.sync_api import sync_playwright

from config import DATA_DIR, OUTPUT_DIR
from whatsapp_sender import DISPATCH_LOCK, cleanup_stale_locks

STATUS_FILE = DATA_DIR / "whatsapp_status.json"
QR_IMAGE_PATH = OUTPUT_DIR / "whatsapp_qr.png"
SESSION_DIR = DATA_DIR / "whatsapp_session"

CHROME_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

AUTH_LOCK = threading.Lock()
_login_thread: Optional[threading.Thread] = None
_stop_requested = False
_current_state: Dict[str, Any] = {
    "status": "idle",
    "message": "Not initialized",
    "updated_at": "",
    "qr_available": False,
    "last_qr_ts": 0,
}


def get_whatsapp_status() -> Dict[str, Any]:
    """Returns the current WhatsApp Web session and login status."""
    with AUTH_LOCK:
        has_active_login = _login_thread is not None and _login_thread.is_alive()

        # If an active login loop is running, return its live state
        if has_active_login:
            res = dict(_current_state)
            if QR_IMAGE_PATH.exists() and res.get("qr_available"):
                res["qr_url"] = f"/output/whatsapp_qr.png?t={int(res.get('last_qr_ts', time.time()))}"
            return res

        # Otherwise check disk status file and session dir
        has_session_files = False
        if SESSION_DIR.exists():
            idb = SESSION_DIR / "Default" / "IndexedDB"
            has_session_files = idb.exists() and any(idb.iterdir())

        persisted = {}
        if STATUS_FILE.exists():
            try:
                persisted = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        is_auth = persisted.get("authenticated", False) and has_session_files

        return {
            "status": "authenticated" if is_auth else "disconnected",
            "message": "Connected & Paired" if is_auth else "No active WhatsApp session. Click 'Scan QR Code' to link a phone.",
            "updated_at": persisted.get("last_login", ""),
            "has_session_files": has_session_files,
            "qr_available": False,
        }


def start_login_flow() -> Dict[str, Any]:
    """Starts the background Playwright task to navigate to WhatsApp Web and capture QR codes."""
    global _login_thread, _stop_requested

    with AUTH_LOCK:
        if _login_thread is not None and _login_thread.is_alive():
            return {"status": "in_progress", "message": "Login session is already running."}

        if not DISPATCH_LOCK.acquire(blocking=False):
            return {
                "status": "busy",
                "message": "A report dispatch or browser session is currently in progress. Please wait a moment and try again."
            }

        _stop_requested = False
        _current_state["status"] = "starting"
        _current_state["message"] = "Launching browser engine and loading WhatsApp Web..."
        _current_state["qr_available"] = False
        _current_state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        _login_thread = threading.Thread(target=_run_playwright_login, daemon=True)
        _login_thread.start()

    return {"status": "started", "message": "Browser launched. Waiting for WhatsApp QR code..."}


def _run_playwright_login():
    global _stop_requested
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        QR_IMAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cleanup_stale_locks(SESSION_DIR)

        print("[WhatsApp Auth] Launching browser engine with desktop User-Agent...")
        with sync_playwright() as p:
            launch_kwargs = {
                "headless": True,
                "user_data_dir": str(SESSION_DIR),
                "user_agent": CHROME_DESKTOP_UA,
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
                    launch_kwargs.pop("channel", None)
                    context = p.chromium.launch_persistent_context(**launch_kwargs)
                else:
                    raise e_launch

            page = context.pages[0] if context.pages else context.new_page()

            with AUTH_LOCK:
                _current_state["status"] = "starting"
                _current_state["message"] = "Loading WhatsApp Web (https://web.whatsapp.com/)..."

            print("[WhatsApp Auth] Navigating to https://web.whatsapp.com/...")
            page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)

            start_time = time.time()
            max_duration = 300  # 5 minutes maximum for QR scan
            last_capture_time = 0.0

            while time.time() - start_time < max_duration:
                if _stop_requested:
                    print("[WhatsApp Auth] Login process cancelled by user request.")
                    break

                # 1. Check if already authenticated
                if page.locator("#side, div[data-testid='chat-list'], header[data-testid='chatlist-header'], div[contenteditable='true'][data-tab='3']").count() > 0:
                    print("[WhatsApp Auth] Chat UI detected! WhatsApp account authenticated successfully.")
                    with AUTH_LOCK:
                        _current_state["status"] = "authenticated"
                        _current_state["message"] = "Successfully linked and authenticated!"
                        _current_state["qr_available"] = False
                        _current_state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    STATUS_FILE.write_text(
                        json.dumps({
                            "authenticated": True,
                            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }, indent=2),
                        encoding="utf-8"
                    )

                    if QR_IMAGE_PATH.exists():
                        try:
                            QR_IMAGE_PATH.unlink()
                        except Exception:
                            pass
                    break

                # 2. Check for reload button on expired QR code
                reload_btn = page.locator("button:has-text('reload'), button:has-text('Click to reload'), span[data-icon='refresh'], div[role='button']:has(span[data-icon='refresh'])").first
                if reload_btn.count() > 0 and reload_btn.is_visible():
                    print("[WhatsApp Auth] QR code expired on WhatsApp Web. Clicking reload...")
                    try:
                        reload_btn.click()
                        time.sleep(2)
                    except Exception:
                        pass

                # 3. Check for QR code element
                canvas = page.locator("canvas, div[data-ref], div[data-testid='qrcode']").first
                if canvas.count() > 0 and canvas.is_visible():
                    now = time.time()
                    if (not _current_state.get("qr_available")) or (now - last_capture_time >= 5):
                        try:
                            canvas.screenshot(path=str(QR_IMAGE_PATH.resolve()))
                            last_capture_time = now
                            with AUTH_LOCK:
                                _current_state["status"] = "needs_scan"
                                _current_state["message"] = "QR Code ready. Open WhatsApp on your phone -> Linked Devices -> Scan QR Code."
                                _current_state["qr_available"] = True
                                _current_state["last_qr_ts"] = now
                            print(f"[WhatsApp Auth] Live QR code snapshot updated at {datetime.now().strftime('%H:%M:%S')}")
                        except Exception as e_shot:
                            print(f"[WhatsApp Auth] Warning taking QR snapshot: {e_shot}")

                time.sleep(2)

            if not _stop_requested and _current_state["status"] != "authenticated":
                with AUTH_LOCK:
                    _current_state["status"] = "timeout"
                    _current_state["message"] = "QR Code expired or scan timed out. Click 'Scan QR Code' to retry."
                    _current_state["qr_available"] = False

            context.close()
    except Exception as e:
        print(f"[WhatsApp Auth] Browser error: {e}")
        with AUTH_LOCK:
            _current_state["status"] = "error"
            _current_state["message"] = f"Browser error: {e}"
            _current_state["qr_available"] = False
    finally:
        try:
            DISPATCH_LOCK.release()
        except RuntimeError:
            pass


def cancel_login() -> Dict[str, Any]:
    """Cancels any active login flow and closes the background browser."""
    global _stop_requested
    _stop_requested = True
    with AUTH_LOCK:
        _current_state["status"] = "idle"
        _current_state["message"] = "Login cancelled by user."
        _current_state["qr_available"] = False
    if QR_IMAGE_PATH.exists():
        try:
            QR_IMAGE_PATH.unlink()
        except Exception:
            pass
    return {"status": "OK", "message": "Login cancelled"}


def logout_session() -> Dict[str, Any]:
    """Wipes saved WhatsApp Web session completely to allow pairing with a new phone."""
    cancel_login()
    time.sleep(1)

    with DISPATCH_LOCK:
        if SESSION_DIR.exists():
            cleanup_stale_locks(SESSION_DIR)
            try:
                shutil.rmtree(SESSION_DIR)
                print(f"[WhatsApp Session] Successfully wiped session directory: {SESSION_DIR}")
            except Exception as e:
                print(f"[WhatsApp Session] Warning wiping directory: {e}")

        if STATUS_FILE.exists():
            try:
                STATUS_FILE.unlink()
            except Exception:
                pass

        if QR_IMAGE_PATH.exists():
            try:
                QR_IMAGE_PATH.unlink()
            except Exception:
                pass

    return {
        "status": "OK",
        "message": "WhatsApp session deleted successfully. You can now scan a QR code with a different phone."
    }
