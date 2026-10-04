"""
web_server.py
=============
FastAPI backend server for the Asianet Kerala Regional Network Operations Manager.
Enables adding, removing, and editing:
  - Center Names
  - Team Leader Names
  - ACSO Names
  - Employee Codes
Region-by-region across all 14 Kerala districts.
Provides live mathematical parity testing, high-definition report generation, and WhatsApp dispatch.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import asyncio
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import pandas as pd

from config import (
    BASE_DIR,
    OUTPUT_DIR,
    TARGET_EXCEL_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
)
import db_manager
from report_engine import compute_report, load_inputs_from_workbook
from report_image_generator import generate_report_images, generate_acso_report_images
from whatsapp_sender import flash_report_image
from data_processor import filter_adl, filter_adtv, filter_prepaid, write_working_copy
from crm_downloader import download_from_crm
import whatsapp_auth_manager
import logger_setup

# Initialize dual-stream 3-day rotating logging
logger_setup.init_logging()

app = FastAPI(
    title="Asianet Kerala Network Tracker - Regional Operations Manager",
    description="Multi-region configuration manager, calculation engine, and report dispatcher.",
    version="1.0.0"
)

# Mount Output directory for rendered report images
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR.resolve())), name="output")

TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR.resolve()))


# --- Pydantic Request Models ---

class RegionCreate(BaseModel):
    id: str
    name: str
    softcode_region: str
    prepaid_region: str


class TeamLeaderPayload(BaseModel):
    center_name: str
    name: str
    pd_adl_name_key: Optional[str] = ""
    pd_adtv_name_key: Optional[str] = ""
    pp_adl_emp_code: Optional[str] = ""
    adtv_center: Optional[str] = ""
    adtv_name: Optional[str] = ""
    sort_order: Optional[int] = 0


class AcsoPayload(BaseModel):
    center_name: str
    acso_name: str
    adtv_acso_name: Optional[str] = ""
    pd_adl_center_key: Optional[str] = ""
    pd_adtv_center_key: Optional[str] = ""
    pp_adl_center_key: Optional[str] = ""
    pp_adtv_center_key: Optional[str] = ""
    adl_center_display: Optional[str] = ""
    adtv_center_display: Optional[str] = ""
    sort_order: Optional[int] = 0


class EmployeePayload(BaseModel):
    emp_code: str
    name: str
    role: Optional[str] = "Technician"
    center_name: Optional[str] = ""
    phone: Optional[str] = ""


class DispatchRulePayload(BaseModel):
    rule_name: str
    report_type: str
    target_recipients: str
    description: Optional[str] = ""
    region_id: Optional[str] = "thrissur"
    is_enabled: Optional[bool] = True


class ScheduleTimePayload(BaseModel):
    run_time: str
    label: Optional[str] = ""
    region_id: Optional[str] = "thrissur"
    is_enabled: Optional[bool] = True


class GenerateAndSendPayload(BaseModel):
    target_phone: str
    report_type: Optional[str] = "all"


class CycleRunPayload(BaseModel):
    region_id: Optional[str] = "thrissur"


# --- Frontend View Route ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Renders the main operational management interface."""
    html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# --- Region Management Endpoints ---

@app.get("/api/regions")
async def list_regions():
    """Returns all 14 Kerala regions with their operational counts."""
    return db_manager.get_all_regions()


@app.post("/api/regions")
async def create_region(payload: RegionCreate):
    """Creates a new region."""
    success = db_manager.add_region(
        payload.id,
        payload.name,
        payload.softcode_region,
        payload.prepaid_region
    )
    if not success:
        raise HTTPException(status_code=400, detail="Region ID already exists.")
    return {"status": "OK", "message": f"Region '{payload.name}' created"}


@app.delete("/api/regions/{region_id}")
async def remove_region(region_id: str):
    """Deletes a region (except Thrissur master baseline)."""
    if region_id.lower() == "thrissur":
        raise HTTPException(status_code=400, detail="Cannot delete baseline Thrissur region.")
    success = db_manager.delete_region(region_id)
    if not success:
        raise HTTPException(status_code=404, detail="Region not found.")
    return {"status": "OK", "message": f"Region '{region_id}' deleted"}


@app.get("/api/regions/{region_id}/config")
async def get_region_config(region_id: str):
    """Fetches all Team Leaders, ACSOs, Centers, and Employees for a region."""
    reg = db_manager.get_region_by_id(region_id)
    if not reg:
        raise HTTPException(status_code=404, detail=f"Region '{region_id}' not found.")
    return {
        "region": reg,
        "tls": db_manager.get_team_leaders(region_id),
        "acsos": db_manager.get_acsos(region_id),
        "centers": db_manager.get_centers(region_id),
        "emps": db_manager.get_employees(region_id),
    }


# --- Team Leader CRUD ---

@app.post("/api/regions/{region_id}/team-leaders")
async def create_team_leader(region_id: str, payload: TeamLeaderPayload):
    """Adds a new Team Leader to the specified region."""
    tl_id = db_manager.add_team_leader(region_id, payload.dict())
    return {"status": "OK", "id": tl_id}


@app.put("/api/regions/{region_id}/team-leaders/{tl_id}")
async def modify_team_leader(region_id: str, tl_id: int, payload: TeamLeaderPayload):
    """Updates an existing Team Leader."""
    db_manager.update_team_leader(tl_id, payload.dict())
    return {"status": "OK", "id": tl_id}


@app.delete("/api/regions/{region_id}/team-leaders/{tl_id}")
async def remove_team_leader(region_id: str, tl_id: int):
    """Removes a Team Leader."""
    db_manager.delete_team_leader(tl_id)
    return {"status": "OK"}


# --- ACSO / Center CRUD ---

@app.post("/api/regions/{region_id}/acsos")
async def create_acso(region_id: str, payload: AcsoPayload):
    """Adds a Center and ACSO Officer to the specified region."""
    acso_id = db_manager.add_acso(region_id, payload.dict())
    # Also record in centers table if needed
    db_manager.add_center(region_id, {
        "center_name": payload.center_name,
        "adl_area_key": payload.pd_adl_center_key or payload.center_name,
        "adtv_amo_key": payload.pd_adtv_center_key or payload.center_name,
        "prepaid_area_key": payload.pp_adl_center_key or payload.center_name,
        "sort_order": payload.sort_order or 0
    })
    return {"status": "OK", "id": acso_id}


@app.put("/api/regions/{region_id}/acsos/{acso_id}")
async def modify_acso(region_id: str, acso_id: int, payload: AcsoPayload):
    """Updates an existing ACSO Officer and Center mapping."""
    db_manager.update_acso(acso_id, payload.dict())
    return {"status": "OK", "id": acso_id}


@app.delete("/api/regions/{region_id}/acsos/{acso_id}")
async def remove_acso(region_id: str, acso_id: int):
    """Removes an ACSO Officer and Center."""
    db_manager.delete_acso(acso_id)
    return {"status": "OK"}


# --- Employee Directory CRUD ---

@app.post("/api/regions/{region_id}/employees")
async def create_employee(region_id: str, payload: EmployeePayload):
    """Registers an employee code and staff profile."""
    emp_id = db_manager.add_employee(region_id, payload.dict())
    return {"status": "OK", "id": emp_id}


@app.put("/api/regions/{region_id}/employees/{emp_id}")
async def modify_employee(region_id: str, emp_id: int, payload: EmployeePayload):
    """Updates an employee profile."""
    db_manager.update_employee(emp_id, payload.dict())
    return {"status": "OK", "id": emp_id}


@app.delete("/api/regions/{region_id}/employees/{emp_id}")
async def remove_employee(region_id: str, emp_id: int):
    """Deletes an employee record."""
    db_manager.delete_employee(emp_id)
    return {"status": "OK"}


# --- Live Engine & Report Operations ---

@app.get("/api/regions/{region_id}/test-engine")
def test_calculation_engine(region_id: str):
    """
    Executes pure-Python mathematical computation using dynamic region configuration
    against loaded CRM sheets.
    """
    try:
        df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

        adl_postpaid = result.pending_days["adl_acso"].total.grand_total if result.pending_days["adl_acso"].total else sum(r.grand_total for r in result.pending_days["adl_acso"].rows)
        adl_prepaid = result.prepaid_pending["adl_acso"].total.grand_total if result.prepaid_pending["adl_acso"].total else sum(r.grand_total for r in result.prepaid_pending["adl_acso"].rows)
        adl_total = result.final["adl_acso"].total.grand_total if result.final["adl_acso"].total else sum(r.grand_total for r in result.final["adl_acso"].rows)

        adtv_postpaid = result.pending_days["adtv_acso"].total.grand_total if result.pending_days["adtv_acso"].total else sum(r.grand_total for r in result.pending_days["adtv_acso"].rows)
        adtv_prepaid = result.prepaid_pending["adtv_acso"].total.grand_total if result.prepaid_pending["adtv_acso"].total else sum(r.grand_total for r in result.prepaid_pending["adtv_acso"].rows)
        adtv_total = result.final["adtv_acso"].total.grand_total if result.final["adtv_acso"].total else sum(r.grand_total for r in result.final["adtv_acso"].rows)

        return {
            "status": "PASS",
            "region": region_id,
            "adl_total": adl_total,
            "adl_postpaid": adl_postpaid,
            "adl_prepaid": adl_prepaid,
            "adtv_total": adtv_total,
            "adtv_postpaid": adtv_postpaid,
            "adtv_prepaid": adtv_prepaid,
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "message": str(e)
        }


@app.post("/api/regions/{region_id}/generate-reports")
def generate_reports(region_id: str):
    """
    Computes report for the region and renders high-definition Retina JPEG images
    (Team Leader tables and ACSO tables) using Playwright.
    """
    try:
        df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }

        # Generate Team Leader images
        generate_report_images(df_sections)
        # Generate ACSO images
        generate_acso_report_images(df_sections)

        return {
            "status": "OK",
            "message": "All reports rendered successfully",
            "images": [
                "/output/ADL_Complaint_Pending.jpg",
                "/output/ADTv_Complaint_Pending.jpg",
                "/output/ADL_ACSO_Complaint_Pending.jpg",
                "/output/ADTv_ACSO_Complaint_Pending.jpg",
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/regions/{region_id}/dispatch-whatsapp")
def dispatch_whatsapp(region_id: str):
    """
    Sends the 4 standalone high-definition report cards directly to WhatsApp
    configured for this region, or operator fallback.
    """
    try:
        images = [
            ADL_REPORT_IMAGE_PATH,
            ADTV_REPORT_IMAGE_PATH,
            ADL_ACSO_REPORT_IMAGE_PATH,
            ADTV_ACSO_REPORT_IMAGE_PATH,
        ]

        # Verify images exist, or render if missing
        missing = [img for img in images if not img.exists()]
        if missing:
            df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)
            result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)
            df_sections = {
                "adl_team": result.final["adl_team"].to_frame(),
                "adtv_team": result.final["adtv_team"].to_frame(),
                "adl_acso": result.final["adl_acso"].to_frame(),
                "adtv_acso": result.final["adtv_acso"].to_frame(),
            }
            generate_report_images(df_sections)
            generate_acso_report_images(df_sections)

        # Collect target recipients from active dispatch rules for this region
        rules = db_manager.get_dispatch_rules(region_id)
        targets: List[str] = []
        for r in rules:
            if r.get("is_enabled", 1):
                for t in str(r.get("target_recipients", "")).split(","):
                    clean = t.strip()
                    if clean and clean not in targets:
                        targets.append(clean)

        # Validate that targets are configured
        if not targets:
            raise HTTPException(
                status_code=400,
                detail="No target WhatsApp groups or phone numbers are configured in active dispatch rules. Please configure target recipients in the Auto Schedule & Routing tab."
            )

        success = flash_report_image(images, target_recipients=targets)
        if success:
            return {"status": "OK", "message": f"All 4 report cards dispatched to {', '.join(targets)}"}
        else:
            raise HTTPException(status_code=500, detail="WhatsApp dispatcher failed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/regions/{region_id}/generate-and-send")
def generate_and_send_now(region_id: str, payload: GenerateAndSendPayload):
    """
    Pulls fresh tickets from CRM, computes report, renders high-DPI cards,
    and sends them to the specified phone number to test reports are generating properly.
    """
    target = payload.target_phone.strip()
    if not target:
        raise HTTPException(status_code=400, detail="Target phone number is required")

    try:
        # 1. Download latest CRM tickets
        try:
            adl_path, adtv_path, prep_path = download_from_crm(region=region_id, headless=True)
            raw_adl = pd.read_excel(adl_path)
            raw_adtv = pd.read_excel(adtv_path)
            raw_prep = pd.read_csv(prep_path) if str(prep_path).endswith(".csv") else pd.read_excel(prep_path)
            df_adl = filter_adl(raw_adl, region=region_id)
            df_adtv = filter_adtv(raw_adtv, region=region_id)
            df_prepaid = filter_prepaid(raw_prep, region=region_id)
        except Exception as e_dl:
            print(f"[Generate & Send] Online download fallback: {e_dl}")
            df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)

        # 2. Compute report
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

        # 3. Render High-DPI images
        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }
        generate_report_images(df_sections)
        generate_acso_report_images(df_sections)

        # 4. Save working copy
        try:
            write_working_copy(df_adl, df_adtv, df_prepaid, template_path=TARGET_EXCEL_PATH)
        except Exception:
            pass

        # 5. Dispatch to the specified number
        imgs = get_images_for_report_type(payload.report_type or "all")
        success = flash_report_image(imgs, target_recipients=[target])
        if success:
            return {"status": "OK", "message": f"Reports generated & sent to {target} successfully!"}
        else:
            raise HTTPException(status_code=500, detail="WhatsApp delivery failed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Report Type Image Helper ---

def get_images_for_report_type(report_type: str) -> List[Path]:
    if report_type == "adl_tl":
        return [ADL_REPORT_IMAGE_PATH]
    elif report_type == "adtv_tl":
        return [ADTV_REPORT_IMAGE_PATH]
    elif report_type == "adl_acso":
        return [ADL_ACSO_REPORT_IMAGE_PATH]
    elif report_type == "adtv_acso":
        return [ADTV_ACSO_REPORT_IMAGE_PATH]
    elif report_type == "all":
        return [
            ADL_REPORT_IMAGE_PATH,
            ADTV_REPORT_IMAGE_PATH,
            ADL_ACSO_REPORT_IMAGE_PATH,
            ADTV_ACSO_REPORT_IMAGE_PATH,
        ]
    return [ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH]


def execute_automated_cycle(region_id: str = "thrissur") -> Dict[str, Any]:
    """Pulls fresh tickets from CRM, computes report, renders images, and dispatches per rules."""
    ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        adl_path, adtv_path, prep_path = download_from_crm(region=region_id, headless=True)
        raw_adl = pd.read_excel(adl_path)
        raw_adtv = pd.read_excel(adtv_path)
        raw_prep = pd.read_csv(prep_path) if str(prep_path).endswith(".csv") else pd.read_excel(prep_path)

        df_adl = filter_adl(raw_adl, region=region_id)
        df_adtv = filter_adtv(raw_adtv, region=region_id)
        df_prepaid = filter_prepaid(raw_prep, region=region_id)

        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }
        generate_report_images(df_sections)
        generate_acso_report_images(df_sections)

        write_working_copy(df_adl, df_adtv, df_prepaid, template_path=TARGET_EXCEL_PATH)

        # Dispatch according to active rules
        rules = db_manager.get_dispatch_rules(region_id)
        dispatched_count = 0
        for r in rules:
            if not r.get("is_enabled", 1):
                continue
            targets = [t.strip() for t in r.get("target_recipients", "").split(",") if t.strip()]
            if not targets:
                continue
            report_type = r.get("report_type", "all")
            imgs = get_images_for_report_type(report_type)
            flash_report_image(imgs, target_recipients=targets)
            dispatched_count += 1

        status_msg = f"Completed at {ts_now}. Dispatched {dispatched_count} active rule(s)."
        db_manager.set_setting("last_cycle_timestamp", ts_now)
        db_manager.set_setting("last_cycle_status", status_msg)
        return {"status": "OK", "message": status_msg, "dispatched_rules": dispatched_count}
    except Exception as e:
        err_msg = f"Failed at {ts_now}: {e}"
        db_manager.set_setting("last_cycle_timestamp", ts_now)
        db_manager.set_setting("last_cycle_status", err_msg)
        return {"status": "ERROR", "message": err_msg}


# --- Dispatch Rules Endpoints ---

@app.get("/api/regions/{region_id}/dispatch-rules")
def list_dispatch_rules(region_id: str):
    return db_manager.get_dispatch_rules(region_id)


@app.post("/api/regions/{region_id}/dispatch-rules")
def create_dispatch_rule(region_id: str, payload: DispatchRulePayload):
    data = payload.dict()
    data["region_id"] = region_id
    rid = db_manager.add_dispatch_rule(data)
    return {"status": "OK", "id": rid}


@app.put("/api/dispatch-rules/{rule_id}")
def update_dispatch_rule_endpoint(rule_id: int, payload: DispatchRulePayload):
    db_manager.update_dispatch_rule(rule_id, payload.dict())
    return {"status": "OK"}


@app.delete("/api/dispatch-rules/{rule_id}")
def delete_dispatch_rule_endpoint(rule_id: int):
    db_manager.delete_dispatch_rule(rule_id)
    return {"status": "OK"}


@app.post("/api/dispatch-rules/{rule_id}/toggle")
def toggle_dispatch_rule_endpoint(rule_id: int):
    db_manager.toggle_dispatch_rule(rule_id)
    return {"status": "OK"}


@app.post("/api/dispatch-rules/{rule_id}/trigger")
def trigger_dispatch_rule_endpoint(rule_id: int):
    rules = db_manager.get_dispatch_rules()
    rule = next((r for r in rules if r["id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Dispatch rule not found")
    targets = [t.strip() for t in (rule.get("target_recipients") or "").split(",") if t.strip()]
    if not targets:
        raise HTTPException(
            status_code=400,
            detail=f"No target recipients defined for rule '{rule.get('rule_name', 'Rule')}'. Please click 'Edit' to configure WhatsApp groups or phone numbers."
        )
    imgs = get_images_for_report_type(rule["report_type"])
    missing = [i for i in imgs if not i.exists()]
    if missing:
        df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=rule["region_id"])
        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }
        generate_report_images(df_sections)
        generate_acso_report_images(df_sections)

    success = flash_report_image(imgs, target_recipients=targets)
    if success:
        return {"status": "OK", "message": f"Successfully sent '{rule['rule_name']}' to {len(targets)} recipient(s)"}
    raise HTTPException(status_code=500, detail="WhatsApp dispatch failed or profile is busy. Please wait a few seconds and try again.")


# --- Schedule Times Endpoints ---

@app.get("/api/regions/{region_id}/schedule-times")
def list_schedule_times(region_id: str):
    return db_manager.get_schedule_times(region_id)


@app.post("/api/regions/{region_id}/schedule-times")
def create_schedule_time(region_id: str, payload: ScheduleTimePayload):
    sid = db_manager.add_schedule_time(region_id, payload.run_time, payload.label or "")
    return {"status": "OK", "id": sid}


@app.put("/api/schedule-times/{time_id}")
def update_schedule_time_endpoint(time_id: int, payload: ScheduleTimePayload):
    db_manager.update_schedule_time(time_id, payload.run_time, payload.label or "", 1 if payload.is_enabled else 0)
    return {"status": "OK"}


@app.delete("/api/schedule-times/{time_id}")
def delete_schedule_time_endpoint(time_id: int):
    db_manager.delete_schedule_time(time_id)
    return {"status": "OK"}


@app.post("/api/schedule-times/{time_id}/toggle")
def toggle_schedule_time_endpoint(time_id: int):
    db_manager.toggle_schedule_time(time_id)
    return {"status": "OK"}


# --- System & Automation Status Endpoints ---

@app.get("/api/system/settings")
def get_system_settings():
    return {
        "scheduler_enabled": db_manager.get_setting("scheduler_enabled", "1") == "1",
        "last_cycle_timestamp": db_manager.get_setting("last_cycle_timestamp", "Not yet executed"),
        "last_cycle_status": db_manager.get_setting("last_cycle_status", "Scheduler Ready"),
    }


@app.post("/api/system/scheduler-toggle")
def toggle_master_scheduler():
    current = db_manager.get_setting("scheduler_enabled", "1")
    new_val = "0" if current == "1" else "1"
    db_manager.set_setting("scheduler_enabled", new_val)
    return {"status": "OK", "scheduler_enabled": new_val == "1"}


@app.post("/api/system/run-automated-cycle-now")
def run_automated_cycle_now(payload: Optional[CycleRunPayload] = None, region_id: Optional[str] = None):
    target_region = "thrissur"
    if payload and payload.region_id:
        target_region = payload.region_id
    elif region_id:
        target_region = region_id
    return execute_automated_cycle(target_region)


# --- WhatsApp Web Session & Authentication Endpoints ---

@app.get("/api/whatsapp/status")
def get_whatsapp_auth_status():
    """Returns current WhatsApp Web login and QR scan state."""
    return whatsapp_auth_manager.get_whatsapp_status()


@app.post("/api/whatsapp/start-login")
def start_whatsapp_login():
    """Launches background Chromium to fetch WhatsApp Web QR code."""
    return whatsapp_auth_manager.start_login_flow()


@app.post("/api/whatsapp/cancel-login")
def cancel_whatsapp_login():
    """Cancels active QR scan browser session."""
    return whatsapp_auth_manager.cancel_login()


@app.post("/api/whatsapp/logout")
def logout_whatsapp_session():
    """Wipes WhatsApp Web profile and session cache to allow pairing a new phone."""
    return whatsapp_auth_manager.logout_session()


# --- Logs & System Diagnostics Endpoints ---

@app.get("/api/logs/files")
def api_get_log_files():
    """Returns list of all available running and error log files in logs/ directory."""
    return logger_setup.get_log_files()


@app.get("/api/logs/view")
def api_view_log(file: Optional[str] = None, type: str = "running", lines: int = 300):
    """Returns tail content of a specific log file or today's default log."""
    safe_lines = min(max(lines, 10), 2000)
    return logger_setup.read_log_file(file_name=file, log_type=type, max_lines=safe_lines)


@app.get("/api/logs/analysis")
def api_analyze_logs(days: int = 3):
    """Performs deep log diagnostic analysis, health score calculation, and issue categorization."""
    safe_days = min(max(days, 1), 7)
    return logger_setup.analyze_system_logs(days=safe_days)


@app.post("/api/logs/cleanup")
def api_cleanup_logs(days: int = 3):
    """Purges log files older than N days (default 3 days)."""
    safe_days = min(max(days, 1), 30)
    deleted = logger_setup.cleanup_old_logs(retention_days=safe_days)
    return {"status": "OK", "deleted_files": deleted, "count": len(deleted)}


# --- Background Scheduler Loop ---

async def background_scheduler_loop():
    while True:
        try:
            await asyncio.sleep(25)
            if db_manager.get_setting("scheduler_enabled", "1") != "1":
                continue
            now = datetime.now()
            current_hh_mm = now.strftime("%H:%M")
            today_date = now.strftime("%Y-%m-%d")

            schedule_slots = db_manager.get_schedule_times()
            for slot in schedule_slots:
                if not slot.get("is_enabled", 1):
                    continue
                if slot.get("run_time") == current_hh_mm:
                    last_run = slot.get("last_run") or ""
                    if not last_run.startswith(today_date):
                        print(f"\n[Scheduler] Auto-triggering report generation for region '{slot['region_id']}' at {current_hh_mm}...")
                        db_manager.update_last_run(slot["id"])
                        await asyncio.to_thread(execute_automated_cycle, slot["region_id"])
        except Exception as e:
            print(f"[Scheduler Loop Error] {e}")


@app.on_event("startup")
async def start_scheduler_task():
    asyncio.create_task(background_scheduler_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_server:app", host="127.0.0.1", port=8201, reload=True)

