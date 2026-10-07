"""
data_processor.py
=================
1. Filters the raw CRM downloads (ADL / ADTv / Prepaid) - same rules as before.
2. Computes the report with report_engine (exact replica of the Excel formulas).
3. Optionally writes a dated WORKING COPY of the Excel tracker with the new data.

The golden template `Daily Complint Tracker.xls` is NEVER modified.
See docs/REPORT_GENERATION_REFERENCE.md.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    ADL_COMPLAINT_TYPE,
    ADL_PROBLEM_TYPES,
    ADTV_COMPLAINT_TYPE,
    OUTPUT_DIR,
    PREPAID_COMPLAINT_TYPE,
    PREPAID_REGION,
    TARGET_EXCEL_PATH,
    TARGET_REGION,
    DEFAULT_REGION_ID,
)
from report_engine import ReportResult, compute_report, validate_inputs
from report_layout import BUCKET_LABELS
import db_manager

BUCKET_COLUMNS = BUCKET_LABELS
REPORT_COLUMNS = ["CENTER", "Name", "Grand Total", *BUCKET_COLUMNS]


# --- Filtering (applied to raw portal downloads before they become 'ADL P' / 'ADTv P' / 'Prepaid') ---

def _casefold_eq(series: pd.Series, value: str) -> pd.Series:
    return series.astype(str).str.strip().str.casefold() == value.casefold()


def _find_column(df: pd.DataFrame, *names: str) -> Optional[str]:
    """Find a portal column despite harmless header case/space differences."""
    wanted = {name.strip().casefold() for name in names}
    return next((column for column in df.columns if str(column).strip().casefold() in wanted), None)


def _casefold_in(series: pd.Series, values: List[str]) -> pd.Series:
    allowed = {str(value).strip().casefold() for value in values}
    return series.astype(str).str.strip().str.casefold().isin(allowed)


def _filter_configured_centers(
    df: pd.DataFrame,
    region_id: Optional[str],
    source_columns: tuple[str, ...],
    center_key: str,
) -> pd.DataFrame:
    """Keep only exact center keys belonging to the selected region when available."""
    if df.empty or not region_id:
        return df
    try:
        center_rows = db_manager.get_centers(region_id)
    except Exception:
        return df
    allowed_centers = {
        str(row.get(center_key) or row.get("center_name") or "").strip().casefold()
        for row in center_rows
        if str(row.get(center_key) or row.get("center_name") or "").strip()
    }
    source_col = next(
        (column for column in df.columns if str(column).strip().casefold() in source_columns),
        None,
    )
    if not source_col or not allowed_centers:
        return df
    return df[df[source_col].astype(str).str.strip().str.casefold().isin(allowed_centers)].copy()


def filter_adl(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or TARGET_REGION
    region_col = _find_column(f, "REGION")
    complaint_type_col = _find_column(f, "COMPLAINTTYPE", "Complaint Type")
    problem_type_col = _find_column(f, "PROBLEMTYPE", "Problem Type")
    if region_col:
        f = f[_casefold_eq(f[region_col], target_reg)]
    if complaint_type_col:
        f = f[_casefold_eq(f[complaint_type_col], ADL_COMPLAINT_TYPE)]
    if problem_type_col:
        f = f[_casefold_in(f[problem_type_col], ADL_PROBLEM_TYPES)]
    return _filter_configured_centers(f, region, ("area", "center"), "adl_area_key")


def filter_adtv(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or TARGET_REGION
    region_col = _find_column(f, "REGION")
    complaint_type_col = _find_column(f, "COMPLAINTTYPE", "Complaint Type")
    if region_col:
        f = f[_casefold_eq(f[region_col], target_reg)]
    if complaint_type_col:
        f = f[_casefold_eq(f[complaint_type_col], ADTV_COMPLAINT_TYPE)]
    return _filter_configured_centers(f, region, ("serviceamo", "amo", "area"), "adtv_amo_key")


def filter_prepaid(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or PREPAID_REGION
    region_col = _find_column(f, "REGION")
    if region_col:
        f = f[_casefold_eq(f[region_col], target_reg)]
    ct_col = _find_column(f, "Complaint Type", "COMPLAINTTYPE")
    if ct_col:
        f = f[_casefold_eq(f[ct_col], PREPAID_COMPLAINT_TYPE)]
    return _filter_configured_centers(f, region, ("area", "center", "serviceamo", "amo"), "prepaid_area_key")


# --- Report computation ---

def compute_report_result(df_adl: pd.DataFrame, df_adtv: pd.DataFrame, df_prepaid: pd.DataFrame,
                          region_id: str = DEFAULT_REGION_ID, strict: bool = True) -> ReportResult:
    """Validate inputs, then compute all three report sheets exactly like the Excel workbook."""
    warnings = validate_inputs(df_adl, df_adtv, df_prepaid)
    for w in warnings:
        print(f"  [!] DATA WARNING {w}")
    if warnings and strict:
        raise ValueError("Input data failed integrity checks - report NOT generated:\n  " + "\n  ".join(warnings))
    return compute_report(df_adl, df_adtv, df_prepaid, region_id=region_id)


def compute_all_sections(df_adl: pd.DataFrame, df_adtv: pd.DataFrame, df_prepaid: pd.DataFrame,
                         region_id: str = DEFAULT_REGION_ID, strict: bool = True) -> Dict[str, pd.DataFrame]:
    """Backward-compatible wrapper: final 'Post Paid & Prepaid' tables as DataFrames."""
    result = compute_report_result(df_adl, df_adtv, df_prepaid, region_id=region_id, strict=strict)
    return {k: t.to_frame() for k, t in result.final.items()}


# --- Working copy of the Excel tracker (golden template stays untouched) ---

def write_working_copy(df_adl: pd.DataFrame, df_adtv: pd.DataFrame, df_prepaid: pd.DataFrame,
                       template_path: str = TARGET_EXCEL_PATH) -> Optional[Path]:
    """
    Copies the golden template to output/Daily Complint Tracker_<timestamp>.xls, pastes the
    new data into 'ADL P' / 'ADTv P' / 'Prepaid' (aligned BY HEADER NAME, so columns can never
    shift), recalculates and saves the COPY. Windows + Excel only; returns None otherwise.
    """
    template = Path(template_path)
    if sys.platform != "win32" or not template.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    copy_path = (OUTPUT_DIR / f"{template.stem}_{ts}{template.suffix}").resolve()
    shutil.copy2(template, copy_path)

    import win32com.client
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(str(copy_path))
        for sheet_name, df_data in {"ADL P": df_adl, "ADTv P": df_adtv, "Prepaid": df_prepaid}.items():
            ws = wb.Sheets(sheet_name)
            n_cols = ws.UsedRange.Columns.Count
            headers = [ws.Cells(1, c).Value for c in range(1, n_cols + 1)]
            n_rows = ws.UsedRange.Rows.Count
            if n_rows > 1:
                ws.Range(ws.Rows(2), ws.Rows(n_rows + 50)).ClearContents()
            if df_data.empty:
                continue
            records = []
            used: set = set()
            for _, r in df_data.iterrows():
                row_vals = []
                for h in headers:
                    # first unused source column with this header (handles duplicate TICKETNO)
                    match = next((c for c in df_data.columns
                                  if str(c).split(".")[0].strip().lower() == str(h or "").strip().lower()
                                  and (c, h) not in used), None)
                    v = r[match] if match is not None else ""
                    if pd.isna(v) if not isinstance(v, str) else False:
                        v = ""
                    elif isinstance(v, (np.integer,)):
                        v = int(v)
                    elif isinstance(v, (np.floating,)):
                        v = float(v)
                    row_vals.append(v)
                records.append(row_vals)
            ws.Range(ws.Cells(2, 1), ws.Cells(1 + len(records), len(headers))).Value = records
        excel.CalculateFull()
        wb.Save()
        wb.Close(False)
        print(f"[Excel] Working copy saved: {copy_path.name} (template untouched)")
        return copy_path
    except Exception as e:
        print(f"[Excel] Working copy failed: {e}")
        return None
    finally:
        excel.Quit()


def update_excel_file(df_adl, df_adtv, df_prepaid, target_path: str = TARGET_EXCEL_PATH):
    """Deprecated name kept for compatibility - now ONLY writes a dated working copy."""
    return write_working_copy(df_adl, df_adtv, df_prepaid, template_path=target_path)
