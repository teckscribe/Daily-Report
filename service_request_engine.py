"""
service_request_engine.py
=========================
Automated Service Request (SR) Pending Report Engine for Daily QOS Tracker.

Generates:
1. ACSO-wise Pending Pivot Reports (ADL Broadband & ADTv Digital TV).
2. Formatted Multi-section Excel Workbook (output/Daily_Service_Request_Pending_Report.xlsx).
3. High-DPI Retina Mobile Images (output/ADL_SR_Pending.jpg, output/ADTv_SR_Pending.jpg,
   and combined output/Daily_SR_Report_latest.jpg).
4. WhatsApp Automated Dispatch to configured groups and recipients.
"""

import html
import os
import re
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from PIL import Image
from playwright.sync_api import sync_playwright

from config import (
    BASE_DIR,
    DATA_DIR,
    DOWNLOADS_DIR,
    OUTPUT_DIR,
    TARGET_REGION,
    DEFAULT_REGION_ID,
)
import db_manager

# --- Paths ---
SR_RAW_EXCEL_PATH = DATA_DIR / "Service Request - Raw Data.xls"
SR_EXCEL_REPORT_PATH = OUTPUT_DIR / "Daily_Service_Request_Pending_Report.xlsx"
ADL_SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADL_SR_Pending.jpg"
ADTV_SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADTv_SR_Pending.jpg"
SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "Daily_SR_Report_latest.jpg"

REPORT_COLUMNS = [
    "CENTER", "Service Request Type", "Grand Total",
    "<1 day", "1 day", "2 day", "3 day", ">3 day", ">5 day", "> 10 day"
]

BUCKET_COLUMNS = [
    "<1 day", "1 day", "2 day", "3 day", ">3 day", ">5 day", "> 10 day"
]

SR_REPORT_TYPES = {
    "sr",
    "service_request",
    "sr_all",
    "adl_sr",
    "adl_sr_acso",
    "adtv_sr",
    "adtv_sr_acso",
    "sr_combined",
    "sr_side_by_side",
    "combined_sr",
}


def is_sr_report_type(report_type: Optional[str]) -> bool:
    """Returns True if the given report type string is any variant of Service Request reports."""
    if not report_type:
        return False
    clean = str(report_type).lower().strip()
    return (
        clean in SR_REPORT_TYPES
        or clean.startswith("sr")
        or clean.endswith("_sr")
        or "_sr_" in clean
    )



# --- Normalization & Bucket Logic (Exact User Equations) ---

def pending_bucket(days: Any) -> str:
    """Classifies elapsed days into institutional pending buckets."""
    days_val = pd.to_numeric(days, errors="coerce")
    if pd.isna(days_val) or days_val < 1:
        return "<1 day"

    days_int = int(days_val)
    if days_int == 1:
        return "1 day"
    if days_int == 2:
        return "2 day"
    if days_int == 3:
        return "3 day"
    if days_int <= 5:
        return ">3 day"
    if days_int <= 10:
        return ">5 day"
    return "> 10 day"


def normalize_service(value: Any) -> str:
    """Standardizes disparate CRM complaint and problem text into uniform categories."""
    value_str = str(value).strip()
    service_map = {
        "cable rerouting required": "Cable Rerouting",
        "cable rerouting": "Cable Rerouting",
        "cable re-routing": "Cable Rerouting",
        "reconnection - cabling to be done": "Reconnection",
        "reconnection req with field visit": "Reconnection",
        "shift newconnection": "Shifting",
        "shifting request": "Shifting",
        "transfer to a new location": "Shifting",
    }
    return service_map.get(value_str.casefold(), value_str)


def is_excluded_service(value: Any) -> bool:
    """
    Returns True if the ticket should be excluded from report generation.
    Specifically excludes 'STATIC IP Renewal' complaint types under the Service Request head
    from the SMS portal (https://sms.ali.asianetindia.com/) and CRM portals.
    """
    if value is None or pd.isna(value):
        return True
    v_norm = str(value).strip().lower()
    if not v_norm or v_norm in ("nan", "none", "null"):
        return True
    if "static ip renewal" in v_norm or "static ip" in v_norm:
        return True
    return False


def prepare_source(
    df: pd.DataFrame,
    center_col: str,
    service_col: str,
    days_col: str,
    center_case: Optional[str] = None,
) -> pd.DataFrame:
    """Prepares and cleans raw CRM tickets for pivoting."""
    if df.empty or center_col not in df.columns or service_col not in df.columns or days_col not in df.columns:
        return pd.DataFrame(columns=["CENTER", "Service Request Type", "Days", "Pending Bucket"])

    data = df[[center_col, service_col, days_col]].copy()
    data.columns = ["CENTER", "Service Request Type", "Days"]
    data = data.dropna(subset=["CENTER", "Service Request Type"])

    # Exclude 'STATIC IP Renewal' from report generation
    data = data[~data["Service Request Type"].apply(is_excluded_service)].copy()

    data["CENTER"] = data["CENTER"].astype(str).str.strip()
    data["Service Request Type"] = data["Service Request Type"].apply(normalize_service)

    # Secondary check after normalization
    data = data[~data["Service Request Type"].apply(is_excluded_service)]
    # Never allow unrelated portal records into the SR report, even if a
    # source export is broader than its intended filters.
    data = data[data["Service Request Type"].isin({"Shifting", "Cable Rerouting", "Reconnection"})].copy()

    if center_case == "title":
        data["CENTER"] = data["CENTER"].str.title()

    data["Pending Bucket"] = data["Days"].apply(pending_bucket)
    return data


def build_pending_report(data: pd.DataFrame) -> pd.DataFrame:
    """Builds pivot table grouped by CENTER and Service Request Type."""
    if data.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    pivot = pd.pivot_table(
        data,
        index=["CENTER", "Service Request Type"],
        columns="Pending Bucket",
        values="Days",
        aggfunc="count",
        fill_value=0,
    ).reset_index()

    for col in BUCKET_COLUMNS:
        if col not in pivot.columns:
            pivot[col] = 0

    pivot["Grand Total"] = pivot[BUCKET_COLUMNS].sum(axis=1)
    pivot = pivot[pivot["Grand Total"] > 0]
    pivot = pivot[["CENTER", "Service Request Type", "Grand Total"] + BUCKET_COLUMNS]

    pivot = pivot.sort_values(
        by=["CENTER", "Service Request Type"],
        kind="stable",
    ).reset_index(drop=True)

    return pivot


# --- Data Ingestion ---

def find_service_request_raw_file() -> Optional[Path]:
    """Finds the most recent Service Request raw data Excel file."""
    search_locations = [
        DATA_DIR / "Service Request - Raw Data.xls",
        DATA_DIR / "Service Request - Raw Data.xlsx",
        # Compatibility only for existing manual installations.
        BASE_DIR / "Service Request - Raw Data.xls",
        BASE_DIR / "Service Request - Raw Data.xlsx",
    ]
    exact_matches = [p for p in search_locations if p.exists() and p.stat().st_size > 1000]
    if exact_matches:
        return max(exact_matches, key=lambda f: f.stat().st_mtime)

    for search_dir in [DATA_DIR, DOWNLOADS_DIR, BASE_DIR]:
        matches = list(search_dir.glob("Service Request*.xls*"))
        if matches:
            return max(matches, key=lambda f: f.stat().st_mtime)

    return None


def sr_output_path(filename: str, region_id: str = DEFAULT_REGION_ID) -> Path:
    """Keep output isolated by validated region ID, including for concurrent regions."""
    import re
    if not re.fullmatch(r"[a-z0-9_-]+", region_id):
        raise ValueError("Invalid region ID")
    return OUTPUT_DIR / "regions" / region_id / filename


def compute_service_request_reports(
    raw_path: Optional[Path] = None,
    region_id: str = DEFAULT_REGION_ID,
) -> Dict[str, pd.DataFrame]:
    """
    Reads the raw Excel workbook (ADL Postpaid, ADTv, Prepaid) and returns
    both computed pivot DataFrames.
    """
    file_path = raw_path or find_service_request_raw_file()
    if not file_path or not file_path.exists():
        raise FileNotFoundError(
            "Service Request raw data file not found. Use 'Upload Raw SR' to upload a current "
            "Kottayam Service Request workbook; it will be stored privately in data/."
        )

    with pd.ExcelFile(file_path) as xl:
        sheet_names = xl.sheet_names

        # 1. ADL Postpaid Tickets
        adl_sheet = next((s for s in sheet_names if "ADL" in s), sheet_names[0])
        adl_df = pd.read_excel(xl, sheet_name=adl_sheet)

        # 2. ADTv Tickets
        adtv_sheet = next((s for s in sheet_names if "ADTv" in s or "DTV" in s.upper()), sheet_names[min(1, len(sheet_names)-1)])
        adtv_df = pd.read_excel(xl, sheet_name=adtv_sheet)

        # 3. Prepaid Tickets
        prep_sheet = next((s for s in sheet_names if "Prepaid" in s), None)
        if prep_sheet:
            prepaid_df = pd.read_excel(xl, sheet_name=prep_sheet)
        else:
            prepaid_df = pd.DataFrame()

    # CRM exports contain a REGION column for postpaid/TV. Resolve the
    # configured display name from the region record. Prepaid exports may
    # already be region-scoped; filter them too when a region column is
    # present. Legacy exports without REGION are accepted only in a
    # one-region installation and are then restricted to that region's
    # configured center keys.
    region_row = db_manager.get_region_by_id(region_id) or {}
    softcode_region = str(region_row.get("softcode_region") or region_id).strip()
    prepaid_region = str(region_row.get("prepaid_region") or softcode_region).strip()
    configured_regions = db_manager.get_all_regions()
    is_single_region_install = (
        len(configured_regions) == 1
        and str(configured_regions[0].get("id") or "").strip().casefold()
        == str(region_id).strip().casefold()
    )
    center_rows = db_manager.get_centers(region_id)

    def _center_keys(column: str) -> set[str]:
        return {
            str(row.get(column) or row.get("center_name") or "").strip().casefold()
            for row in center_rows
            if str(row.get(column) or row.get("center_name") or "").strip()
        }

    def _filter_region(
        frame: pd.DataFrame,
        region_name: str,
        center_columns: Tuple[str, ...],
        configured_center_column: str,
    ) -> pd.DataFrame:
        if frame.empty:
            return frame
        region_col = next((c for c in frame.columns if str(c).strip().casefold() == "region"), None)
        source_center_col = next(
            (c for c in frame.columns if str(c).strip().casefold() in center_columns),
            None,
        )
        allowed_centers = _center_keys(configured_center_column)
        if region_col:
            filtered = frame[
                frame[region_col].astype(str).str.strip().str.casefold() == region_name.casefold()
            ].copy()
            # Some portal exports can be labelled with the wrong region. When
            # a known center column is present, the configured center mapping
            # is the second required proof before a row is reported.
            if source_center_col and allowed_centers:
                return filtered[
                    filtered[source_center_col].astype(str).str.strip().str.casefold().isin(allowed_centers)
                ].copy()
            return filtered
        if is_single_region_install:
            if not source_center_col or not allowed_centers:
                raise ValueError(
                    f"Cannot verify source region {region_name!r}: this legacy Service Request "
                    "sheet needs a REGION column or configured center keys."
                )
            return frame[
                frame[source_center_col].astype(str).str.strip().str.casefold().isin(allowed_centers)
            ].copy()
        raise ValueError(
            f"Cannot verify source region {region_name!r}: a non-empty Service Request "
            "sheet has no REGION column. Upload a region-labelled export or remove "
            "the extra region from the dashboard."
        )

    adl_df = _filter_region(adl_df, softcode_region, ("area", "center"), "adl_area_key")
    adtv_df = _filter_region(adtv_df, softcode_region, ("serviceamo", "amo", "area"), "adtv_amo_key")
    prepaid_df = _filter_region(prepaid_df, prepaid_region, ("area", "center", "serviceamo", "amo"), "prepaid_area_key")

    # Process ADL Postpaid
    adl_postpaid = prepare_source(
        adl_df,
        center_col="AREA",
        service_col="PROBLEMSUBTYPE",
        days_col="DAYSELAPSED",
    )

    # Process Prepaid (Handle TAT or calculate from Created On)
    if not prepaid_df.empty:
        # SMS exports can include non-SR records. Restrict to the exact
        # Service Request complaint head before mapping its two SR labels.
        complaint_type_col = next(
            (c for c in prepaid_df.columns if str(c).strip().casefold() in ("complaint type", "complainttype")),
            None,
        )
        if complaint_type_col:
            prepaid_df = prepaid_df[
                prepaid_df[complaint_type_col].astype(str).str.strip().str.casefold() == "service request"
            ].copy()
        for c_col in ["Complaint", "COMPLAINT"]:
            if c_col in prepaid_df.columns:
                prepaid_df = prepaid_df[~prepaid_df[c_col].apply(is_excluded_service)].copy()

        prep_days_col = "DaysCalc"
        if "TAT" in prepaid_df.columns:
            prepaid_df["DaysCalc"] = prepaid_df["TAT"]
        elif "Created On" in prepaid_df.columns:
            # Calculate days elapsed since Created On
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            created_dt = pd.to_datetime(prepaid_df["Created On"], errors="coerce")
            prepaid_df["DaysCalc"] = (file_mtime - created_dt).dt.days.fillna(0).astype(int)
        else:
            prepaid_df["DaysCalc"] = 0

        prepaid = prepare_source(
            prepaid_df,
            center_col="Area",
            service_col="Complaint",
            days_col=prep_days_col,
            center_case="title",
        )
        adl_source = pd.concat([adl_postpaid, prepaid], ignore_index=True)
    else:
        adl_source = adl_postpaid

    adl_report = build_pending_report(adl_source)

    # Process ADTv
    adtv_source = prepare_source(
        adtv_df,
        center_col="SERVICEAMO",
        service_col="PROBLEMTYPE",
        days_col="DAYSELAPSED",
        center_case="title",
    )
    adtv_report = build_pending_report(adtv_source)

    return {
        "ADL Service Request Pending": adl_report,
        "ADTv Service Request Pending": adtv_report,
    }


def calculate_sr_pending_reports(raw_path: Optional[Path] = None, region_id: str = DEFAULT_REGION_ID) -> Dict[str, Any]:
    """Convenience wrapper returning computed records dictionary."""
    sections = compute_service_request_reports(raw_path, region_id=region_id)
    adl_records = sections["ADL Service Request Pending"].to_dict(orient="records")
    adtv_records = sections["ADTv Service Request Pending"].to_dict(orient="records")
    return {
        "status": "OK",
        "adl": adl_records,
        "adtv": adtv_records,
        "sections": sections,
    }


def generate_sr_excel_report(raw_path: Optional[Path] = None, region_id: str = DEFAULT_REGION_ID) -> Path:
    """Convenience wrapper computing and generating the formatted Excel workbook."""
    sections = compute_service_request_reports(raw_path, region_id=region_id)
    return create_excel_output(sections)


# --- Excel Output Generator (Exact xlsxwriter Formatting) ---

def _get_excel_column_name(col_num: int) -> str:
    name = ""
    col_num += 1
    while col_num:
        col_num, remainder = divmod(col_num - 1, 26)
        name = chr(65 + remainder) + name
    return name


def create_excel_output(
    sections: Dict[str, pd.DataFrame],
    target_path: Optional[Path] = None,
    region_id: str = DEFAULT_REGION_ID,
) -> Path:
    """
    Renders styled Excel workbook matching the exact Streamlit xlsxwriter logic.
    Saves to output/Daily_Service_Request_Pending_Report.xlsx.
    """
    dest = target_path or sr_output_path(SR_EXCEL_REPORT_PATH.name, region_id)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(dest), engine="xlsxwriter") as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet(" Report ")
        writer.sheets[" Report "] = worksheet

        title_format = workbook.add_format({
            "bold": True,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#993300",
            "font_color": "#FFFFFF",
            "font_size": 14,
        })

        header_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#D9D9D9",
        })

        pending_header_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#D8E4BC",
        })

        grand_total_value_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#D9D9D9",
            "num_format": "0;-0;;@",
        })

        green_value_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#00B050",
            "font_color": "#FFFFFF",
        })

        red_value_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#FF0000",
            "font_color": "#FFFFFF",
        })

        amber_value_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#FFC000",
            "font_color": "#000000",
        })

        number_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "num_format": "0;-0;;@",
        })

        text_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "left",
            "valign": "vcenter",
        })

        total_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "num_format": "0;-0;;@",
        })

        total_green_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#00B050",
            "font_color": "#FFFFFF",
            "num_format": "0;-0;;@",
        })

        total_red_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#FF0000",
            "font_color": "#FFFFFF",
            "num_format": "0;-0;;@",
        })

        total_amber_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#FFC000",
            "font_color": "#000000",
            "num_format": "0;-0;;@",
        })

        total_text_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "border": 1,
            "align": "left",
            "valign": "vcenter",
            "bg_color": "#CCCCFF",
        })

        start_positions = [0, 11]

        for section_index, (section_name, report_df) in enumerate(sections.items()):
            if section_index >= len(start_positions):
                break
            start_col = start_positions[section_index]

            worksheet.merge_range(0, start_col, 0, start_col + 1, section_name, title_format)
            for col in range(start_col + 2, start_col + 10):
                worksheet.write_blank(0, col, None, title_format)

            worksheet.merge_range(1, start_col, 2, start_col, "CENTER", header_format)
            worksheet.merge_range(1, start_col + 1, 2, start_col + 1, "Service Request Type", header_format)
            worksheet.merge_range(1, start_col + 2, 2, start_col + 2, "Grand Total", header_format)

            worksheet.merge_range(1, start_col + 3, 1, start_col + 4, "Pending Days", pending_header_format)
            for col in range(start_col + 5, start_col + 10):
                worksheet.write_blank(1, col, None, pending_header_format)

            for col_num, col_name in enumerate(BUCKET_COLUMNS, start=start_col + 3):
                worksheet.write(2, col_num, col_name, pending_header_format)

            for row_num in range(len(report_df)):
                excel_row = row_num + 3
                for col_num, col_name in enumerate(REPORT_COLUMNS):
                    value = report_df.iloc[row_num][col_name]
                    excel_col = start_col + col_num

                    if col_num in [0, 1]:
                        worksheet.write(excel_row, excel_col, value, text_format)
                    elif col_num == 2:
                        worksheet.write(excel_row, excel_col, value, grand_total_value_format)
                    elif value == 0:
                        worksheet.write_blank(excel_row, excel_col, None, number_format)
                    elif col_name == "<1 day":
                        worksheet.write(excel_row, excel_col, value, green_value_format)
                    elif col_name in ["1 day", "2 day"]:
                        worksheet.write(excel_row, excel_col, value, amber_value_format)
                    else:
                        worksheet.write(excel_row, excel_col, value, red_value_format)

            total_row = len(report_df) + 3
            first_data_row = 4
            last_data_row = total_row

            worksheet.write(total_row, start_col, "Grand Total", total_text_format)
            worksheet.write_blank(total_row, start_col + 1, None, header_format)

            for col_num in range(2, 10):
                excel_col = start_col + col_num
                col_letter = _get_excel_column_name(excel_col)
                formula = f"=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row})"
                fmt = grand_total_value_format if col_num == 2 else (total_green_format if col_num == 3 else total_format)
                worksheet.write_formula(total_row, excel_col, formula, fmt)

            worksheet.conditional_format(
                total_row, start_col + 4, total_row, start_col + 5,
                {"type": "cell", "criteria": ">", "value": 0, "format": total_amber_format},
            )
            worksheet.conditional_format(
                total_row, start_col + 6, total_row, start_col + 9,
                {"type": "cell", "criteria": ">", "value": 0, "format": total_red_format},
            )

            worksheet.set_column(start_col, start_col, 22)
            worksheet.set_column(start_col + 1, start_col + 1, 32)
            worksheet.set_column(start_col + 2, start_col + 9, 11)

    return dest


# --- High-DPI Retina HTML & Image Generator ---

def generate_sr_table_html(title: str, report_df: pd.DataFrame) -> str:
    """Generates pixel-perfect HTML table for Playwright Retina snapshot rendering."""
    esc_title = html.escape(title)

    # Calculate column totals
    gt_total = report_df["Grand Total"].sum() if not report_df.empty else 0
    bucket_totals = {b: report_df[b].sum() if not report_df.empty else 0 for b in BUCKET_COLUMNS}

    tbody_rows = ""
    for _, r in report_df.iterrows():
        c_name = html.escape(str(r["CENTER"]))
        s_type = html.escape(str(r["Service Request Type"]))
        gt_val = int(r["Grand Total"])

        cells_html = ""
        for b in BUCKET_COLUMNS:
            b_val = int(r[b])
            if b_val == 0:
                cells_html += '<td class="cell-empty"></td>'
            elif b == "<1 day":
                cells_html += f'<td class="cell-green">{b_val}</td>'
            elif b in ("1 day", "2 day"):
                cells_html += f'<td class="cell-amber">{b_val}</td>'
            else:
                cells_html += f'<td class="cell-red">{b_val}</td>'

        tbody_rows += f"""
        <tr>
            <td class="col-center">{c_name}</td>
            <td class="col-type">{s_type}</td>
            <td class="gt-val">{gt_val}</td>
            {cells_html}
        </tr>
        """

    # Grand total row
    tot_cells = ""
    for b in BUCKET_COLUMNS:
        tot_v = bucket_totals[b]
        if tot_v == 0:
            tot_cells += '<td class="tot-empty font-total"></td>'
        elif b == "<1 day":
            tot_cells += f'<td class="tot-green font-total">{tot_v}</td>'
        elif b in ("1 day", "2 day"):
            tot_cells += f'<td class="tot-amber font-total">{tot_v}</td>'
        else:
            tot_cells += f'<td class="tot-red font-total">{tot_v}</td>'

    tot_row = f"""
    <tr class="row-total">
        <td class="col-center label-total">Grand Total</td>
        <td class="col-type label-total"></td>
        <td class="gt-total font-total">{gt_total}</td>
        {tot_cells}
    </tr>
    """

    return f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background-color: #ffffff;
            font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
            padding: 10px;
            display: inline-block;
        }}
        .table-box {{
            border: 2px solid #000000;
            display: inline-block;
            background: #ffffff;
        }}
        .banner {{
            background-color: #993300;
            color: #ffffff;
            font-size: 24px;
            font-weight: bold;
            text-align: center;
            padding: 8px 12px;
            border-bottom: 2px solid #000000;
            letter-spacing: 0.5px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 19px;
            color: #000000;
        }}
        th, td {{
            border: 1px solid #7f7f7f;
            padding: 4px 8px;
            height: 36px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 19px;
            border: 1px solid #000000;
        }}
        .th-center {{ text-align: left; width: 230px; min-width: 230px; }}
        .th-type {{ text-align: left; width: 260px; min-width: 260px; }}
        .th-gt {{ text-align: center; width: 95px; min-width: 95px; }}
        .th-pending {{
            text-align: center;
            background-color: #d8e4bc;
            border: 1px solid #000000;
        }}
        .th-bucket {{
            text-align: center;
            width: 72px;
            min-width: 72px;
            background-color: #d8e4bc;
            font-size: 17.5px;
        }}
        
        .col-center {{ text-align: left; font-size: 19px; font-weight: bold; color: #000000; }}
        .col-type {{ text-align: left; font-size: 18.5px; font-weight: bold; color: #000000; }}
        .gt-val {{
            text-align: center;
            font-weight: bold;
            font-size: 20px;
            background-color: #d9d9d9;
            color: #000000;
        }}
        
        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 20px;
        }}
        .cell-amber {{
            background-color: #ffc000;
            color: #000000;
            font-weight: bold;
            text-align: center;
            font-size: 20px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 20px;
        }}
        
        .row-total td {{
            border-top: 2px solid #000000;
            border-bottom: 2px solid #000000;
            height: 46px;
        }}
        .label-total {{
            background-color: #ccccff;
            font-size: 21px;
            font-weight: bold;
        }}
        .gt-total {{
            background-color: #d9d9d9;
            text-align: center;
            font-size: 22px;
            font-weight: bold;
        }}
        .font-total {{
            font-size: 21px;
            font-weight: bold;
            text-align: center;
        }}
        .tot-empty {{ background-color: #ffffff; }}
        .tot-green {{ background-color: #00b050; color: #ffffff; }}
        .tot-amber {{ background-color: #ffc000; color: #000000; }}
        .tot-red {{ background-color: #ff0000; color: #ffffff; }}
    </style>
    </head>
    <body>
        <div class="table-box">
            <div class="banner">{esc_title}</div>
            <table>
                <thead>
                    <tr>
                        <th rowspan="2" class="th-center">CENTER</th>
                        <th rowspan="2" class="th-type">Service Request Type</th>
                        <th rowspan="2" class="th-gt">Grand Total</th>
                        <th colspan="7" class="th-pending">Pending Days</th>
                    </tr>
                    <tr>
                        <th class="th-bucket">&lt;1 day</th>
                        <th class="th-bucket">1 day</th>
                        <th class="th-bucket">2 day</th>
                        <th class="th-bucket">3 day</th>
                        <th class="th-bucket">&gt;3 day</th>
                        <th class="th-bucket">&gt;5 day</th>
                        <th class="th-bucket">&gt; 10 day</th>
                    </tr>
                </thead>
                <tbody>
                    {tbody_rows}
                    {tot_row}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


def render_sr_report_images(
    sections: Optional[Dict[str, pd.DataFrame]] = None,
    region_id: str = DEFAULT_REGION_ID,
) -> List[Path]:
    """
    Renders high-definition Retina report images (1600px+ width) using Playwright.
    Generates ADL_SR_Pending.jpg, ADTv_SR_Pending.jpg, and combined Daily_SR_Report_latest.jpg.
    """
    ADL_SR_REPORT_IMAGE_PATH = sr_output_path("ADL_SR_Pending.jpg", region_id)
    ADTV_SR_REPORT_IMAGE_PATH = sr_output_path("ADTv_SR_Pending.jpg", region_id)
    SR_REPORT_IMAGE_PATH = sr_output_path("Daily_SR_Report_latest.jpg", region_id)
    ADL_SR_REPORT_IMAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not sections:
        sections = compute_service_request_reports(region_id=region_id)

    html_adl = generate_sr_table_html("ADL Service Request Pending", sections["ADL Service Request Pending"])
    html_adtv = generate_sr_table_html("ADTv Service Request Pending", sections["ADTv Service Request Pending"])

    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if sys.platform == "win32":
            launch_kwargs["channel"] = "chrome"

        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            if "channel" in launch_kwargs:
                del launch_kwargs["channel"]
            browser = p.chromium.launch(**launch_kwargs)

        context = browser.new_context(device_scale_factor=2.2)
        page = context.new_page()

        # Render ADL
        page.set_content(html_adl, wait_until="networkidle")
        elem_adl = page.locator(".table-box")
        elem_adl.screenshot(path=str(ADL_SR_REPORT_IMAGE_PATH), type="jpeg", quality=95)
        print(f"[OK] Rendered Retina ADL Service Request: {ADL_SR_REPORT_IMAGE_PATH.name}")

        # Render ADTv
        page.set_content(html_adtv, wait_until="networkidle")
        elem_adtv = page.locator(".table-box")
        elem_adtv.screenshot(path=str(ADTV_SR_REPORT_IMAGE_PATH), type="jpeg", quality=95)
        print(f"[OK] Rendered Retina ADTv Service Request: {ADTV_SR_REPORT_IMAGE_PATH.name}")

        browser.close()

    # Combine into side-by-side or stacked image
    try:
        img_adl = Image.open(ADL_SR_REPORT_IMAGE_PATH)
        img_adtv = Image.open(ADTV_SR_REPORT_IMAGE_PATH)

        pad = 25
        # Side by side if both fit nicely
        comb_w = img_adl.width + img_adtv.width + pad
        comb_h = max(img_adl.height, img_adtv.height)

        combined = Image.new("RGB", (comb_w, comb_h), (255, 255, 255))
        combined.paste(img_adl, (0, 0))
        combined.paste(img_adtv, (img_adl.width + pad, 0))
        combined.save(str(SR_REPORT_IMAGE_PATH), quality=95)
        print(f"[OK] Saved Combined SR Image: {SR_REPORT_IMAGE_PATH.name} ({combined.size})")
    except Exception as e_comb:
        print(f"[!] Combined image notice: {e_comb}")

    return [ADL_SR_REPORT_IMAGE_PATH, ADTV_SR_REPORT_IMAGE_PATH, SR_REPORT_IMAGE_PATH]


# --- Automated Cycle & WhatsApp Dispatch ---

def execute_automated_sr_cycle(region_id: str = DEFAULT_REGION_ID) -> Dict[str, Any]:
    """
    Complete end-to-end automated cycle for Service Requests:
    1. Reads/loads raw ticket data
    2. Computes pivot reports
    3. Writes formatted Excel file
    4. Renders High-DPI Retina images
    5. Dispatches images to WhatsApp groups / numbers according to SR dispatch rules
    6. Logs execution
    """
    ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[SR_CYCLE] Starting automated Service Request cycle for region '{region_id}'...")

    try:
        # 1. Pull exact current SR source data before any automatic dispatch.
        from crm_downloader import download_service_requests_from_crm
        download_service_requests_from_crm(region=region_id, headless=True)

        # 2. Compute reports
        sections = compute_service_request_reports(region_id=region_id)

        # 3. Write Excel output
        excel_path = create_excel_output(sections, region_id=region_id)
        print(f"[SR_CYCLE] Generated Service Request Excel workbook: {excel_path.name}")

        # 4. Render High-DPI images
        img_paths = render_sr_report_images(sections, region_id=region_id)
        ADL_SR_REPORT_IMAGE_PATH, ADTV_SR_REPORT_IMAGE_PATH, SR_REPORT_IMAGE_PATH = img_paths
        print(f"[SR_CYCLE] Generated {len(img_paths)} Service Request Retina cards")

        # 5. WhatsApp Dispatch per configured rules
        from whatsapp_sender import flash_report_image, normalize_recipient

        # Find rules matching any SR report type or entire suite
        all_rules = db_manager.get_dispatch_rules(region_id)
        sr_rules = [
            r for r in all_rules
            if r.get("is_enabled", 1) and (
                is_sr_report_type(r.get("report_type"))
                or str(r.get("report_type", "")).lower().strip() in ("suite_all", "everything")
            )
        ]

        dispatch_results = []
        if sr_rules:
            for rule in sr_rules:
                r_type = str(rule.get("report_type", "all")).lower().strip()
                recipients = [normalize_recipient(t.strip()) for t in str(rule.get("target_recipients", "")).split(",") if t.strip()]
                if not recipients:
                    continue

                if r_type in ("adl_sr", "adl_sr_acso"):
                    imgs_to_send = [ADL_SR_REPORT_IMAGE_PATH]
                elif r_type in ("adtv_sr", "adtv_sr_acso"):
                    imgs_to_send = [ADTV_SR_REPORT_IMAGE_PATH]
                elif r_type in ("sr_combined", "sr_side_by_side", "combined_sr"):
                    imgs_to_send = [SR_REPORT_IMAGE_PATH]
                else:
                    imgs_to_send = [ADL_SR_REPORT_IMAGE_PATH, ADTV_SR_REPORT_IMAGE_PATH]

                rule_name = rule.get("rule_name") or f"Rule #{rule['id']}"
                print(f"[SR_CYCLE] Executing SR Dispatch Rule '{rule_name}' ({r_type}) to {len(recipients)} recipient(s): {recipients}...")
                sent_ok = flash_report_image(imgs_to_send, target_recipients=recipients)
                dispatch_results.append({
                    "rule_id": rule["id"],
                    "rule_name": rule_name,
                    "report_type": r_type,
                    "recipients": recipients,
                    "success": sent_ok,
                })

            if sr_rules and not any(d.get("success") for d in dispatch_results):
                failed_names = [d.get("rule_name") for d in dispatch_results if not d.get("success")]
                raise RuntimeError(f"WhatsApp dispatch failed for SR rule(s): {', '.join(failed_names)}. Check WhatsApp Web session.")
        else:
            print(f"[SR_CYCLE] No specific SR dispatch rules configured for region '{region_id}'. Reports saved locally.")

        db_manager.set_setting(f"last_sr_cycle_{region_id}", ts_now)
        db_manager.set_setting(f"last_sr_cycle_status_{region_id}", "Completed Successfully")

        return {
            "status": "OK",
            "message": "Service Request cycle completed successfully.",
            "timestamp": ts_now,
            "excel_path": str(excel_path),
            "images": [str(p) for p in img_paths],
            "dispatches": dispatch_results,
        }

    except Exception as e:
        err_msg = f"Service Request cycle failed: {e}"
        print(f"[SR_CYCLE ERROR] {err_msg}", file=sys.stderr)
        db_manager.set_setting(f"last_sr_cycle_status_{region_id}", f"Error: {e}")
        try:
            from telegram_bot import format_automated_error_alert, get_alert_retry_keyboard, broadcast_telegram_alert
            alert_text = format_automated_error_alert(
                pipeline="Service Request Pending",
                region_id=region_id,
                error_message=str(e),
                timestamp=ts_now,
            )
            kb = get_alert_retry_keyboard("sr")
            broadcast_telegram_alert(alert_text, reply_markup=kb)
        except Exception as alert_ex:
            print(f"[Telegram Alert Error] Failed to broadcast SR alert: {alert_ex}")
        return {
            "status": "ERROR",
            "message": str(e),
            "timestamp": ts_now,
        }


if __name__ == "__main__":
    print("Testing Service Request Engine...")
    res = execute_automated_sr_cycle(DEFAULT_REGION_ID)
    print("Result:", res)
