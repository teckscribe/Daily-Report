"""
telegram_bot.py
===============
Interactive Telegram Operations Control Bot for Daily QOS Tracker.

Menu Hierarchy:
1. Main Menu:
   - ⚙️ Control Buttons       (opens Sub Menu: Control Buttons)
   - 🚀 Render and Send        (opens Sub Menu: Render and Send)
   - ❌ Close                  (vanishes the menu UI)

2. Sub Menu 1 (Control Buttons):
   - ▶️ Start                  (starts daily-work-report systemd service)
   - ⏹️ Stop                   (stops daily-work-report systemd service)
   - 🔄 Restart                (restarts daily-work-report systemd service)
   - 📊 Status                 (queries service state, uptime & scheduler health)
   - 🔙 Back to Main Menu

3. Sub Menu 2 (Render and Send):
   - 📊 Send Complaint         (dispatches Complaint reports to preconfigured WhatsApp groups/numbers)
   - 📋 Send SR                (dispatches Service Request reports to preconfigured WhatsApp groups/numbers)
   - 📱 Test Send Complaint    (sends Complaint reports to preconfigured test WhatsApp numbers)
   - 📲 Test Send SR           (sends Service Request reports to preconfigured test WhatsApp numbers)
   - 🖼️ Send Reports in Telegram (delivers all High-DPI cards straight into Telegram chat)
   - ✏️ Update the Test Numbers (manage / add / remove / reset preconfigured test WhatsApp numbers)
   - 🔙 Back to Main Menu

Mandatory Safety Guardrail:
- Every action prompts an explicit "Confirm" and "Cancel" question before executing.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

import db_manager
from config import (
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_SR_REPORT_IMAGE_PATH,
    ADTV_SR_REPORT_IMAGE_PATH,
    SR_REPORT_IMAGE_PATH,
    BASE_DIR,
    DATA_DIR,
    TELEGRAM_ALLOWED_USERS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_TEST_PHONE,
    TELEGRAM_WEB_URL,
)

SERVICE_NAME = os.getenv("SYSTEMD_SERVICE_NAME", "daily-work-report")
POLL_TIMEOUT = 30
user_states: Dict[int, str] = {}
authorized_users_cache: Set[int] = set(TELEGRAM_ALLOWED_USERS)


# --- Lightweight Telegram API Client ---

class TelegramAPI:
    def __init__(self, token: str):
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def is_configured(self) -> bool:
        return bool(self.token and len(self.token) > 15 and ":" in self.token)

    def get_me(self) -> Dict[str, Any]:
        res = requests.get(f"{self.base_url}/getMe", timeout=10)
        return res.json()

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            res = requests.post(url, json=payload, timeout=15)
            return res.json()
        except Exception as e:
            print(f"[Telegram API] send_message error: {e}")
            return {"ok": False, "description": str(e)}

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/editMessageText"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            res = requests.post(url, json=payload, timeout=15)
            return res.json()
        except Exception as e:
            print(f"[Telegram API] edit_message_text error: {e}")
            return {"ok": False, "description": str(e)}

    def delete_message(
        self,
        chat_id: int | str,
        message_id: int,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/deleteMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"[Telegram API] delete_message error: {e}")
            return {"ok": False, "description": str(e)}

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/answerCallbackQuery"
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        try:
            res = requests.post(url, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"[Telegram API] answer_callback_query error: {e}")
            return {"ok": False, "description": str(e)}

    def send_photo(
        self,
        chat_id: int | str,
        photo_path: Path | str,
        caption: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/sendPhoto"
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = parse_mode
        p = Path(photo_path)
        if not p.exists():
            return {"ok": False, "description": f"File not found: {p}"}
        try:
            with open(p, "rb") as f:
                res = requests.post(url, data=data, files={"photo": f}, timeout=45)
            return res.json()
        except Exception as e:
            print(f"[Telegram API] send_photo error: {e}")
            return {"ok": False, "description": str(e)}

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/getUpdates"
        params: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        try:
            res = requests.get(url, params=params, timeout=timeout + 10)
            data = res.json()
            if data.get("ok"):
                return data.get("result", [])
        except Exception as e:
            print(f"[Telegram API] get_updates error: {e}")
        return []


# --- System Service Management (systemctl) ---

def run_shell_command(cmd: List[str], timeout: int = 15) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def get_service_status() -> Dict[str, Any]:
    """Queries systemd service state and checks web scheduler settings."""
    is_active = False
    systemd_state = "unknown"
    systemd_output = ""

    if sys.platform != "win32":
        code, out, _ = run_shell_command(["systemctl", "is-active", SERVICE_NAME])
        systemd_state = out.strip().lower()
        is_active = (systemd_state == "active")

        # Get detailed uptime / memory
        _, out_status, _ = run_shell_command(["systemctl", "status", SERVICE_NAME])
        systemd_output = out_status
    else:
        # Windows development check: test if web port 8201 is listening
        try:
            r = requests.get(f"{TELEGRAM_WEB_URL}/api/system/settings", timeout=2)
            is_active = (r.status_code == 200)
            systemd_state = "active (windows port listening)" if is_active else "inactive"
        except Exception:
            systemd_state = "inactive"
            is_active = False

    # Check web server settings
    web_connected = False
    scheduler_enabled = None
    last_cycle = "Not available"
    last_status = "Not available"
    try:
        r = requests.get(f"{TELEGRAM_WEB_URL}/api/system/settings", timeout=3)
        if r.status_code == 200:
            web_connected = True
            info = r.json()
            scheduler_enabled = info.get("scheduler_enabled", True)
            last_cycle = info.get("last_cycle_timestamp", "None")
            last_status = info.get("last_cycle_status", "Ready")
    except Exception:
        web_connected = False

    return {
        "is_active": is_active,
        "systemd_state": systemd_state,
        "web_connected": web_connected,
        "scheduler_enabled": scheduler_enabled,
        "last_cycle": last_cycle,
        "last_status": last_status,
        "raw_systemd": systemd_output,
    }


def _exec_service_command(action: str) -> Tuple[bool, str]:
    if sys.platform == "win32":
        return True, f"Simulated service {action} (running on Windows local environment)"
    # Try non-interactive sudo first (-n prevents hanging on password prompt)
    code, out, err = run_shell_command(["sudo", "-n", "systemctl", action, SERVICE_NAME])
    if code != 0:
        # Fallback to direct systemctl (in case Polkit or root allows it)
        code, out, err = run_shell_command(["systemctl", action, SERVICE_NAME])
    time.sleep(2)
    st = get_service_status()
    if action in ("start", "restart"):
        if st["is_active"]:
            return True, f"Service '{SERVICE_NAME}' {action}ed successfully and is ACTIVE."
        return False, f"Failed to {action} service '{SERVICE_NAME}'. Error: {err or out or 'Check systemctl permissions.'}"
    elif action == "stop":
        if not st["is_active"]:
            return True, f"Service '{SERVICE_NAME}' has been STOPPED."
        return False, f"Failed to stop service '{SERVICE_NAME}'. Error: {err or out or 'Check systemctl permissions.'}"
    return False, f"Unknown action: {action}"


def start_system_service() -> Tuple[bool, str]:
    return _exec_service_command("start")


def stop_system_service() -> Tuple[bool, str]:
    return _exec_service_command("stop")


def restart_system_service() -> Tuple[bool, str]:
    return _exec_service_command("restart")


# --- Report Dispatches via Web API ---

def trigger_group_dispatch(region_id: str = "thrissur") -> Tuple[bool, str]:
    """Calls web server endpoint to run automated Complaint cycle and dispatch to groups."""
    try:
        url = f"{TELEGRAM_WEB_URL}/api/system/run-automated-cycle-now?region_id={region_id}"
        res = requests.post(url, json={"region_id": region_id, "pipeline": "complaint"}, timeout=300)
        data = res.json()
        if res.status_code == 200 and data.get("status") == "OK":
            return True, data.get("message", "All active dispatch rules triggered successfully.")
        return False, data.get("message") or data.get("detail") or "Failed to run automated cycle"
    except Exception as e:
        return False, f"Could not connect to web server: {e}"


def trigger_test_delivery(target_phone: str, region_id: str = "thrissur") -> Tuple[bool, str]:
    """Generates High-DPI reports and delivers them to a specific phone number."""
    clean_phone = target_phone.strip()
    if not clean_phone:
        return False, "Target phone number cannot be empty."

    try:
        url = f"{TELEGRAM_WEB_URL}/api/regions/{region_id}/generate-and-send"
        payload = {"target_phone": clean_phone, "report_type": "all"}
        res = requests.post(url, json=payload, timeout=300)
        data = res.json()
        if res.status_code == 200 and data.get("status") == "OK":
            return True, data.get("message", f"Delivered to {clean_phone} successfully.")
        return False, data.get("detail") or data.get("message") or "Test delivery failed"
    except Exception as e:
        return False, f"Could not connect to web server: {e}"


def trigger_sr_dispatch(region_id: str = "thrissur") -> Tuple[bool, str]:
    """Calls web server endpoint to run automated Service Request cycle and dispatch."""
    try:
        url = f"{TELEGRAM_WEB_URL}/api/service-request/run-cycle?region_id={region_id}"
        res = requests.post(url, json={"region_id": region_id}, timeout=300)
        data = res.json()
        if res.status_code == 200 and data.get("status") == "OK":
            return True, data.get("message", "Service Request reports generated & dispatched successfully.")
        return False, data.get("message") or data.get("detail") or "Failed to run Service Request cycle"
    except Exception as e:
        return False, f"Could not connect to web server: {e}"


def trigger_sr_test_delivery(target_phone: str, region_id: str = "thrissur") -> Tuple[bool, str]:
    """Generates Service Request reports and delivers them to a specific phone number."""
    clean_phone = target_phone.strip()
    if not clean_phone:
        return False, "Target phone number cannot be empty."

    try:
        url = f"{TELEGRAM_WEB_URL}/api/service-request/generate-and-send"
        payload = {"target_phone": clean_phone, "report_type": "all"}
        res = requests.post(url, json=payload, timeout=300)
        data = res.json()
        if res.status_code == 200 and data.get("status") == "OK":
            return True, data.get("message", f"SR report delivered to {clean_phone} successfully.")
        return False, data.get("detail") or data.get("message") or "SR delivery failed"
    except Exception as e:
        return False, f"Could not connect to web server: {e}"


DEFAULT_TEST_NUMBERS: List[str] = []


def get_preconfigured_test_numbers() -> List[str]:
    """Retrieves list of preconfigured test numbers from persistent SQLite settings."""
    raw = db_manager.get_setting("telegram_test_numbers", "").strip()
    if raw:
        try:
            nums = json.loads(raw)
            if isinstance(nums, list) and nums:
                return [str(n).strip() for n in nums if str(n).strip()]
        except Exception:
            nums = [n.strip() for n in raw.split(",") if n.strip()]
            if nums:
                return nums

    # Seed defaults if not set
    defaults: List[str] = []
    if TELEGRAM_TEST_PHONE and TELEGRAM_TEST_PHONE.strip():
        defaults.append(TELEGRAM_TEST_PHONE.strip())
    for d in DEFAULT_TEST_NUMBERS:
        if d not in defaults:
            defaults.append(d)
    return defaults


def set_preconfigured_test_numbers(numbers: List[str]) -> bool:
    """Saves list of test numbers to SQLite system_settings."""
    clean: List[str] = []
    for n in numbers:
        cleaned = str(n).strip()
        if cleaned and cleaned not in clean:
            clean.append(cleaned)
    return db_manager.set_setting("telegram_test_numbers", json.dumps(clean))


def add_preconfigured_test_number(number: str) -> bool:
    """Adds a test number to persistent list."""
    nums = get_preconfigured_test_numbers()
    cleaned = number.strip()
    if cleaned and cleaned not in nums:
        nums.append(cleaned)
        return set_preconfigured_test_numbers(nums)
    return True


def remove_preconfigured_test_number(number: str) -> bool:
    """Removes a test number from persistent list."""
    nums = get_preconfigured_test_numbers()
    cleaned = number.strip()
    if cleaned in nums:
        nums.remove(cleaned)
        return set_preconfigured_test_numbers(nums)
    return True


def reset_preconfigured_test_numbers() -> bool:
    """Resets test numbers back to system defaults."""
    defaults: List[str] = []
    if TELEGRAM_TEST_PHONE and TELEGRAM_TEST_PHONE.strip():
        defaults.append(TELEGRAM_TEST_PHONE.strip())
    for d in DEFAULT_TEST_NUMBERS:
        if d not in defaults:
            defaults.append(d)
    return set_preconfigured_test_numbers(defaults)


# --- Keyboard Layouts (UI Buttons) ---

def get_main_menu_keyboard(service_active: Optional[bool] = None) -> Dict[str, Any]:
    """
    Main Menu:
    • Control Buttons
    • Render and Send
    • Close
    """
    return {
        "inline_keyboard": [
            [
                {"text": "⚙️ Control Buttons", "callback_data": "menu:control"},
            ],
            [
                {"text": "🚀 Render and Send", "callback_data": "menu:render_send"},
            ],
            [
                {"text": "❌ Close", "callback_data": "menu:close_prompt"},
            ],
        ]
    }


def get_control_menu_keyboard(service_active: bool = True) -> Dict[str, Any]:
    """
    Sub Menu: Control Buttons
    • Start, Stop, Restart, Status
    • Back to Main Menu
    """
    active_indicator = "🟢 Running" if service_active else "🛑 Stopped"
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ Start", "callback_data": "srv:start"},
                {"text": "⏹️ Stop", "callback_data": "srv:stop"},
            ],
            [
                {"text": "🔄 Restart", "callback_data": "srv:restart"},
                {"text": f"📊 Status ({active_indicator})", "callback_data": "srv:status"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu:main"},
            ],
        ]
    }


def get_render_send_menu_keyboard() -> Dict[str, Any]:
    """
    Sub Menu: Render and Send
    • Send Complaint
    • Send SR
    • Test Send Complaint
    • Test Send SR
    • Send Reports in telegram
    • Update the Test Numbers
    • Back to Main Menu
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Send Complaint", "callback_data": "action:send_complaint"},
            ],
            [
                {"text": "📋 Send SR", "callback_data": "action:send_sr"},
            ],
            [
                {"text": "📱 Test Send Complaint", "callback_data": "action:test_complaint"},
            ],
            [
                {"text": "📲 Test Send SR", "callback_data": "action:test_sr"},
            ],
            [
                {"text": "🖼️ Send Reports in Telegram", "callback_data": "action:send_reports_telegram"},
            ],
            [
                {"text": "✏️ Update the Test Numbers", "callback_data": "action:manage_test_numbers"},
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu:main"},
            ],
        ]
    }


def get_test_selection_keyboard(action_type: str, test_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Displays selection of preconfigured test numbers or enter custom number."""
    nums = test_numbers if test_numbers is not None else get_preconfigured_test_numbers()
    buttons = []
    if len(nums) > 1:
        buttons.append([{"text": f"🚀 Send to ALL Test Numbers ({len(nums)})", "callback_data": f"test_sel:{action_type}:ALL"}])
    for n in nums:
        buttons.append([{"text": f"📞 Send to {n}", "callback_data": f"test_sel:{action_type}:{n}"}])
    buttons.append([{"text": "✏️ Enter Custom Mobile Number", "callback_data": f"test_sel:{action_type}:custom"}])
    buttons.append([{"text": "🔙 Back to Render & Send", "callback_data": "menu:render_send"}])
    return {"inline_keyboard": buttons}


def get_test_numbers_manager_keyboard(test_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Keyboard for managing preconfigured test numbers."""
    nums = test_numbers if test_numbers is not None else get_preconfigured_test_numbers()
    buttons = [
        [{"text": "➕ Add Test Number", "callback_data": "tnum:add_prompt"}],
    ]
    if nums:
        buttons.append([{"text": "➖ Remove a Test Number", "callback_data": "tnum:remove_menu"}])
    buttons.append([{"text": "🔄 Reset to Defaults", "callback_data": "tnum:reset_prompt"}])
    buttons.append([{"text": "🔙 Back to Render & Send", "callback_data": "menu:render_send"}])
    return {"inline_keyboard": buttons}


def get_remove_test_numbers_keyboard(test_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Keyboard listing test numbers to delete."""
    nums = test_numbers if test_numbers is not None else get_preconfigured_test_numbers()
    buttons = []
    for num in nums:
        buttons.append([{"text": f"➖ Remove {num}", "callback_data": f"tnum:del_prompt:{num}"}])
    buttons.append([{"text": "🔙 Back", "callback_data": "action:manage_test_numbers"}])
    return {"inline_keyboard": buttons}


def get_confirmation_keyboard(confirm_data: str, cancel_data: str = "menu:main") -> Dict[str, Any]:
    """Standard Confirm & Cancel confirmation modal keyboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": confirm_data},
                {"text": "❌ Cancel", "callback_data": cancel_data},
            ]
        ]
    }


def get_sr_menu_keyboard() -> Dict[str, Any]:
    """Legacy helper maintained for backward compatibility."""
    return get_render_send_menu_keyboard()


def get_phone_selection_keyboard(default_phone: str = "", prefix: str = "num") -> Dict[str, Any]:
    """Legacy helper maintained for backward compatibility."""
    act = "sr" if "sr" in prefix else "complaint"
    return get_test_selection_keyboard(act)


# --- Message Formatting Helpers ---

def format_main_menu_message() -> str:
    return "🎛 <b>Daily QOS Tracker — Control Panel</b>"


def format_status_message(status_info: Dict[str, Any]) -> str:
    is_act = status_info["is_active"]
    act_badge = "🟢 <b>ACTIVE (Running)</b>" if is_act else "🛑 <b>INACTIVE (Stopped)</b>"
    sched = status_info.get("scheduler_enabled")
    sched_badge = "🟢 Enabled" if sched else ("🔴 Disabled" if sched is False else "⚪ Unknown")
    web_badge = "🟢 Connected" if status_info["web_connected"] else "🔴 Disconnected"

    return (
        "⚙️ <b>Control Center — Background Services</b>\n\n"
        f"<b>System Service:</b> {act_badge}\n"
        f"<b>Web Server API:</b> {web_badge} (<code>{TELEGRAM_WEB_URL}</code>)\n"
        f"<b>Scheduler Engine:</b> {sched_badge}\n"
        f"<b>Last Auto-Run:</b> <code>{status_info.get('last_cycle', 'None')}</code>\n"
        f"<b>Last Status:</b> <i>{status_info.get('last_status', 'Ready')}</i>\n\n"
        "<i>Select an action below to control the service or check status:</i>"
    )


def format_control_menu_message(status_info: Dict[str, Any]) -> str:
    return format_status_message(status_info)


def format_render_send_menu_message() -> str:
    return (
        "🚀 <b>Render and Send Center</b>\n\n"
        "Select an action below to dispatch reports, send test deliveries, or update test numbers:\n\n"
        "• <b>📊 Send Complaint:</b> To preconfigured WhatsApp groups/numbers\n"
        "• <b>📋 Send SR:</b> To preconfigured WhatsApp groups/numbers\n"
        "• <b>📱 Test Send Complaint:</b> To preconfigured test WhatsApp numbers\n"
        "• <b>📲 Test Send SR:</b> To preconfigured test WhatsApp numbers\n"
        "• <b>🖼️ Send Reports in Telegram:</b> Deliver high-resolution report cards here\n"
        "• <b>✏️ Update the Test Numbers:</b> Add, remove, or reset test numbers"
    )


def format_test_numbers_manager_message(numbers: List[str]) -> str:
    msg = "📱 <b>Preconfigured Test WhatsApp Numbers</b>\n\n"
    if numbers:
        msg += "Registered test recipients:\n"
        for i, num in enumerate(numbers, 1):
            msg += f"{i}. <code>{num}</code>\n"
    else:
        msg += "<i>No test numbers currently configured.</i>\n"
    msg += "\nSelect an option below to add, remove, or reset:"
    return msg


# --- Authorization Helper ---

def is_user_authorized(user_id: int, chat_id: int) -> bool:
    global authorized_users_cache
    if not authorized_users_cache:
        # Auto-authorize first caller if no admin IDs are configured in .env
        authorized_users_cache.add(user_id)
        print(f"[Telegram Bot] [!] No TELEGRAM_ALLOWED_USERS in .env. Auto-authorized user: {user_id}")
        return True
    return user_id in authorized_users_cache or chat_id in authorized_users_cache


# --- Telegram Bot Engine ---

class TelegramBotRunner:
    def __init__(self, api: TelegramAPI):
        self.api = api
        self.running = False
        self.last_update_id = 0

    def start(self):
        if not self.api.is_configured():
            print("\n[Telegram Bot] [!] TELEGRAM_BOT_TOKEN is not configured in .env.")
            print("[Telegram Bot] Please create a bot with @BotFather and add your token to .env:")
            print("  TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ\n")
            return

        try:
            bot_info = self.api.get_me()
            if not bot_info.get("ok"):
                print(f"[Telegram Bot] [!] Invalid bot token: {bot_info}")
                return
            bot_user = bot_info["result"]["username"]
            print(f"\n[Telegram Bot] Logged in as @{bot_user}! Starting long-polling listener...")
        except Exception as e:
            print(f"[Telegram Bot] Connection error: {e}")
            return

        self.running = True
        while self.running:
            try:
                updates = self.api.get_updates(offset=self.last_update_id + 1, timeout=POLL_TIMEOUT)
                for update in updates:
                    self.last_update_id = update["update_id"]
                    self.process_update(update)
            except Exception as e:
                print(f"[Telegram Bot] Polling loop error: {e}")
                time.sleep(3)

    def stop(self):
        self.running = False

    def process_update(self, update: Dict[str, Any]):
        # Handle Callback Queries (Button clicks)
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb["id"]
            user_id = cb["from"]["id"]
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            data = cb.get("data", "")

            if not is_user_authorized(user_id, chat_id):
                self.api.answer_callback_query(
                    cb_id,
                    text=f"⛔ Unauthorized (ID: {user_id}). Add to TELEGRAM_ALLOWED_USERS in .env",
                    show_alert=True,
                )
                return

            self.handle_callback(cb_id, chat_id, message_id, data)
            return

        # Handle Standard Chat Messages
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = (msg.get("text") or "").strip()

            if not is_user_authorized(user_id, chat_id):
                denied_msg = (
                    "⛔ <b>Access Restricted</b>\n\n"
                    f"Your Telegram User ID is: <code>{user_id}</code>\n\n"
                    "To authorize this account, open <code>.env</code> on the server and add:\n"
                    f"<code>TELEGRAM_ALLOWED_USERS={user_id}</code>\n"
                    "Then restart the bot."
                )
                self.api.send_message(chat_id, denied_msg)
                return

            self.handle_message(chat_id, user_id, text)

    def handle_message(self, chat_id: int, user_id: int, text: str):
        global user_states

        # Check interactive user state inputs
        state = user_states.get(chat_id)
        if state:
            user_states.pop(chat_id, None)
            clean_digits = re.sub(r"\D", "", text)
            if len(clean_digits) < 10:
                self.api.send_message(
                    chat_id,
                    "❌ <b>Invalid Phone Number</b>\nPlease provide a valid 10-digit mobile number.",
                )
                self.send_render_send_menu(chat_id)
                return
            formatted_num = f"+91{clean_digits[-10:]}"

            if state in ("WAITING_FOR_COMPLAINT_TEST_PHONE", "WAITING_FOR_PHONE"):
                prompt = (
                    "⚠️ <b>Confirm Action: Test Send Complaint</b>\n\n"
                    f"Are you sure you want to generate Complaint reports and send to:\n"
                    f"📱 <b>{formatted_num}</b>?"
                )
                kb = get_confirmation_keyboard(
                    confirm_data=f"exec:test_complaint:{formatted_num}",
                    cancel_data="action:test_complaint",
                )
                self.api.send_message(chat_id, prompt, reply_markup=kb)
                return

            elif state in ("WAITING_FOR_SR_TEST_PHONE", "WAITING_FOR_SR_PHONE"):
                prompt = (
                    "⚠️ <b>Confirm Action: Test Send Service Request</b>\n\n"
                    f"Are you sure you want to generate Service Request reports and send to:\n"
                    f"📱 <b>{formatted_num}</b>?"
                )
                kb = get_confirmation_keyboard(
                    confirm_data=f"exec:test_sr:{formatted_num}",
                    cancel_data="action:test_sr",
                )
                self.api.send_message(chat_id, prompt, reply_markup=kb)
                return

            elif state == "WAITING_FOR_ADD_TEST_PHONE":
                prompt = (
                    "⚠️ <b>Confirm Action: Add Test Number</b>\n\n"
                    f"Are you sure you want to add <b>{formatted_num}</b> to preconfigured test numbers?"
                )
                kb = get_confirmation_keyboard(
                    confirm_data=f"exec:add_tnum:{formatted_num}",
                    cancel_data="action:manage_test_numbers",
                )
                self.api.send_message(chat_id, prompt, reply_markup=kb)
                return

        # Commands (All command triggers require confirmation before execution)
        if text.startswith("/start") or text.startswith("/menu") or text.startswith("/help"):
            self.send_main_menu(chat_id)
        elif text.startswith("/control"):
            self.send_control_menu(chat_id)
        elif text.startswith("/render"):
            self.send_render_send_menu(chat_id)
        elif text.startswith("/status"):
            prompt = (
                "⚠️ <b>Confirm Action: Refresh Status</b>\n\n"
                "Query live systemd service and web server health to refresh status?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:srv_status", cancel_data="menu:control"),
            )
        elif text.startswith("/start_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Start Service</b>\n\n"
                f"Are you sure you want to <b>START</b> <code>{SERVICE_NAME}</code>?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:srv_start", cancel_data="menu:control"),
            )
        elif text.startswith("/stop_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Stop Service</b>\n\n"
                f"Are you sure you want to <b>STOP</b> <code>{SERVICE_NAME}</code>?\n\n"
                "<i>Note: Automated cycle schedules will be paused until restarted.</i>"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:srv_stop", cancel_data="menu:control"),
            )
        elif text.startswith("/restart_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Restart Service</b>\n\n"
                f"Are you sure you want to <b>RESTART</b> <code>{SERVICE_NAME}</code>?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:srv_restart", cancel_data="menu:control"),
            )
        elif text.startswith("/send_complaint") or text.startswith("/dispatch"):
            prompt = (
                "⚠️ <b>Confirm Action: Send Complaint</b>\n\n"
                "Are you sure you want to generate Complaint reports and dispatch them to all preconfigured <b>WhatsApp groups/numbers</b>?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:send_complaint_groups", cancel_data="menu:render_send"),
            )
        elif text.startswith("/send_sr") or text.startswith("/sr"):
            prompt = (
                "⚠️ <b>Confirm Action: Send Service Request (SR)</b>\n\n"
                "Are you sure you want to generate Service Request reports and dispatch them to all preconfigured <b>WhatsApp groups/numbers</b>?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:send_sr_groups", cancel_data="menu:render_send"),
            )
        elif text.startswith("/close"):
            prompt = (
                "⚠️ <b>Confirm Action: Close Menu</b>\n\n"
                "Are you sure you want to close and dismiss the menu UI?"
            )
            self.api.send_message(
                chat_id,
                prompt,
                reply_markup=get_confirmation_keyboard("exec:close", cancel_data="menu:main"),
            )
        else:
            self.send_main_menu(chat_id)

    def send_main_menu(self, chat_id: int, message_id: Optional[int] = None):
        msg = format_main_menu_message()
        kb = get_main_menu_keyboard()
        if message_id:
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
        else:
            self.api.send_message(chat_id, msg, reply_markup=kb)

    def send_control_menu(self, chat_id: int, message_id: Optional[int] = None):
        st = get_service_status()
        msg = format_control_menu_message(st)
        kb = get_control_menu_keyboard(st["is_active"])
        if message_id:
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
        else:
            self.api.send_message(chat_id, msg, reply_markup=kb)

    def send_render_send_menu(self, chat_id: int, message_id: Optional[int] = None):
        msg = format_render_send_menu_message()
        kb = get_render_send_menu_keyboard()
        if message_id:
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
        else:
            self.api.send_message(chat_id, msg, reply_markup=kb)

    def handle_callback(self, cb_id: str, chat_id: int, message_id: int, data: str):
        global user_states

        # 1. Navigation / Menu Switching
        if data == "menu:main":
            self.api.answer_callback_query(cb_id)
            self.send_main_menu(chat_id, message_id)
            return

        if data == "menu:control":
            self.api.answer_callback_query(cb_id)
            self.send_control_menu(chat_id, message_id)
            return

        if data in ("menu:render_send", "menu:sr"):
            self.api.answer_callback_query(cb_id)
            self.send_render_send_menu(chat_id, message_id)
            return

        if data in ("menu:cancel", "cancel"):
            self.api.answer_callback_query(cb_id, text="Action cancelled.")
            self.send_main_menu(chat_id, message_id)
            return

        if data == "menu:close_prompt":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Close Menu</b>\n\n"
                "Are you sure you want to close and dismiss the menu UI?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:close", cancel_data="menu:main")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # 2. Control Sub Menu Prompts
        if data == "srv:start":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Start Service</b>\n\n"
                f"Are you sure you want to <b>START</b> the background service (<code>{SERVICE_NAME}</code>)?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_start", cancel_data="menu:control")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "srv:stop":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Stop Service</b>\n\n"
                f"Are you sure you want to <b>STOP</b> the background service (<code>{SERVICE_NAME}</code>)?\n\n"
                "<i>Note: Automated cycle schedules will be paused until restarted.</i>"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_stop", cancel_data="menu:control")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "srv:restart":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Restart Service</b>\n\n"
                f"Are you sure you want to <b>RESTART</b> the background service (<code>{SERVICE_NAME}</code>)?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_restart", cancel_data="menu:control")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data in ("srv:status", "menu:refresh"):
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Refresh Status</b>\n\n"
                "Query live systemd service and web server health to refresh status?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_status", cancel_data="menu:control")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # 3. Render and Send Sub Menu Prompts
        if data in ("action:send_complaint", "action:dispatch_groups"):
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Send Complaint</b>\n\n"
                "Are you sure you want to generate Complaint reports and dispatch them to all preconfigured <b>WhatsApp groups/numbers</b>?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:send_complaint_groups", cancel_data="menu:render_send")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data in ("action:send_sr", "action:sr_dispatch"):
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Send Service Request (SR)</b>\n\n"
                "Are you sure you want to generate Service Request reports and dispatch them to all preconfigured <b>WhatsApp groups/numbers</b>?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:send_sr_groups", cancel_data="menu:render_send")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data in ("action:test_complaint", "action:test_delivery"):
            self.api.answer_callback_query(cb_id)
            nums = get_preconfigured_test_numbers()
            kb = get_test_selection_keyboard("complaint", nums)
            prompt = (
                "📱 <b>Test Send Complaint — Select Destination</b>\n\n"
                "Choose a preconfigured test WhatsApp number below or enter a custom one:"
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data in ("action:test_sr", "action:sr_test_delivery"):
            self.api.answer_callback_query(cb_id)
            nums = get_preconfigured_test_numbers()
            kb = get_test_selection_keyboard("sr", nums)
            prompt = (
                "📲 <b>Test Send Service Request — Select Destination</b>\n\n"
                "Choose a preconfigured test WhatsApp number below or enter a custom one:"
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data.startswith("test_sel:"):
            # Format: test_sel:{action_type}:{target}
            parts = data.split(":", 2)
            act_type = parts[1]
            target_val = parts[2]
            label = "Complaint" if act_type == "complaint" else "Service Request"
            if target_val == "custom":
                user_states[chat_id] = f"WAITING_FOR_{act_type.upper()}_TEST_PHONE"
                self.api.answer_callback_query(cb_id)
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    f"✏️ <b>Enter Target Mobile Number for {label} Test</b>\n\n"
                    "Please reply with the 10-digit mobile number (e.g. <code>+919846000000</code> or <code>9846000000</code>):",
                )
            else:
                self.api.answer_callback_query(cb_id)
                nums_text = "<b>ALL preconfigured test numbers</b>" if target_val == "ALL" else f"📱 <b>{target_val}</b>"
                prompt = (
                    f"⚠️ <b>Confirm Action: Test Send {label}</b>\n\n"
                    f"Are you sure you want to generate {label} reports and send to:\n"
                    f"{nums_text}?"
                )
                kb = get_confirmation_keyboard(
                    confirm_data=f"exec:test_{act_type}:{target_val}",
                    cancel_data=f"action:test_{act_type}",
                )
                self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # Legacy phone number callback compatibility
        if data.startswith("num:"):
            target_val = data.split(":", 1)[1]
            self.handle_callback(cb_id, chat_id, message_id, f"test_sel:complaint:{target_val}")
            return
        if data.startswith("srnum:"):
            target_val = data.split(":", 1)[1]
            self.handle_callback(cb_id, chat_id, message_id, f"test_sel:sr:{target_val}")
            return

        if data in ("action:send_reports_telegram", "action:send_photos", "action:sr_send_photos"):
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Send Reports in Telegram</b>\n\n"
                "Are you sure you want to send all high-resolution report cards (Complaint & Service Request) directly into this chat?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:send_telegram_reports", cancel_data="menu:render_send")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # 4. Test Numbers Management Prompts
        if data == "action:manage_test_numbers":
            self.api.answer_callback_query(cb_id)
            nums = get_preconfigured_test_numbers()
            msg = format_test_numbers_manager_message(nums)
            kb = get_test_numbers_manager_keyboard(nums)
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        if data == "tnum:add_prompt":
            user_states[chat_id] = "WAITING_FOR_ADD_TEST_PHONE"
            self.api.answer_callback_query(cb_id)
            self.api.edit_message_text(
                chat_id,
                message_id,
                "✏️ <b>Enter New Test Mobile Number</b>\n\n"
                "Please reply with the 10-digit mobile number to add to preconfigured test recipients:",
            )
            return

        if data == "tnum:remove_menu":
            self.api.answer_callback_query(cb_id)
            nums = get_preconfigured_test_numbers()
            kb = get_remove_test_numbers_keyboard(nums)
            self.api.edit_message_text(
                chat_id,
                message_id,
                "➖ <b>Remove a Test Number</b>\n\nSelect a number below to remove from preconfigured recipients:",
                reply_markup=kb,
            )
            return

        if data.startswith("tnum:del_prompt:"):
            num_to_del = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Remove Test Number</b>\n\n"
                f"Are you sure you want to remove <b>{num_to_del}</b> from preconfigured test numbers?"
            )
            kb = get_confirmation_keyboard(
                confirm_data=f"exec:del_tnum:{num_to_del}",
                cancel_data="action:manage_test_numbers",
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "tnum:reset_prompt":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Reset Test Numbers</b>\n\n"
                "Are you sure you want to reset preconfigured test numbers back to system defaults?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:reset_tnum", cancel_data="action:manage_test_numbers")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # 5. Confirmed Executions (exec:*)
        if data == "exec:close":
            self.api.answer_callback_query(cb_id, text="Menu closed.")
            del_res = self.api.delete_message(chat_id, message_id)
            if not del_res.get("ok"):
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    "👋 <b>Menu Closed</b>\n\n<i>Use /menu or /start to open the Control Center again.</i>",
                    reply_markup={"inline_keyboard": [[{"text": "🎛 Open Menu", "callback_data": "menu:main"}]]},
                )
            return

        if data == "exec:srv_start":
            self.api.answer_callback_query(cb_id, text="Confirmed. Starting service...")
            self.handle_service_action(chat_id, message_id, "start")
            return

        if data == "exec:srv_stop":
            self.api.answer_callback_query(cb_id, text="Confirmed. Stopping service...")
            self.handle_service_action(chat_id, message_id, "stop")
            return

        if data == "exec:srv_restart":
            self.api.answer_callback_query(cb_id, text="Confirmed. Restarting service...")
            self.handle_service_action(chat_id, message_id, "restart")
            return

        if data == "exec:srv_status":
            self.api.answer_callback_query(cb_id, text="Confirmed. Refreshing status...")
            st = get_service_status()
            msg = "🔄 <b>Status Refreshed</b>\n\n" + format_control_menu_message(st)
            kb = get_control_menu_keyboard(st["is_active"])
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        if data in ("exec:send_complaint_groups", "exec:dispatch_groups"):
            self.api.answer_callback_query(cb_id, text="Confirmed. Triggering Complaint dispatch...")
            self.execute_complaint_group_dispatch_async(chat_id, message_id)
            return

        if data in ("exec:send_sr_groups", "exec:sr_dispatch"):
            self.api.answer_callback_query(cb_id, text="Confirmed. Triggering SR dispatch...")
            self.execute_sr_group_dispatch_async(chat_id, message_id)
            return

        if data.startswith("exec:test_complaint:"):
            target = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering Complaint test...")
            self.execute_test_complaint_async(chat_id, target, message_id)
            return

        if data.startswith("exec:test_delivery:"):
            target = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering Complaint test...")
            self.execute_test_complaint_async(chat_id, target, message_id)
            return

        if data.startswith("exec:test_sr:"):
            target = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering SR test...")
            self.execute_test_sr_async(chat_id, target, message_id)
            return

        if data.startswith("exec:sr_test_delivery:"):
            target = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering SR test...")
            self.execute_test_sr_async(chat_id, target, message_id)
            return

        if data in ("exec:send_telegram_reports", "exec:send_photos", "exec:sr_send_photos"):
            self.api.answer_callback_query(cb_id, text="Confirmed. Sending reports in Telegram...")
            self.execute_send_telegram_reports_async(chat_id, message_id)
            return

        if data.startswith("exec:add_tnum:"):
            num_to_add = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text=f"Number added: {num_to_add}")
            add_preconfigured_test_number(num_to_add)
            nums = get_preconfigured_test_numbers()
            msg = f"✅ Added <b>{num_to_add}</b> to test numbers!\n\n" + format_test_numbers_manager_message(nums)
            kb = get_test_numbers_manager_keyboard(nums)
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        if data.startswith("exec:del_tnum:"):
            num_to_del = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text=f"Number removed: {num_to_del}")
            remove_preconfigured_test_number(num_to_del)
            nums = get_preconfigured_test_numbers()
            msg = f"✅ Removed <b>{num_to_del}</b> from test numbers.\n\n" + format_test_numbers_manager_message(nums)
            kb = get_test_numbers_manager_keyboard(nums)
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        if data == "exec:reset_tnum":
            self.api.answer_callback_query(cb_id, text="Reset to defaults.")
            reset_preconfigured_test_numbers()
            nums = get_preconfigured_test_numbers()
            msg = "✅ Test numbers reset to system defaults.\n\n" + format_test_numbers_manager_message(nums)
            kb = get_test_numbers_manager_keyboard(nums)
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

    # --- Asynchronous Action Handlers ---

    def handle_service_action(self, chat_id: int, message_id: Optional[int], action: str):
        def worker():
            if message_id:
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    f"⏳ <b>Executing {action.upper()} on {SERVICE_NAME}...</b>\nPlease wait a moment.",
                )

            if action == "start":
                ok, msg = start_system_service()
            elif action == "stop":
                ok, msg = stop_system_service()
            elif action == "restart":
                ok, msg = restart_system_service()
            else:
                ok, msg = False, "Unknown action"

            st = get_service_status()
            res_icon = "✅" if ok else "❌"
            notice = f"{res_icon} <b>{msg}</b>\n\n" + format_control_menu_message(st)
            kb = get_control_menu_keyboard(st["is_active"])

            if message_id:
                self.api.edit_message_text(chat_id, message_id, notice, reply_markup=kb)
            else:
                self.api.send_message(chat_id, notice, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_complaint_group_dispatch_async(self, chat_id: int, message_id: Optional[int] = None):
        def worker():
            status_text = (
                "⏳ <b>Automated Complaint Pipeline Running</b>\n\n"
                "• Downloading latest tickets from Softcode & SMS portals...\n"
                "• Computing complaint summary tables...\n"
                "• Rendering High-DPI Retina report cards...\n"
                "• Dispatching to preconfigured WhatsApp Groups & ACSO contacts..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            ok, res_msg = trigger_group_dispatch("thrissur")
            kb = get_render_send_menu_keyboard()

            if ok:
                finish_text = (
                    "✅ <b>Complaint Group Dispatch Complete!</b>\n\n"
                    f"<i>{res_msg}</i>"
                )
            else:
                finish_text = (
                    "❌ <b>Complaint Group Dispatch Error</b>\n\n"
                    f"<code>{res_msg}</code>"
                )

            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_sr_group_dispatch_async(self, chat_id: int, message_id: Optional[int] = None):
        def worker():
            status_text = (
                "⏳ <b>Service Request Pending Pipeline Running</b>\n\n"
                "• Parsing raw Service Request workbooks...\n"
                "• Computing ACSO-wise pending days summary...\n"
                "• Rendering High-DPI Retina report cards...\n"
                "• Dispatching to preconfigured WhatsApp Groups & ACSO contacts..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            ok, res_msg = trigger_sr_dispatch("thrissur")
            kb = get_render_send_menu_keyboard()

            if ok:
                finish_text = (
                    "✅ <b>Service Request Dispatch Complete!</b>\n\n"
                    f"<i>{res_msg}</i>"
                )
            else:
                finish_text = (
                    "❌ <b>Service Request Dispatch Error</b>\n\n"
                    f"<code>{res_msg}</code>"
                )

            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_test_complaint_async(
        self, chat_id: int, target: str, message_id: Optional[int] = None
    ):
        def worker():
            targets = get_preconfigured_test_numbers() if target == "ALL" else [target]
            status_text = (
                f"⏳ <b>Generating & Sending Complaint Test Delivery</b>\n\n"
                f"• Target(s): <code>{', '.join(targets)}</code>\n"
                "• Downloading latest CRM complaints...\n"
                "• Rendering high-resolution Retina cards...\n"
                "• Dispatching via WhatsApp Web..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            results: List[Tuple[str, bool, str]] = []
            for t in targets:
                ok, res_msg = trigger_test_delivery(t, "thrissur")
                results.append((t, ok, res_msg))

            kb = get_render_send_menu_keyboard()
            all_ok = all(r[1] for r in results)
            status_lines = "\n".join(
                [f"• {r[0]}: {'✅ ' + str(r[2]) if r[1] else '❌ ' + str(r[2])}" for r in results]
            )
            icon = "✅" if all_ok else "⚠️"
            finish_text = (
                f"{icon} <b>Complaint Test Delivery Completed</b>\n\n"
                f"{status_lines}"
            )
            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_test_sr_async(
        self, chat_id: int, target: str, message_id: Optional[int] = None
    ):
        def worker():
            targets = get_preconfigured_test_numbers() if target == "ALL" else [target]
            status_text = (
                f"⏳ <b>Generating & Sending Service Request Test Delivery</b>\n\n"
                f"• Target(s): <code>{', '.join(targets)}</code>\n"
                "• Reading Service Request ticket ledger...\n"
                "• Rendering high-resolution ACSO report cards...\n"
                "• Dispatching via WhatsApp Web..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            results: List[Tuple[str, bool, str]] = []
            for t in targets:
                ok, res_msg = trigger_sr_test_delivery(t, "thrissur")
                results.append((t, ok, res_msg))

            kb = get_render_send_menu_keyboard()
            all_ok = all(r[1] for r in results)
            status_lines = "\n".join(
                [f"• {r[0]}: {'✅ ' + str(r[2]) if r[1] else '❌ ' + str(r[2])}" for r in results]
            )
            icon = "✅" if all_ok else "⚠️"
            finish_text = (
                f"{icon} <b>Service Request Test Delivery Completed</b>\n\n"
                f"{status_lines}"
            )
            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_send_telegram_reports_async(self, chat_id: int, message_id: Optional[int] = None):
        def worker():
            if message_id:
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    "⏳ <b>Delivering High-DPI Report Cards to Telegram...</b>\nPlease wait a moment.",
                )
            cards = [
                ("ADL Broadband — Team Leaders", ADL_REPORT_IMAGE_PATH),
                ("ADTv Digital TV — Team Leaders", ADTV_REPORT_IMAGE_PATH),
                ("ADL Broadband — ACSO Centers", ADL_ACSO_REPORT_IMAGE_PATH),
                ("ADTv Digital TV — ACSO Centers", ADTV_ACSO_REPORT_IMAGE_PATH),
                ("ADL Broadband — Service Requests (ACSO)", ADL_SR_REPORT_IMAGE_PATH),
                ("ADTv Digital TV — Service Requests (ACSO)", ADTV_SR_REPORT_IMAGE_PATH),
                ("Daily Service Request Combined Report", SR_REPORT_IMAGE_PATH),
            ]
            sent_count = 0
            for title, path in cards:
                if path.exists():
                    self.api.send_photo(chat_id, path, caption=f"📊 <b>{title}</b>")
                    sent_count += 1
                    time.sleep(1)

            kb = get_render_send_menu_keyboard()
            if sent_count == 0:
                self.api.send_message(
                    chat_id,
                    "⚠️ No report images found in <code>output/</code> directory. Click 'Send Complaint' or 'Send SR' to generate fresh reports.",
                    reply_markup=kb,
                )
            else:
                self.api.send_message(
                    chat_id,
                    f"✅ Delivered <b>{sent_count}</b> High-DPI report card(s) to Telegram!",
                    reply_markup=kb,
                )

        threading.Thread(target=worker, daemon=True).start()

    # Legacy method aliases for backwards compatibility
    def execute_group_dispatch_async(self, chat_id: int, message_id: Optional[int] = None):
        return self.execute_complaint_group_dispatch_async(chat_id, message_id)

    def execute_test_delivery_async(self, chat_id: int, target_phone: str, message_id: Optional[int] = None):
        return self.execute_test_complaint_async(chat_id, target_phone, message_id)

    def send_report_photos_async(self, chat_id: int, message_id: Optional[int] = None):
        return self.execute_send_telegram_reports_async(chat_id, message_id)

    def execute_sr_dispatch_async(self, chat_id: int, message_id: Optional[int] = None):
        return self.execute_sr_group_dispatch_async(chat_id, message_id)

    def execute_sr_test_delivery_async(self, chat_id: int, target_phone: str, message_id: Optional[int] = None):
        return self.execute_test_sr_async(chat_id, target_phone, message_id)

    def send_sr_report_photos_async(self, chat_id: int, message_id: Optional[int] = None):
        return self.execute_send_telegram_reports_async(chat_id, message_id)


# --- CLI Entry Point ---

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Daily QOS Tracker Telegram Bot Daemon")
    parser.add_argument("--test", action="store_true", help="Test bot token connectivity")
    parser.add_argument("--status", action="store_true", help="Print current service status")
    args = parser.parse_args()

    api = TelegramAPI(TELEGRAM_BOT_TOKEN)

    if args.status:
        st = get_service_status()
        print(json.dumps(st, indent=2))
        return

    if args.test:
        if not api.is_configured():
            print("[FAIL] TELEGRAM_BOT_TOKEN is missing or not set in .env")
            sys.exit(1)
        res = api.get_me()
        if res.get("ok"):
            bot = res["result"]
            print(f"[OK] Successfully connected! Bot: @{bot['username']} (ID: {bot['id']})")
        else:
            print(f"[FAIL] Telegram API error: {res}")
            sys.exit(1)
        return

    bot = TelegramBotRunner(api)
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n[Telegram Bot] Stopped by user.")
        bot.stop()


if __name__ == "__main__":
    main()
