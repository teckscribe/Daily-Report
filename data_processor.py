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

BUCKET_COLUMNS = BUCKET_LABELS
REPORT_COLUMNS = ["CENTER", "Name", "Grand Total", *BUCKET_COLUMNS]


# --- Filtering (applied to raw portal downloads before they become 'ADL P' / 'ADTv P' / 'Prepaid') ---

def _casefold_eq(series: pd.Series, value: str) -> pd.Series:
    return series.astype(str).str.strip().str.casefold() == value.casefold()


def filter_adl(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or TARGET_REGION
    if "REGION" in f.columns:
        f = f[_casefold_eq(f["REGION"], target_reg)]
    if "COMPLAINTTYPE" in f.columns:
        f = f[_casefold_eq(f["COMPLAINTTYPE"], ADL_COMPLAINT_TYPE)]
    if "PROBLEMTYPE" in f.columns:
        pattern = "|".join(ADL_PROBLEM_TYPES)
        f = f[f["PROBLEMTYPE"].astype(str).str.strip().str.casefold().str.contains(pattern, regex=True, na=False)]
    return f


def filter_adtv(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or TARGET_REGION
    if "REGION" in f.columns:
        f = f[_casefold_eq(f["REGION"], target_reg)]
    if "COMPLAINTTYPE" in f.columns:
        f = f[_casefold_eq(f["COMPLAINTTYPE"], ADTV_COMPLAINT_TYPE)]
    return f


def filter_prepaid(df: pd.DataFrame, region: Optional[str] = None) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    target_reg = region or PREPAID_REGION
    region_col = next((c for c in f.columns if str(c).lower() == "region"), None)
    if region_col:
        f = f[_casefold_eq(f[region_col], target_reg)]
    ct_col = next((c for c in f.columns if str(c).lower() in ("complaint type", "complainttype")), None)
    if ct_col:
        f = f[f[ct_col].astype(str).str.strip().str.casefold().str.contains(PREPAID_COMPLAINT_TYPE.casefold(), na=False)]
    return f


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
