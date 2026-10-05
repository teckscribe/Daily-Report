"""
telegram_bot.py
===============
Interactive Telegram Operations Control Bot for Daily QOS Tracker.

UI Buttons provided:
1. Service Management:
   - ▶️ Start Service    (systemctl start daily-work-report)
   - ⏹️ Stop Service     (systemctl stop daily-work-report)
   - 🔄 Restart Service  (systemctl restart daily-work-report)
   - 📊 Service Status   (checks systemd state & scheduler health)
2. Report Dispatches:
   - 🚀 Report-to-Group Dispatch Rules (triggers live CRM sync & sends to active WhatsApp groups)
   - 📲 Test Delivery: Generate & Send to Specific Number (preset quick-click or custom phone entry)
   - 🖼️ Send Report Photos Here (delivers all 4 High-DPI cards straight into Telegram chat)

Configuration:
All credentials are read from .env:
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_ALLOWED_USERS=... (comma-separated admin Telegram user IDs)
  TELEGRAM_TEST_PHONE=...   (default test number)
  TELEGRAM_WEB_URL=...      (default http://127.0.0.1:8201)
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
    """Calls web server endpoint to run automated cycle and dispatch to groups."""
    try:
        url = f"{TELEGRAM_WEB_URL}/api/system/run-automated-cycle-now?region_id={region_id}"
        res = requests.post(url, json={"region_id": region_id}, timeout=300)
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


# --- Keyboard Layouts (UI Buttons) ---

def get_main_menu_keyboard(service_active: bool) -> Dict[str, Any]:
    active_indicator = "🟢 Running" if service_active else "🛑 Stopped"
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ Start Service", "callback_data": "srv:start"},
                {"text": "⏹️ Stop Service", "callback_data": "srv:stop"},
            ],
            [
                {"text": "🔄 Restart Service", "callback_data": "srv:restart"},
                {"text": f"📊 Status ({active_indicator})", "callback_data": "srv:status"},
            ],
            [
                {
                    "text": "🚀 Report-to-Group Dispatch Rules",
                    "callback_data": "action:dispatch_groups",
                }
            ],
            [
                {
                    "text": "📲 Test Delivery: Generate & Send to Specific Number",
                    "callback_data": "action:test_delivery",
                }
            ],
            [
                {
                    "text": "📋 Service Request Pending Report",
                    "callback_data": "menu:sr",
                }
            ],
            [
                {
                    "text": "🖼️ Send Reports in Telegram",
                    "callback_data": "action:send_photos",
                },
                {"text": "🔄 Refresh", "callback_data": "menu:refresh"},
            ],
        ]
    }


def get_sr_menu_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🚀 Dispatch SR Reports to Groups",
                    "callback_data": "action:sr_dispatch",
                }
            ],
            [
                {
                    "text": "📲 Send SR Test Delivery",
                    "callback_data": "action:sr_test_delivery",
                }
            ],
            [
                {
                    "text": "🖼️ Send SR Report Cards Here",
                    "callback_data": "action:sr_send_photos",
                }
            ],
            [
                {"text": "🔙 Back to Main Menu", "callback_data": "menu:main"},
            ],
        ]
    }


def get_phone_selection_keyboard(default_phone: str, prefix: str = "num") -> Dict[str, Any]:
    buttons = []
    if default_phone:
        buttons.append([{"text": f"📞 Send to {default_phone} (Default)", "callback_data": f"{prefix}:{default_phone}"}])
    buttons.append([{"text": "📞 Send to +919633889430", "callback_data": f"{prefix}:+919633889430"}])
    buttons.append([{"text": "📞 Send to +917591920200", "callback_data": f"{prefix}:+917591920200"}])
    buttons.append([{"text": "✏️ Type Custom Mobile Number", "callback_data": f"{prefix}:custom"}])
    back_target = "menu:sr" if prefix.startswith("sr") else "menu:main"
    buttons.append([{"text": "🔙 Back", "callback_data": back_target}])
    return {"inline_keyboard": buttons}


def get_confirmation_keyboard(confirm_data: str, cancel_data: str = "menu:cancel") -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": confirm_data},
                {"text": "❌ Cancel", "callback_data": cancel_data},
            ]
        ]
    }




def format_status_message(status_info: Dict[str, Any]) -> str:
    is_act = status_info["is_active"]
    act_badge = "🟢 <b>ACTIVE (Running)</b>" if is_act else "🛑 <b>INACTIVE (Stopped)</b>"
    sched = status_info.get("scheduler_enabled")
    sched_badge = "🟢 Enabled" if sched else ("🔴 Disabled" if sched is False else "⚪ Unknown")
    web_badge = "🟢 Connected" if status_info["web_connected"] else "🔴 Disconnected"

    return (
        "🎛 <b>Daily QOS Tracker — Control Center</b>\n\n"
        f"<b>System Service:</b> {act_badge}\n"
        f"<b>Web Server API:</b> {web_badge} (<code>{TELEGRAM_WEB_URL}</code>)\n"
        f"<b>Scheduler Engine:</b> {sched_badge}\n"
        f"<b>Last Auto-Run:</b> <code>{status_info.get('last_cycle', 'None')}</code>\n"
        f"<b>Last Status:</b> <i>{status_info.get('last_status', 'Ready')}</i>\n\n"
        "<i>Select an action below to manage services or execute dispatches:</i>"
    )


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

        # Check if user is in interactive custom phone input mode
        if user_states.get(chat_id) == "WAITING_FOR_PHONE":
            user_states.pop(chat_id, None)
            clean_digits = re.sub(r"\D", "", text)
            if len(clean_digits) < 10:
                self.api.send_message(
                    chat_id,
                    "❌ <b>Invalid Phone Number</b>\nPlease provide a valid 10-digit mobile number.",
                )
                self.send_main_menu(chat_id)
                return

            formatted_num = f"+91{clean_digits[-10:]}"
            prompt = (
                "⚠️ <b>Confirm Action: Test Delivery</b>\n\n"
                f"Are you sure you want to generate reports and send to:\n"
                f"📱 <b>{formatted_num}</b>?"
            )
            kb = get_confirmation_keyboard(confirm_data=f"exec:test_delivery:{formatted_num}")
            self.api.send_message(chat_id, prompt, reply_markup=kb)
            return

        elif user_states.get(chat_id) == "WAITING_FOR_SR_PHONE":
            user_states.pop(chat_id, None)
            clean_digits = re.sub(r"\D", "", text)
            if len(clean_digits) < 10:
                self.api.send_message(
                    chat_id,
                    "❌ <b>Invalid Phone Number</b>\nPlease provide a valid 10-digit mobile number.",
                )
                self.send_main_menu(chat_id)
                return

            formatted_num = f"+91{clean_digits[-10:]}"
            prompt = (
                "⚠️ <b>Confirm Action: Service Request Test Delivery</b>\n\n"
                f"Are you sure you want to generate SR reports and send to:\n"
                f"📱 <b>{formatted_num}</b>?"
            )
            kb = get_confirmation_keyboard(confirm_data=f"exec:sr_test_delivery:{formatted_num}", cancel_data="menu:sr")
            self.api.send_message(chat_id, prompt, reply_markup=kb)
            return

        # Commands (All command triggers require confirmation)
        if text.startswith("/start") or text.startswith("/menu") or text.startswith("/help"):
            self.send_main_menu(chat_id)
        elif text.startswith("/status"):
            st = get_service_status()
            msg = format_status_message(st)
            kb = get_main_menu_keyboard(st["is_active"])
            self.api.send_message(chat_id, msg, reply_markup=kb)
        elif text.startswith("/sr") or text.startswith("/service_request"):
            kb = get_sr_menu_keyboard()
            prompt = (
                "📋 <b>Service Request Pending Reports (ACSO-wise)</b>\n\n"
                "Select an action below to dispatch Service Request pending reports or send test deliveries:"
            )
            self.api.send_message(chat_id, prompt, reply_markup=kb)
        elif text.startswith("/start_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Start Service</b>\n\n"
                f"Are you sure you want to <b>START</b> <code>{SERVICE_NAME}</code>?"
            )
            self.api.send_message(chat_id, prompt, reply_markup=get_confirmation_keyboard("exec:srv_start"))
        elif text.startswith("/stop_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Stop Service</b>\n\n"
                f"Are you sure you want to <b>STOP</b> <code>{SERVICE_NAME}</code>?\n\n"
                "<i>Note: Automated cycle schedules will be paused until restarted.</i>"
            )
            self.api.send_message(chat_id, prompt, reply_markup=get_confirmation_keyboard("exec:srv_stop"))
        elif text.startswith("/restart_service"):
            prompt = (
                "⚠️ <b>Confirm Action: Restart Service</b>\n\n"
                f"Are you sure you want to <b>RESTART</b> <code>{SERVICE_NAME}</code>?"
            )
            self.api.send_message(chat_id, prompt, reply_markup=get_confirmation_keyboard("exec:srv_restart"))
        elif text.startswith("/dispatch"):
            prompt = (
                "⚠️ <b>Confirm Action: Report-to-Group Dispatch Rules</b>\n\n"
                "Are you sure you want to run the automated cycle and dispatch reports to all configured <b>WhatsApp Groups</b> & ACSO contacts?"
            )
            self.api.send_message(chat_id, prompt, reply_markup=get_confirmation_keyboard("exec:dispatch_groups"))
        else:
            self.send_main_menu(chat_id)

    def send_main_menu(self, chat_id: int):
        st = get_service_status()
        msg = format_status_message(st)
        kb = get_main_menu_keyboard(st["is_active"])
        self.api.send_message(chat_id, msg, reply_markup=kb)

    def handle_callback(self, cb_id: str, chat_id: int, message_id: int, data: str):
        global user_states

        # 1. Navigation / Cancel Callbacks
        if data == "menu:cancel":
            self.api.answer_callback_query(cb_id, text="Action cancelled.")
            st = get_service_status()
            msg = "❌ <b>Action Cancelled.</b>\n\n" + format_status_message(st)
            kb = get_main_menu_keyboard(st["is_active"])
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        if data in ("srv:status", "menu:refresh", "menu:main"):
            self.api.answer_callback_query(cb_id, text="Updating status...")
            st = get_service_status()
            msg = format_status_message(st)
            kb = get_main_menu_keyboard(st["is_active"])
            self.api.edit_message_text(chat_id, message_id, msg, reply_markup=kb)
            return

        # 2. Confirmation Prompts (Before Executing Any Action)
        if data == "srv:start":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Start Service</b>\n\n"
                f"Are you sure you want to <b>START</b> the background service (<code>{SERVICE_NAME}</code>)?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_start")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "srv:stop":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Stop Service</b>\n\n"
                f"Are you sure you want to <b>STOP</b> the background service (<code>{SERVICE_NAME}</code>)?\n\n"
                "<i>Note: Automated cycle schedules will be paused until restarted.</i>"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_stop")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "srv:restart":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Restart Service</b>\n\n"
                f"Are you sure you want to <b>RESTART</b> the background service (<code>{SERVICE_NAME}</code>)?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:srv_restart")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:dispatch_groups":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Report-to-Group Dispatch Rules</b>\n\n"
                "Are you sure you want to run the automated cycle and dispatch reports to all configured <b>WhatsApp Groups</b> & ACSO contacts?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:dispatch_groups")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:test_delivery":
            self.api.answer_callback_query(cb_id)
            kb = get_phone_selection_keyboard(TELEGRAM_TEST_PHONE)
            prompt = (
                "📲 <b>Test Delivery: Generate & Send to Specific Number</b>\n\n"
                "Select a destination phone number below or enter a custom one:"
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data.startswith("num:"):
            target_val = data.split(":", 1)[1]
            if target_val == "custom":
                user_states[chat_id] = "WAITING_FOR_PHONE"
                self.api.answer_callback_query(cb_id)
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    "✏️ <b>Enter Target Mobile Number</b>\n\n"
                    "Please reply with the phone number (e.g. <code>+919846000000</code> or <code>9846000000</code>):",
                )
            else:
                self.api.answer_callback_query(cb_id)
                prompt = (
                    "⚠️ <b>Confirm Action: Test Delivery</b>\n\n"
                    f"Are you sure you want to generate reports and send to:\n"
                    f"📱 <b>{target_val}</b>?"
                )
                kb = get_confirmation_keyboard(confirm_data=f"exec:test_delivery:{target_val}")
                self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:send_photos":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Send Report Photos Here</b>\n\n"
                "Are you sure you want to send all 4 high-resolution report cards directly into this chat?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:send_photos")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # --- Service Request Callbacks ---
        if data == "menu:sr":
            self.api.answer_callback_query(cb_id)
            kb = get_sr_menu_keyboard()
            prompt = (
                "📋 <b>Service Request Pending Reports (ACSO-wise)</b>\n\n"
                "Select an action below to dispatch Service Request pending reports or send test deliveries:"
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:sr_dispatch":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Service Request Dispatch Rules</b>\n\n"
                "Are you sure you want to run the Service Request cycle and dispatch pending reports to all configured <b>WhatsApp Groups</b> & ACSO contacts?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:sr_dispatch", cancel_data="menu:sr")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:sr_test_delivery":
            self.api.answer_callback_query(cb_id)
            kb = get_phone_selection_keyboard(TELEGRAM_TEST_PHONE, prefix="srnum")
            prompt = (
                "📲 <b>Service Request Test Delivery</b>\n\n"
                "Select a destination phone number below or enter a custom one:"
            )
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data.startswith("srnum:"):
            target_val = data.split(":", 1)[1]
            if target_val == "custom":
                user_states[chat_id] = "WAITING_FOR_SR_PHONE"
                self.api.answer_callback_query(cb_id)
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    "✏️ <b>Enter Target Mobile Number for Service Request</b>\n\n"
                    "Please reply with the phone number (e.g. <code>+919846000000</code> or <code>9846000000</code>):",
                )
            else:
                self.api.answer_callback_query(cb_id)
                prompt = (
                    "⚠️ <b>Confirm Action: Service Request Test Delivery</b>\n\n"
                    f"Are you sure you want to generate SR reports and send to:\n"
                    f"📱 <b>{target_val}</b>?"
                )
                kb = get_confirmation_keyboard(confirm_data=f"exec:sr_test_delivery:{target_val}", cancel_data="menu:sr")
                self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        if data == "action:sr_send_photos":
            self.api.answer_callback_query(cb_id)
            prompt = (
                "⚠️ <b>Confirm Action: Send Service Request Report Cards Here</b>\n\n"
                "Are you sure you want to send the latest Service Request pending report cards into this chat?"
            )
            kb = get_confirmation_keyboard(confirm_data="exec:sr_send_photos", cancel_data="menu:sr")
            self.api.edit_message_text(chat_id, message_id, prompt, reply_markup=kb)
            return

        # 3. Confirmed Executions (exec:*)
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

        if data == "exec:dispatch_groups":
            self.api.answer_callback_query(cb_id, text="Confirmed. Triggering group dispatch...")
            self.execute_group_dispatch_async(chat_id, message_id)
            return

        if data.startswith("exec:test_delivery:"):
            target_phone = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text=f"Confirmed. Sending to {target_phone}...")
            self.execute_test_delivery_async(chat_id, target_phone, message_id)
            return

        if data == "exec:send_photos":
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering photos...")
            self.send_report_photos_async(chat_id, message_id)
            return

        if data == "exec:sr_dispatch":
            self.api.answer_callback_query(cb_id, text="Confirmed. Triggering SR dispatch...")
            self.execute_sr_dispatch_async(chat_id, message_id)
            return

        if data.startswith("exec:sr_test_delivery:"):
            target_phone = data.split(":", 2)[2]
            self.api.answer_callback_query(cb_id, text=f"Confirmed. Sending SR report to {target_phone}...")
            self.execute_sr_test_delivery_async(chat_id, target_phone, message_id)
            return

        if data == "exec:sr_send_photos":
            self.api.answer_callback_query(cb_id, text="Confirmed. Delivering SR cards...")
            self.send_sr_report_photos_async(chat_id, message_id)
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
            notice = f"{res_icon} <b>{msg}</b>\n\n" + format_status_message(st)
            kb = get_main_menu_keyboard(st["is_active"])

            if message_id:
                self.api.edit_message_text(chat_id, message_id, notice, reply_markup=kb)
            else:
                self.api.send_message(chat_id, notice, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_group_dispatch_async(self, chat_id: int, message_id: Optional[int]):
        def worker():
            status_text = (
                "⏳ <b>Automated Complaint Pipeline Running</b>\n\n"
                "• Downloading latest tickets from Softcode & SMS portals...\n"
                "• Computing complaint summary tables...\n"
                "• Rendering High-DPI Retina report cards...\n"
                "• Dispatching to configured WhatsApp Groups & ACSO contacts..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                sent = self.api.send_message(chat_id, status_text)
                target_msg_id = sent.get("result", {}).get("message_id")

            ok, res_msg = trigger_group_dispatch("thrissur")
            st = get_service_status()
            kb = get_main_menu_keyboard(st["is_active"])

            if ok:
                finish_text = (
                    "✅ <b>Report-to-Group Dispatch Complete!</b>\n\n"
                    f"<i>{res_msg}</i>\n\n"
                    f"{format_status_message(st)}"
                )
            else:
                finish_text = (
                    "❌ <b>Group Dispatch Error</b>\n\n"
                    f"<code>{res_msg}</code>\n\n"
                    f"{format_status_message(st)}"
                )

            if message_id:
                self.api.edit_message_text(chat_id, message_id, finish_text, reply_markup=kb)
            else:
                self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_test_delivery_async(
        self, chat_id: int, target_phone: str, message_id: Optional[int] = None
    ):
        def worker():
            status_text = (
                f"⏳ <b>Generating & Sending Test Delivery</b>\n\n"
                f"• Target Number: <code>{target_phone}</code>\n"
                "• Downloading latest CRM complaints...\n"
                "• Rendering high-resolution Retina cards...\n"
                "• Dispatching via WhatsApp Web..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            ok, res_msg = trigger_test_delivery(target_phone, "thrissur")
            st = get_service_status()
            kb = get_main_menu_keyboard(st["is_active"])

            if ok:
                finish_text = (
                    f"✅ <b>Test Delivery Succeeded!</b>\n\n"
                    f"Reports sent to: <code>{target_phone}</code>\n"
                    f"<i>{res_msg}</i>\n\n"
                    f"{format_status_message(st)}"
                )
            else:
                finish_text = (
                    f"❌ <b>Test Delivery Failed</b>\n\n"
                    f"Target: <code>{target_phone}</code>\n"
                    f"Error: <code>{res_msg}</code>\n\n"
                    f"{format_status_message(st)}"
                )

            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def send_report_photos_async(self, chat_id: int, message_id: Optional[int] = None):
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
            ]
            sent_count = 0
            for title, path in cards:
                if path.exists():
                    self.api.send_photo(chat_id, path, caption=f"📊 <b>{title}</b>")
                    sent_count += 1
                    time.sleep(1)

            if sent_count == 0:
                self.api.send_message(
                    chat_id,
                    "⚠️ No report images found in <code>output/</code> directory. Click 'Report-to-Group Dispatch Rules' or 'Test Delivery' to generate fresh reports.",
                )
            else:
                self.send_main_menu(chat_id)

        threading.Thread(target=worker, daemon=True).start()

    def execute_sr_dispatch_async(self, chat_id: int, message_id: Optional[int] = None):
        def worker():
            status_text = (
                "⏳ <b>Service Request Pending Pipeline Running</b>\n\n"
                "• Parsing raw Service Request workbooks...\n"
                "• Computing ACSO-wise pending days summary...\n"
                "• Rendering High-DPI Retina report cards...\n"
                "• Dispatching to configured WhatsApp Groups & ACSO contacts..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            ok, res_msg = trigger_sr_dispatch("thrissur")
            kb = get_sr_menu_keyboard()

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

            if message_id:
                self.api.edit_message_text(chat_id, message_id, finish_text, reply_markup=kb)
            else:
                self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def execute_sr_test_delivery_async(
        self, chat_id: int, target_phone: str, message_id: Optional[int] = None
    ):
        def worker():
            status_text = (
                f"⏳ <b>Generating & Sending Service Request Test Delivery</b>\n\n"
                f"• Target Number: <code>{target_phone}</code>\n"
                "• Reading Service Request ticket ledger...\n"
                "• Rendering high-resolution ACSO report cards...\n"
                "• Dispatching via WhatsApp Web..."
            )
            if message_id:
                self.api.edit_message_text(chat_id, message_id, status_text)
            else:
                self.api.send_message(chat_id, status_text)

            ok, res_msg = trigger_sr_test_delivery(target_phone, "thrissur")
            kb = get_sr_menu_keyboard()

            if ok:
                finish_text = (
                    f"✅ <b>Service Request Test Delivery Succeeded!</b>\n\n"
                    f"Reports sent to: <code>{target_phone}</code>\n"
                    f"<i>{res_msg}</i>"
                )
            else:
                finish_text = (
                    f"❌ <b>Service Request Test Delivery Failed</b>\n\n"
                    f"Target: <code>{target_phone}</code>\n"
                    f"Error: <code>{res_msg}</code>"
                )

            self.api.send_message(chat_id, finish_text, reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()

    def send_sr_report_photos_async(self, chat_id: int, message_id: Optional[int] = None):
        def worker():
            if message_id:
                self.api.edit_message_text(
                    chat_id,
                    message_id,
                    "⏳ <b>Delivering High-DPI SR Report Cards to Telegram...</b>\nPlease wait a moment.",
                )
            cards = [
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

            kb = get_sr_menu_keyboard()
            if sent_count == 0:
                self.api.send_message(
                    chat_id,
                    "⚠️ No SR report images found in <code>output/</code> directory. Run SR dispatch or generate reports to create fresh cards.",
                    reply_markup=kb,
                )
            else:
                self.api.send_message(chat_id, "📋 <b>Service Request Menu:</b>", reply_markup=kb)

        threading.Thread(target=worker, daemon=True).start()


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
