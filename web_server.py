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
import secrets

import json
from io import BytesIO

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import pandas as pd

from config import (
    BASE_DIR,
    OUTPUT_DIR,
    TARGET_EXCEL_PATH,
    resolve_target_excel_path,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
    ADL_SR_REPORT_IMAGE_PATH,
    ADTV_SR_REPORT_IMAGE_PATH,
    SR_REPORT_IMAGE_PATH,
    SR_EXCEL_REPORT_PATH,
    WEB_API_TOKEN,
    DEFAULT_REGION_ID,
)
import db_manager
from report_engine import compute_report, load_inputs_from_workbook
from report_image_generator import generate_report_images, generate_acso_report_images
from whatsapp_sender import flash_report_image
from data_processor import filter_adl, filter_adtv, filter_prepaid, write_working_copy
from crm_downloader import download_from_crm
import whatsapp_auth_manager
import logger_setup
from service_request_engine import (
    compute_service_request_reports,
    create_excel_output as create_sr_excel_output,
    render_sr_report_images,
    execute_automated_sr_cycle,
    is_sr_report_type,
)

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
    phone: Optional[str] = ""
    email: Optional[str] = ""
    crm_name: Optional[str] = ""
    emp_code: Optional[str] = ""
    sort_order: Optional[int] = 0


class EmployeePayload(BaseModel):
    emp_code: str
    name: str
    role: Optional[str] = "Technician"
    center_name: Optional[str] = ""
    phone: Optional[str] = ""


class DirectoryRowPayload(BaseModel):
    emp_code: Optional[str] = ""
    emp_name: str
    position: Optional[str] = "Team Leader"
    phone: Optional[str] = ""
    email: Optional[str] = ""
    center_name: str
    crm_name: Optional[str] = ""
    adl_center: Optional[str] = ""
    adtv_center: Optional[str] = ""
    prepaid_center: Optional[str] = ""
    entry_type: Optional[str] = "tl"


class BulkDeleteDirectoryPayload(BaseModel):
    items: List[Dict[str, Any]]


class DispatchRulePayload(BaseModel):
    rule_name: str
    report_type: str
    target_recipients: str
    description: Optional[str] = ""
    region_id: Optional[str] = DEFAULT_REGION_ID
    is_enabled: Optional[bool] = True


class ScheduleTimePayload(BaseModel):
    run_time: str
    label: Optional[str] = ""
    region_id: Optional[str] = DEFAULT_REGION_ID
    is_enabled: Optional[bool] = True
    report_type: Optional[str] = "complaint"



class GenerateAndSendPayload(BaseModel):
    target_phone: str
    report_type: Optional[str] = "all"


class CycleRunPayload(BaseModel):
    region_id: Optional[str] = DEFAULT_REGION_ID
    pipeline: Optional[str] = "all"  # 'complaint', 'service_request', or 'all'


class ApiLoginPayload(BaseModel):
    token: str


@app.middleware("http")
async def add_no_cache_api_headers(request: Request, call_next):
    protected_path = request.url.path.startswith("/api/") or request.url.path.startswith("/output/")
    if protected_path and request.url.path != "/api/auth/login":
        supplied = request.headers.get("Authorization", "")
        bearer = supplied[7:].strip() if supplied.lower().startswith("bearer ") else ""
        cookie_token = request.cookies.get("dwr_api_token", "")
        if not WEB_API_TOKEN or not (secrets.compare_digest(bearer, WEB_API_TOKEN) or secrets.compare_digest(cookie_token, WEB_API_TOKEN)):
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.post("/api/auth/login")
def api_login(payload: ApiLoginPayload, response: Response):
    if not WEB_API_TOKEN or not secrets.compare_digest(payload.token.strip(), WEB_API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid API token.")
    response.set_cookie("dwr_api_token", WEB_API_TOKEN, httponly=True, samesite="lax", secure=False, max_age=86400)
    return {"status": "OK"}


# --- Frontend View Route ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Renders the main operational management interface."""
    html_path = TEMPLATES_DIR / "index.html"
    html = html_path.read_text(encoding="utf-8").replace("__DEFAULT_REGION_ID__", DEFAULT_REGION_ID)
    response = HTMLResponse(content=html)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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
    db_manager.update_team_leader(tl_id, payload.dict(), region_id=region_id)
    return {"status": "OK", "id": tl_id}


@app.delete("/api/regions/{region_id}/team-leaders/{tl_id}")
async def remove_team_leader(region_id: str, tl_id: int):
    """Removes a Team Leader."""
    db_manager.delete_team_leader(tl_id, region_id=region_id)
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
    db_manager.update_acso(acso_id, payload.dict(), region_id=region_id)
    return {"status": "OK", "id": acso_id}


@app.delete("/api/regions/{region_id}/acsos/{acso_id}")
async def remove_acso(region_id: str, acso_id: int):
    """Removes an ACSO Officer and Center."""
    db_manager.delete_acso(acso_id, region_id=region_id)
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
    db_manager.update_employee(emp_id, payload.dict(), region_id=region_id)
    return {"status": "OK", "id": emp_id}


@app.delete("/api/regions/{region_id}/employees/{emp_id}")
async def remove_employee(region_id: str, emp_id: int):
    """Deletes an employee record."""
    db_manager.delete_employee(emp_id, region_id=region_id)
    return {"status": "OK"}


# --- Unified Employee Directory Endpoints (7-Column Format) ---

@app.get("/api/regions/{region_id}/directory")
def get_region_directory_endpoint(region_id: str):
    """Fetches the unified employee directory in the 7-column schema."""
    return db_manager.get_unified_directory(region_id)


@app.post("/api/regions/{region_id}/directory")
def add_directory_entry_endpoint(region_id: str, payload: DirectoryRowPayload):
    """Adds a single employee directory entry."""
    row_id = db_manager.add_unified_directory_row(region_id, payload.dict())
    return {"status": "OK", "id": row_id}


@app.put("/api/regions/{region_id}/directory/{row_id}")
def update_directory_entry_endpoint(region_id: str, row_id: int, payload: DirectoryRowPayload):
    """Updates a single employee directory entry."""
    db_manager.update_unified_directory_row(row_id, payload.dict(), region_id=region_id)
    return {"status": "OK", "id": row_id}


@app.delete("/api/regions/{region_id}/directory/{row_id}")
def delete_directory_entry_endpoint(region_id: str, row_id: int, entry_type: Optional[str] = "tl"):
    """Deletes an employee directory entry."""
    db_manager.delete_unified_directory_row(row_id, entry_type=entry_type, region_id=region_id)
    return {"status": "OK"}


@app.post("/api/regions/{region_id}/directory/bulk-delete")
def bulk_delete_directory_endpoint(region_id: str, payload: BulkDeleteDirectoryPayload):
    """Deletes multiple employee directory entries at once and synchronizes JSON."""
    count = db_manager.bulk_delete_unified_directory(payload.items, region_id=region_id)
    return {
        "status": "OK",
        "deleted_count": count,
        "message": f"Successfully deleted {count} employee(s)."
    }


@app.get("/api/regions/{region_id}/directory/export-json")
def export_directory_json_endpoint(region_id: str):
    """Exports and downloads the complete Employee Directory as a standalone JSON file."""
    path_str = db_manager.sync_directory_to_json(region_id)
    return FileResponse(
        path=path_str,
        filename=f"Employee_Directory_{region_id}.json",
        media_type="application/json"
    )


@app.get("/api/regions/{region_id}/directory/export-excel")
def export_directory_excel_endpoint(region_id: str):
    """
    Exports the complete populated Employee Directory for a region in the exact
    10-column Excel template format.
    """
    records = db_manager.get_unified_directory(region_id)

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employee Directory"

    headers = [
        "Emp Code",
        "Employee Display name",
        "Position",
        "Phone Number",
        "Gmail",
        "Center Display name",
        "Name in Postpaid CRM",
        "Center Name in Postpaid ADL",
        "Center Name in Postpaid ADTv",
        "Center name in Prepaid",
    ]
    ws.append(headers)

    # Professional header styling
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1'),
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # Populate rows
    for r in records:
        emp_code = r.get("emp_code") or ""
        emp_name = r.get("emp_name") or ""
        position = r.get("position") or ("ACSO" if "acso" in str(r.get("entry_type", "")).lower() else "Team Leader")
        phone = r.get("phone") or ""
        email = r.get("email") or ""
        center_name = r.get("center_name") or ""
        crm_name = r.get("crm_name") or emp_name
        adl_center = r.get("adl_center") or center_name
        adtv_center = r.get("adtv_center") or center_name
        prepaid_center = r.get("prepaid_center") or center_name

        ws.append([
            emp_code,
            emp_name,
            position,
            phone,
            email,
            center_name,
            crm_name,
            adl_center,
            adtv_center,
            prepaid_center,
        ])

    # Style data rows
    regular_font = Font(name="Calibri", size=10)
    for row in ws.iter_rows(min_row=2, max_row=max(ws.max_row, 2), min_col=1, max_col=len(headers)):
        for cell in row:
            cell.font = regular_font
            cell.border = thin_border
            if cell.column in (1, 3, 4):  # Emp Code, Position, Phone
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(vertical="center")

    # Set row height
    ws.row_dimensions[1].height = 28
    for row_idx in range(2, max(ws.max_row + 1, 3)):
        ws.row_dimensions[row_idx].height = 20

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    clean_reg = region_id.capitalize()
    filename = f"Employee_Directory_{clean_reg}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.post("/api/regions/{region_id}/directory/import-json")
def import_directory_json_endpoint(region_id: str, payload: List[Dict[str, Any]]):
    """Directly updates the Employee Directory from a JSON array payload."""
    result = db_manager.import_unified_directory(region_id, payload)
    return {
        "status": "OK",
        "message": f"Successfully imported {result.get('total_employees_imported', 0)} employees from JSON payload.",
        "details": result
    }


@app.get("/api/employee-directory/download-template")
def download_directory_template_endpoint(region_id: Optional[str] = DEFAULT_REGION_ID):
    """Downloads a clean, blank formatted Excel template for uploading the Employee Directory."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employee Directory"

    headers = [
        "Emp Code",
        "Employee Display name",
        "Position",
        "Phone Number",
        "Gmail",
        "Center Display name",
        "Name in Postpaid CRM",
        "Center Name in Postpaid ADL",
        "Center Name in Postpaid ADTv",
        "Center name in Prepaid",
    ]
    ws.append(headers)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1'),
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    ws.row_dimensions[1].height = 28

    column_widths = {
        'A': 14,  # Emp Code
        'B': 26,  # Employee Display name
        'C': 16,  # Position
        'D': 18,  # Phone Number
        'E': 26,  # Gmail
        'F': 22,  # Center Display name
        'G': 26,  # Name in Postpaid CRM
        'H': 26,  # Center Name in Postpaid ADL
        'I': 26,  # Center Name in Postpaid ADTv
        'J': 24,  # Center name in Prepaid
    }
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = "Employee_Directory_Blank_Template.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.post("/api/regions/{region_id}/upload-directory")
async def upload_directory_endpoint(region_id: str, file: UploadFile = File(...)):
    """Uploads and imports Excel, CSV, or JSON file into the Employee Directory database."""
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv", ".json")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls), CSV (.csv), and JSON (.json) files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        if file.filename.lower().endswith(".json"):
            records = json.loads(content.decode("utf-8"))
            if not isinstance(records, list):
                raise ValueError("JSON file must contain an array of employee directory objects.")
            result = db_manager.import_unified_directory(region_id, records)
            return {
                "status": "OK",
                "message": f"Successfully imported {result.get('total_employees_imported', 0)} personnel from JSON.",
                "details": result
            }
        elif file.filename.lower().endswith(".csv"):
            df = pd.read_csv(BytesIO(content))
        else:
            excel_file = pd.ExcelFile(BytesIO(content))
            lower_sheets = [str(s).lower() for s in excel_file.sheet_names]
            # Safety check: if user mistakenly uploaded the Daily Complaint workbook here
            if any("adl p" in s for s in lower_sheets) and any("adtv p" in s for s in lower_sheets):
                target_master = BASE_DIR / "Daily Complint Tracker.xls"
                target_master.write_bytes(content)
                alt_master = BASE_DIR / "Daily Complint pending Report.xls"
                try:
                    alt_master.write_bytes(content)
                except Exception:
                    pass
                return {
                    "status": "OK",
                    "message": f"Detected Daily Complaint workbook '{file.filename}'! Updated active complaints tracker.",
                    "details": {"type": "complaints_tracker"}
                }

            # Smart sheet detection: find Employee Directory sheet or search sheets for roster columns
            chosen_sheet = None
            for s in excel_file.sheet_names:
                s_low = str(s).lower()
                if any(w in s_low for w in ["employee", "directory", "staff", "roster", "personnel"]):
                    chosen_sheet = s
                    break

            if chosen_sheet is None:
                for s in excel_file.sheet_names:
                    try:
                        df_peek = pd.read_excel(excel_file, sheet_name=s, nrows=5)
                        cols_peek = " ".join(str(c).lower() for c in df_peek.columns)
                        if any(k in cols_peek for k in ["name", "code", "center", "position", "emp", "role", "tl"]):
                            chosen_sheet = s
                            break
                    except Exception:
                        continue

            if chosen_sheet is None:
                chosen_sheet = excel_file.sheet_names[0] if len(excel_file.sheet_names) > 0 else 0

            df = pd.read_excel(excel_file, sheet_name=chosen_sheet)
    except Exception as e_parse:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {e_parse}")

    # Header Row Auto-Detection (if title banners or empty rows exist above headers)
    recognized_keywords = ['code', 'name', 'center', 'position', 'role', 'phone', 'mail', 'crm', 'adl', 'adtv', 'prepaid', 'designation', 'tl', 'acso', 'staff', 'employee', 'full name']
    cols_str = ' '.join(str(c).lower() for c in df.columns)
    matches = sum(1 for kw in recognized_keywords if kw in cols_str)
    if matches < 2 and len(df) > 0:
        for idx in range(min(10, len(df))):
            row_vals = ' '.join(str(v).lower() for v in df.iloc[idx].values)
            if sum(1 for kw in recognized_keywords if kw in row_vals) >= 2:
                df.columns = [str(v).strip() if pd.notna(v) else f"col_{c_idx}" for c_idx, v in enumerate(df.iloc[idx].values)]
                df = df.iloc[idx + 1:].reset_index(drop=True)
                break

    col_map = {}
    for c in df.columns:
        clean = str(c).lower().strip().replace('_', ' ').replace('-', ' ')
        # 1. Exact canonical matches first
        if clean in ['emp code', 'employee code', 'emp id', 'employee id', 'staff id', 'alloted to', 'code']:
            col_map[c] = 'emp_code'
        elif clean in ['position', 'designation', 'role', 'job title', 'post']:
            col_map[c] = 'position'
        elif clean in ['phone number', 'phone', 'mobile', 'mobile number', 'contact', 'cell', 'tel']:
            col_map[c] = 'phone'
        elif clean in ['gmail', 'email', 'mail', 'email address', 'gmail / email']:
            col_map[c] = 'email'
        elif clean in ['name in postpaid crm', 'postpaid crm name', 'crm name', 'postpaid crm']:
            col_map[c] = 'crm_name'
        elif clean in ['center name in postpaid adl', 'postpaid adl center', 'adl center']:
            col_map[c] = 'adl_center'
        elif clean in ['center name in postpaid adtv', 'postpaid adtv center', 'adtv center']:
            col_map[c] = 'adtv_center'
        elif clean in ['center name in prepaid', 'prepaid center', 'sms center', 'center in prepaid']:
            col_map[c] = 'prepaid_center'
        elif clean in ['center display name', 'center name', 'center', 'hub', 'location', 'station']:
            col_map[c] = 'center_name'
        elif clean in ['employee display name', 'employee name', 'emp name', 'display name', 'full name', 'name', 'staff', 'officer']:
            col_map[c] = 'emp_name'
        # 2. Resilient fallback for informal or variant column headers
        elif 'crm' in clean and 'name' in clean:
            col_map[c] = 'crm_name'
        elif 'adl' in clean and 'center' in clean:
            col_map[c] = 'adl_center'
        elif 'adtv' in clean and 'center' in clean:
            col_map[c] = 'adtv_center'
        elif 'prepaid' in clean and 'center' in clean:
            col_map[c] = 'prepaid_center'
        elif any(k in clean for k in ['emp code', 'alloted', 'emp no']):
            col_map[c] = 'emp_code'
        elif any(k in clean for k in ['phone', 'mobile', 'contact']):
            col_map[c] = 'phone'
        elif any(k in clean for k in ['email', 'gmail']):
            col_map[c] = 'email'
        elif any(k in clean for k in ['position', 'role', 'designation']):
            col_map[c] = 'position'
        elif 'center' in clean:
            col_map[c] = 'center_name'
        elif any(k in clean for k in ['employee', 'staff', 'name']):
            col_map[c] = 'emp_name'

    df_renamed = df.rename(columns=col_map)
    if "emp_name" not in df_renamed.columns:
        found_cols = ", ".join(f"'{c}'" for c in df.columns[:8])
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded sheet is missing the Employee Name column. Recognized columns found: [{found_cols}]. Please use 'Employee Display name' or 'Name'."
        )

    clean_reg = region_id.capitalize()
    if "center_name" not in df_renamed.columns:
        df_renamed["center_name"] = clean_reg

    records = []
    for _, row in df_renamed.iterrows():
        emp_name = str(row.get("emp_name", "")).strip()
        if not emp_name or emp_name.lower() in ("nan", "none", "null", ""):
            continue

        center_name = str(row.get("center_name", "")).strip()
        if not center_name or center_name.lower() in ("nan", "none", "null", ""):
            center_name = clean_reg

        emp_code = str(row.get("emp_code", "")).strip()
        if emp_code.lower() in ("nan", "none", "null"):
            emp_code = ""
        elif emp_code.endswith(".0"):
            emp_code = emp_code[:-2]

        pos_raw = str(row.get("position", "")).strip()
        if not pos_raw or pos_raw.lower() in ("nan", "none", "null"):
            position = "ACSO" if "acso" in emp_name.lower() else "Team Leader"
        else:
            position = pos_raw

        phone = str(row.get("phone", "")).strip()
        if phone.lower() in ("nan", "none", "null"):
            phone = ""
        elif phone.endswith(".0"):
            phone = phone[:-2]

        email = str(row.get("email", "")).strip()
        if email.lower() in ("nan", "none", "null"):
            email = ""

        crm_val = row.get("crm_name")
        if pd.isna(crm_val) or str(crm_val).strip().lower() in ("nan", "none", "null", ""):
            crm_name = emp_name
        else:
            crm_name = str(crm_val)

        adl_center = str(row.get("adl_center", center_name)).strip()
        if not adl_center or adl_center.lower() in ("nan", "none", "null"):
            adl_center = center_name

        adtv_center = str(row.get("adtv_center", center_name)).strip()
        if not adtv_center or adtv_center.lower() in ("nan", "none", "null"):
            adtv_center = center_name

        prepaid_center = str(row.get("prepaid_center", center_name)).strip()
        if not prepaid_center or prepaid_center.lower() in ("nan", "none", "null"):
            prepaid_center = center_name

        records.append({
            "emp_code": emp_code,
            "emp_name": emp_name,
            "position": position,
            "phone": phone,
            "email": email,
            "center_name": center_name,
            "crm_name": crm_name,
            "adl_center": adl_center,
            "adtv_center": adtv_center,
            "prepaid_center": prepaid_center,
        })

    if not records:
        raise HTTPException(
            status_code=400,
            detail="No valid employee rows found in the uploaded file. Please ensure employee names are present."
        )

    res = db_manager.import_unified_directory(region_id, records)
    total = res.get("total_employees_imported", res.get("employees_imported", len(records)))
    return {
        "status": "OK",
        "message": f"Successfully imported {total} employee(s) across {res.get('centers_configured', 0)} center(s) for region '{region_id}'.",
        "details": res
    }




# --- Live Engine & Report Operations ---

@app.get("/api/regions/{region_id}/test-engine")
def test_calculation_engine(region_id: str):
    """
    Executes pure-Python mathematical computation using dynamic region configuration
    against loaded CRM sheets.
    """
    try:
        df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(resolve_target_excel_path())
        df_adl = filter_adl(df_adl, region=region_id)
        df_adtv = filter_adtv(df_adtv, region=region_id)
        df_prepaid = filter_prepaid(df_prepaid, region=region_id)
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
def generate_reports(region_id: str, report_type: Optional[str] = "complaint"):
    """
    Computes report for the region and renders high-definition Retina JPEG images.
    Supports report_type: 'complaint' (default: 4 cards), 'sr' / 'service_request' (3 cards), or 'all' / 'suite_all' (both: 7 cards).
    """
    try:
        r_type = (report_type or "complaint").lower().strip()
        rendered_images = []

        # 1. Render Complaints if requested
        if r_type in ("all", "suite_all", "complaint", "complaints"):
            df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(resolve_target_excel_path())
            df_adl = filter_adl(df_adl, region=region_id)
            df_adtv = filter_adtv(df_adtv, region=region_id)
            df_prepaid = filter_prepaid(df_prepaid, region=region_id)
            result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

            df_sections = {
                "adl_team": result.final["adl_team"].to_frame(),
                "adtv_team": result.final["adtv_team"].to_frame(),
                "adl_acso": result.final["adl_acso"].to_frame(),
                "adtv_acso": result.final["adtv_acso"].to_frame(),
            }

            generate_report_images(df_sections)
            generate_acso_report_images(df_sections)
            rendered_images.extend([
                "/output/ADL_Complaint_Pending.jpg",
                "/output/ADTv_Complaint_Pending.jpg",
                "/output/ADL_ACSO_Complaint_Pending.jpg",
                "/output/ADTv_ACSO_Complaint_Pending.jpg",
            ])

        # 2. Render Service Requests if requested
        if r_type in ("all", "suite_all", "sr", "service_request", "sr_all"):
            sr_sec = compute_service_request_reports(region_id=region_id)
            render_sr_report_images(sr_sec)
            rendered_images.extend([
                "/output/ADL_SR_Pending.jpg",
                "/output/ADTv_SR_Pending.jpg",
                "/output/Daily_SR_Report_latest.jpg",
            ])

        return {
            "status": "OK",
            "message": f"Reports rendered successfully ({r_type})",
            "images": rendered_images
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/regions/{region_id}/dispatch-whatsapp")
def dispatch_whatsapp(region_id: str, report_type: Optional[str] = "complaint"):
    """
    Sends report cards directly to WhatsApp configured for this region based on active dispatch rules.
    Supports report_type: 'complaint' (default), 'sr' / 'service_request', or 'all' / 'suite_all'.
    """
    try:
        r_type = (report_type or "complaint").lower().strip()
        rules = db_manager.get_dispatch_rules(region_id)
        active_rules = [r for r in rules if r.get("is_enabled", 1)]

        def is_sr_type(rt: str) -> bool:
            return is_sr_report_type(rt)

        if r_type in ("complaint", "complaints"):
            target_rules = [r for r in active_rules if not is_sr_type(r.get("report_type", ""))]
        elif r_type in ("sr", "service_request"):
            target_rules = [r for r in active_rules if is_sr_type(r.get("report_type", ""))]
        else:
            target_rules = active_rules

        if not target_rules:
            raise HTTPException(
                status_code=400,
                detail=f"No active dispatch rules found for '{r_type}'. Please configure dispatch rules in the Auto Schedule & Routing tab."
            )

        dispatched_count = 0
        for rule in target_rules:
            rule_type = rule.get("report_type", "all")
            targets = [t.strip() for t in str(rule.get("target_recipients", "")).split(",") if t.strip()]
            if not targets:
                continue

            imgs = get_images_for_report_type(rule_type)
            missing = [img for img in imgs if not img.exists()]
            if missing:
                if is_sr_type(rule_type):
                    sr_sec = compute_service_request_reports(region_id=region_id)
                    render_sr_report_images(sr_sec)
                else:
                    df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(resolve_target_excel_path())
                    res = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)
                    df_sections = {
                        "adl_team": res.final["adl_team"].to_frame(),
                        "adtv_team": res.final["adtv_team"].to_frame(),
                        "adl_acso": res.final["adl_acso"].to_frame(),
                        "adtv_acso": res.final["adtv_acso"].to_frame(),
                    }
                    generate_report_images(df_sections)
                    generate_acso_report_images(df_sections)

            if flash_report_image(imgs, target_recipients=targets):
                dispatched_count += 1

        return {
            "status": "OK",
            "message": f"Successfully triggered {dispatched_count} active dispatch rule(s) for '{r_type}'."
        }
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

    r_type = (payload.report_type or "all").lower().strip()

    try:
        # 1. Service Request only dispatch
        if is_sr_report_type(r_type):
            sr_sec = compute_service_request_reports(region_id=region_id)
            render_sr_report_images(sr_sec)
            imgs = get_images_for_report_type(r_type)
            success = flash_report_image(imgs, target_recipients=[target])
            if success:
                return {"status": "OK", "message": f"Service Request reports sent to {target} successfully!"}
            raise HTTPException(status_code=500, detail="WhatsApp delivery failed.")

        # 2. Download latest CRM tickets for complaints
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
            df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(resolve_target_excel_path())

        # 3. Compute report
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)

        # 4. Render High-DPI images
        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }
        generate_report_images(df_sections)
        generate_acso_report_images(df_sections)

        # 5. Save working copy
        try:
            write_working_copy(df_adl, df_adtv, df_prepaid, template_path=resolve_target_excel_path())
        except Exception:
            pass

        # 6. If suite_all, generate SR cards as well
        if r_type in ("suite_all", "everything"):
            try:
                sr_sec = compute_service_request_reports(region_id=region_id)
                render_sr_report_images(sr_sec)
            except Exception as e_sr:
                print(f"[Generate & Send] SR generation notice: {e_sr}")

        # 7. Dispatch to the specified number
        imgs = get_images_for_report_type(r_type)
        success = flash_report_image(imgs, target_recipients=[target])
        if success:
            return {"status": "OK", "message": f"Reports generated & sent to {target} successfully!"}
        else:
            raise HTTPException(status_code=500, detail="WhatsApp delivery failed.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Report Type Image Helper ---

def get_images_for_report_type(report_type: str) -> List[Path]:
    r = (report_type or "all").lower().strip()
    if r in ("adl_tl", "adl_team"):
        return [ADL_REPORT_IMAGE_PATH]
    elif r in ("adtv_tl", "adtv_team"):
        return [ADTV_REPORT_IMAGE_PATH]
    elif r in ("adl_acso", "adl_acso_complaint"):
        return [ADL_ACSO_REPORT_IMAGE_PATH]
    elif r in ("adtv_acso", "adtv_acso_complaint"):
        return [ADTV_ACSO_REPORT_IMAGE_PATH]
    elif r in ("adl_sr", "adl_sr_acso"):
        return [ADL_SR_REPORT_IMAGE_PATH]
    elif r in ("adtv_sr", "adtv_sr_acso"):
        return [ADTV_SR_REPORT_IMAGE_PATH]
    elif r in ("sr_combined", "sr_side_by_side", "combined_sr"):
        return [SR_REPORT_IMAGE_PATH]
    elif r in ("sr_all", "service_request", "sr"):
        return [ADL_SR_REPORT_IMAGE_PATH, ADTV_SR_REPORT_IMAGE_PATH]
    elif r in ("suite_all", "everything"):
        return [
            ADL_REPORT_IMAGE_PATH,
            ADTV_REPORT_IMAGE_PATH,
            ADL_ACSO_REPORT_IMAGE_PATH,
            ADTV_ACSO_REPORT_IMAGE_PATH,
            ADL_SR_REPORT_IMAGE_PATH,
            ADTV_SR_REPORT_IMAGE_PATH,
        ]
    elif r in ("all", "complaints_all"):
        return [
            ADL_REPORT_IMAGE_PATH,
            ADTV_REPORT_IMAGE_PATH,
            ADL_ACSO_REPORT_IMAGE_PATH,
            ADTV_ACSO_REPORT_IMAGE_PATH,
        ]
    return [ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH]


def execute_automated_cycle(region_id: str = DEFAULT_REGION_ID) -> Dict[str, Any]:
    """Pulls fresh tickets from CRM, computes report, renders images, and dispatches per rules."""
    ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        adl_path, adtv_path, prep_path = download_from_crm(region=region_id, headless=True, allow_stale=False)
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

        write_working_copy(df_adl, df_adtv, df_prepaid, template_path=resolve_target_excel_path())

        # Dispatch according to active rules
        rules = db_manager.get_dispatch_rules(region_id)
        dispatched_count = 0
        dispatch_failures = []
        for r in rules:
            if not r.get("is_enabled", 1):
                continue
            targets = [t.strip() for t in r.get("target_recipients", "").split(",") if t.strip()]
            if not targets:
                continue
            report_type = r.get("report_type", "all").lower().strip()
            # Skip SR rules in complaint cycle (handled by execute_automated_sr_cycle)
            if is_sr_report_type(report_type):
                continue
            imgs = get_images_for_report_type(report_type)
            ok = flash_report_image(imgs, target_recipients=targets)
            if ok:
                dispatched_count += 1
            else:
                dispatch_failures.append(r.get("rule_name") or f"Rule #{r.get('id')}")

        if rules and not dispatched_count and dispatch_failures:
            raise RuntimeError(f"WhatsApp dispatch failed for active rule(s): {', '.join(dispatch_failures)}. Check WhatsApp Web session.")

        status_msg = f"Completed at {ts_now}. Dispatched {dispatched_count} active rule(s)."
        db_manager.set_setting("last_cycle_timestamp", ts_now)
        db_manager.set_setting("last_cycle_status", status_msg)
        return {"status": "OK", "message": status_msg, "dispatched_rules": dispatched_count}
    except Exception as e:
        err_msg = f"Failed at {ts_now}: {e}"
        db_manager.set_setting("last_cycle_timestamp", ts_now)
        db_manager.set_setting("last_cycle_status", err_msg)
        try:
            from telegram_bot import format_automated_error_alert, get_alert_retry_keyboard, broadcast_telegram_alert
            alert_text = format_automated_error_alert(
                pipeline="Complaint Tracker",
                region_id=region_id,
                error_message=str(e),
                timestamp=ts_now,
            )
            kb = get_alert_retry_keyboard("complaint")
            broadcast_telegram_alert(alert_text, reply_markup=kb)
        except Exception as alert_ex:
            print(f"[Telegram Alert Error] Failed to broadcast complaint alert: {alert_ex}")
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
    r_type = rule.get("report_type", "all").lower().strip()
    imgs = get_images_for_report_type(r_type)
    missing = [i for i in imgs if not i.exists()]
    if missing:
        if is_sr_report_type(r_type):
            sr_sec = compute_service_request_reports(region_id=rule["region_id"])
            render_sr_report_images(sr_sec)
        else:
            df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(TARGET_EXCEL_PATH)
            df_adl = filter_adl(df_adl, region=rule["region_id"])
            df_adtv = filter_adtv(df_adtv, region=rule["region_id"])
            df_prepaid = filter_prepaid(df_prepaid, region=rule["region_id"])
            result = compute_report(df_adl, df_adtv, df_prepaid, region_id=rule["region_id"])
            df_sections = {
                "adl_team": result.final["adl_team"].to_frame(),
                "adtv_team": result.final["adtv_team"].to_frame(),
                "adl_acso": result.final["adl_acso"].to_frame(),
                "adtv_acso": result.final["adtv_acso"].to_frame(),
            }
            generate_report_images(df_sections)
            generate_acso_report_images(df_sections)
            if r_type in ("suite_all", "everything"):
                try:
                    sr_sec = compute_service_request_reports(region_id=rule["region_id"])
                    render_sr_report_images(sr_sec)
                except Exception:
                    pass

    success = flash_report_image(imgs, target_recipients=targets)
    if success:
        return {"status": "OK", "message": f"Successfully sent '{rule['rule_name']}' to {len(targets)} recipient(s)"}
    raise HTTPException(status_code=500, detail="WhatsApp dispatch failed or profile is busy. Please wait a few seconds and try again.")


# --- Schedule Times Endpoints ---

@app.get("/api/regions/{region_id}/schedule-times")
def list_schedule_times(region_id: str, report_type: Optional[str] = None):
    return db_manager.get_schedule_times(region_id, report_type=report_type)


@app.post("/api/regions/{region_id}/schedule-times")
def create_schedule_time(region_id: str, payload: ScheduleTimePayload):
    sid = db_manager.add_schedule_time(
        region_id,
        payload.run_time,
        payload.label or "",
        report_type=payload.report_type or "complaint"
    )
    return {"status": "OK", "id": sid}


@app.put("/api/schedule-times/{time_id}")
def update_schedule_time_endpoint(time_id: int, payload: ScheduleTimePayload):
    db_manager.update_schedule_time(
        time_id,
        payload.run_time,
        payload.label or "",
        1 if payload.is_enabled else 0,
        report_type=payload.report_type
    )
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
        "default_region_id": DEFAULT_REGION_ID,
        "last_sr_cycle_timestamp": db_manager.get_setting(f"last_sr_cycle_{DEFAULT_REGION_ID}", "Not yet executed"),
        "last_sr_cycle_status": db_manager.get_setting(f"last_sr_cycle_status_{DEFAULT_REGION_ID}", "Ready"),
    }


@app.post("/api/system/scheduler-toggle")
def toggle_master_scheduler():
    current = db_manager.get_setting("scheduler_enabled", "1")
    new_val = "0" if current == "1" else "1"
    db_manager.set_setting("scheduler_enabled", new_val)
    return {"status": "OK", "scheduler_enabled": new_val == "1"}


@app.post("/api/system/run-automated-cycle-now")
def run_automated_cycle_now(
    payload: Optional[CycleRunPayload] = None,
    region_id: Optional[str] = None,
    pipeline: Optional[str] = None,
):
    target_region = DEFAULT_REGION_ID
    target_pipeline = "all"

    if payload:
        if payload.region_id:
            target_region = payload.region_id
        if getattr(payload, "pipeline", None):
            target_pipeline = payload.pipeline
    if region_id:
        target_region = region_id
    if pipeline:
        target_pipeline = pipeline

    target_pipeline = target_pipeline.lower().strip()

    if target_pipeline in ("complaint", "complaints"):
        return execute_automated_cycle(target_region)
    elif target_pipeline in ("service_request", "sr"):
        return execute_automated_sr_cycle(target_region)
    else:
        comp_res = execute_automated_cycle(target_region)
        sr_res = execute_automated_sr_cycle(target_region)
        ok = (comp_res.get("status") == "OK") and (sr_res.get("status") == "OK")
        msg = f"Complaints: {comp_res.get('message', '')} | Service Requests: {sr_res.get('message', '')}"
        return {
            "status": "OK" if ok else "PARTIAL",
            "message": msg,
            "complaint_result": comp_res,
            "service_request_result": sr_res,
        }


# --- Service Request (SR) Endpoints ---

@app.get("/api/service-request/reports")
def get_service_request_reports_endpoint(region_id: Optional[str] = None):
    """Returns preview tables for ADL and ADTv Service Request Pending."""
    try:
        target_region = region_id or DEFAULT_REGION_ID
        sections = compute_service_request_reports(region_id=target_region)
        return {
            "status": "OK",
            "adl": sections["ADL Service Request Pending"].to_dict(orient="records"),
            "adtv": sections["ADTv Service Request Pending"].to_dict(orient="records"),
            "last_updated": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/service-request/run-cycle")
def run_service_request_cycle_endpoint(payload: Optional[CycleRunPayload] = None, region_id: Optional[str] = None):
    """Triggers the full automated cycle for Service Requests."""
    target_region = DEFAULT_REGION_ID
    if payload and payload.region_id:
        target_region = payload.region_id
    elif region_id:
        target_region = region_id
    res = execute_automated_sr_cycle(target_region)
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=500, detail=res.get("message"))
    return res


@app.get("/api/service-request/download-excel")
def download_service_request_excel_endpoint(region_id: Optional[str] = None):
    """Downloads the generated Daily Service Request Pending Excel report."""
    if not SR_EXCEL_REPORT_PATH.exists():
        try:
            sections = compute_service_request_reports(region_id=region_id or DEFAULT_REGION_ID)
            create_sr_excel_output(sections)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot generate Excel: {e}")

    return FileResponse(
        path=str(SR_EXCEL_REPORT_PATH),
        filename="Daily_Service_Request_Pending_Report.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.post("/api/complaints/upload-raw")
async def upload_complaints_raw_endpoint(file: UploadFile = File(...)):
    """Uploads a fresh raw Complaints Excel workbook and re-computes reports immediately."""
    if not file.filename.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Only Excel (.xls, .xlsx) files are supported.")
    try:
        content = await file.read()
        target_file = BASE_DIR / "Daily Complint Tracker.xls"
        target_file.write_bytes(content)

        alt_target = BASE_DIR / "Daily Complint pending Report.xls"
        try:
            alt_target.write_bytes(content)
        except Exception:
            pass

        df_adl, df_adtv, df_prepaid = load_inputs_from_workbook(str(target_file))
        df_adl = filter_adl(df_adl, region=DEFAULT_REGION_ID)
        df_adtv = filter_adtv(df_adtv, region=DEFAULT_REGION_ID)
        df_prepaid = filter_prepaid(df_prepaid, region=DEFAULT_REGION_ID)
        result = compute_report(df_adl, df_adtv, df_prepaid, region_id=DEFAULT_REGION_ID)
        df_sections = {
            "adl_team": result.final["adl_team"].to_frame(),
            "adtv_team": result.final["adtv_team"].to_frame(),
            "adl_acso": result.final["adl_acso"].to_frame(),
            "adtv_acso": result.final["adtv_acso"].to_frame(),
        }
        await asyncio.to_thread(generate_report_images, df_sections)
        await asyncio.to_thread(generate_acso_report_images, df_sections)

        adl_total = result.final["adl_acso"].total.grand_total if result.final["adl_acso"].total else 0
        adtv_total = result.final["adtv_acso"].total.grand_total if result.final["adtv_acso"].total else 0

        return {
            "status": "OK",
            "message": f"Successfully uploaded '{file.filename}'! ADL Total: {adl_total}, ADTv Total: {adtv_total}.",
            "adl_total": adl_total,
            "adtv_total": adtv_total,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload failed: {e}")


@app.post("/api/service-request/upload-raw")
async def upload_service_request_raw_endpoint(file: UploadFile = File(...), region_id: Optional[str] = None):
    """Uploads a fresh raw Excel file and re-computes the reports immediately."""
    try:
        suffix = Path(file.filename).suffix or ".xls"
        target_file = BASE_DIR / f"Service Request - Raw Data{suffix}"
        content = await file.read()
        target_file.write_bytes(content)

        sections = compute_service_request_reports(target_file, region_id=region_id or DEFAULT_REGION_ID)
        create_sr_excel_output(sections)
        render_sr_report_images(sections)

        return {
            "status": "OK",
            "message": f"Successfully uploaded '{file.filename}' and generated fresh Service Request reports!",
            "adl_count": len(sections["ADL Service Request Pending"]),
            "adtv_count": len(sections["ADTv Service Request Pending"]),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload failed: {e}")


@app.post("/api/service-request/generate-and-send")
def send_service_request_to_phone_endpoint(payload: GenerateAndSendPayload, region_id: Optional[str] = None):
    """Generates Service Request reports and dispatches to specific phone number or WhatsApp group."""
    target = payload.target_phone.strip()
    if not target:
        raise HTTPException(status_code=400, detail="Target recipient cannot be empty.")

    try:
        sections = compute_service_request_reports(region_id=region_id or DEFAULT_REGION_ID)
        create_sr_excel_output(sections)
        render_sr_report_images(sections)

        r_type = (payload.report_type or "all").lower().strip()
        if r_type in ("adl_sr", "adl"):
            to_send = [ADL_SR_REPORT_IMAGE_PATH]
        elif r_type in ("adtv_sr", "adtv"):
            to_send = [ADTV_SR_REPORT_IMAGE_PATH]
        elif r_type in ("sr_combined", "sr_side_by_side", "combined_sr"):
            to_send = [SR_REPORT_IMAGE_PATH]
        else:
            to_send = [ADL_SR_REPORT_IMAGE_PATH, ADTV_SR_REPORT_IMAGE_PATH]

        success = flash_report_image(to_send, target_recipients=[target])
        if success:
            return {"status": "OK", "message": f"Service Request report sent to {target} successfully!"}
        raise HTTPException(status_code=500, detail="WhatsApp delivery failed or profile busy.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# --- Backup & Configuration Import/Export Endpoints ---

@app.get("/api/backup/export")
def export_configuration_endpoint(region_id: Optional[str] = None):
    """Exports configuration backup as JSON."""
    data = db_manager.export_backup(region_id=region_id)
    reg_label = region_id or "all_regions"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"dwr_config_{reg_label}_{ts}.json"
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.post("/api/backup/restore")
async def restore_configuration_endpoint(request: Request, target_region: Optional[str] = None):
    """Restores configuration from JSON payload."""
    try:
        body = await request.json()
        counts = db_manager.restore_backup(body, target_region=target_region)
        return {"status": "OK", "message": "Configuration restored successfully", "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to restore configuration: {e}")


@app.post("/api/backup/load-sample")
def load_sample_preset_endpoint(region_id: str = DEFAULT_REGION_ID):
    """Loads the bundled Thrissur sample roster and configuration."""
    db_manager.ensure_region_exists(region_id)
    try:
        counts = db_manager.load_sample_preset(region_id)
        return {"status": "OK", "message": f"Thrissur preset loaded into '{region_id}'", "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backup/clear")
def clear_region_configuration_endpoint(region_id: str):
    """Clears all configured roster data for a region."""
    db_manager.ensure_region_exists(region_id)
    conn = db_manager.get_connection()
    c = conn.cursor()
    for t in ["centers", "acsos", "team_leaders", "employees", "schedule_times", "dispatch_rules"]:
        c.execute(f'DELETE FROM "{t}" WHERE region_id = ?', (region_id,))
    conn.commit()
    conn.close()
    try:
        db_manager.sync_directory_to_json(region_id)
    except Exception:
        pass
    return {"status": "OK", "message": f"All roster data cleared for region '{region_id}'"}


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
    last_cleanup_hour = -1
    while True:
        try:
            await asyncio.sleep(25)
            now = datetime.now()

            # Automatic hourly cleanup of raw CRM downloads and expired logs
            if now.hour != last_cleanup_hour:
                last_cleanup_hour = now.hour
                try:
                    from crm_downloader import cleanup_old_download_files
                    cleanup_old_download_files()
                    logger_setup.cleanup_old_logs()
                except Exception:
                    pass

            if db_manager.get_setting("scheduler_enabled", "1") != "1":
                continue
            current_hh_mm = now.strftime("%H:%M")
            today_date = now.strftime("%Y-%m-%d")

            schedule_slots = db_manager.get_schedule_times()
            for slot in schedule_slots:
                if not slot.get("is_enabled", 1):
                    continue
                if slot.get("run_time") == current_hh_mm:
                    last_run = slot.get("last_run") or ""
                    if not last_run.startswith(today_date):
                        slot_type = slot.get("report_type") or "complaint"
                        if slot_type == "service_request":
                            print(f"\n[Scheduler] Auto-triggering SERVICE REQUEST report for region '{slot['region_id']}' at {current_hh_mm}...")
                            run_result = await asyncio.to_thread(execute_automated_sr_cycle, slot["region_id"])
                        else:
                            print(f"\n[Scheduler] Auto-triggering COMPLAINT report for region '{slot['region_id']}' at {current_hh_mm}...")
                            run_result = await asyncio.to_thread(execute_automated_cycle, slot["region_id"])
                        if isinstance(run_result, dict) and run_result.get("status") == "OK":
                            db_manager.update_last_run(slot["id"])
                        else:
                            print(f"[Scheduler] Slot {slot['id']} failed; leaving last_run unchanged for retry.")
        except Exception as e:
            print(f"[Scheduler Loop Error] {e}")
            try:
                from telegram_bot import format_automated_error_alert, broadcast_telegram_alert
                alert_text = format_automated_error_alert(
                    pipeline="Background Scheduler Loop",
                    region_id="system",
                    error_message=f"Critical scheduler loop error: {e}",
                )
                broadcast_telegram_alert(alert_text)
            except Exception:
                pass


@app.on_event("startup")
async def start_scheduler_task():
    try:
        db_manager.auto_sync_directory_from_disk(DEFAULT_REGION_ID)
    except Exception as e:
        print(f"[Startup Directory Auto-Sync] {e}")
    asyncio.create_task(background_scheduler_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_server:app", host="127.0.0.1", port=8201, reload=True, reload_includes=["*.html", "*.py", "*.js", "*.css"])

