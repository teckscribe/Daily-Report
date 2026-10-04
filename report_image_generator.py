import html
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from PIL import Image
import pandas as pd
import xlrd
from playwright.sync_api import sync_playwright

from config import (
    REPORT_IMAGE_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
    TARGET_EXCEL_PATH,
    OUTPUT_DIR,
)


def extract_table_data_from_dataframe(df: pd.DataFrame, is_adtv: bool = False) -> Tuple[str, List[str], List[dict]]:
    """Extracts table data directly from computed DataFrame without requiring Excel file read."""
    title = "ADTv Complaint Pending" if is_adtv else "ADL Complaint Pending"
    bucket_cols = [c for c in df.columns if c not in ("CENTER", "Name", "Grand Total")]
    
    # Determine longest non-zero bucket
    max_b_idx = 1
    for idx, b_col in enumerate(bucket_cols):
        col_sum = pd.to_numeric(df[b_col], errors="coerce").fillna(0).sum()
        if col_sum > 0:
            max_b_idx = max(max_b_idx, idx)

    active_b_count = max_b_idx + 1
    active_buckets = bucket_cols[:active_b_count]

    rows = []
    for _, r in df.iterrows():
        center = str(r.get("CENTER", "")).strip()
        name = str(r.get("Name", "")).strip()
        gt = r.get("Grand Total", 0)
        buckets = [r.get(b, 0) for b in active_buckets]
        rows.append({"center": center, "name": name, "gt": gt, "buckets": buckets})

    return title, active_buckets, rows


def extract_table_data_from_excel(is_adtv: bool = False) -> Tuple[str, List[str], List[dict]]:
    """
    Extracts table data from Excel workbook and dynamically detects active pending day columns.
    Only includes columns up to the longest pending complaint.
    Always includes at least '< 1day' and '1 day'.
    """
    wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
    ws = wb.sheet_by_name("Post Paid & Prepaid")

    start_c = 16 if is_adtv else 0
    bucket_start_c = 19 if is_adtv else 3
    bucket_end_c = min(ws.ncols, 31 if is_adtv else 15)
    title = "ADTv Complaint Pending" if is_adtv else "ADL Complaint Pending"

    # Find longest pending bucket with non-zero complaints
    max_b_idx = 1  # Default to at least index 1 ('1 day')
    for b_idx in range(bucket_end_c - bucket_start_c):
        col_c = bucket_start_c + b_idx
        col_sum = sum(float(ws.cell_value(r, col_c) or 0) for r in range(3, 25))
        if col_sum > 0:
            max_b_idx = max(max_b_idx, b_idx)

    active_b_count = max_b_idx + 1
    bucket_names = [str(ws.cell_value(2, bucket_start_c + i)).strip() for i in range(active_b_count)]

    rows = []
    for r in range(3, 25):
        center = str(ws.cell_value(r, start_c)).strip()
        name = str(ws.cell_value(r, start_c + 1)).strip()
        gt = ws.cell_value(r, start_c + 2)
        buckets = [ws.cell_value(r, bucket_start_c + i) for i in range(active_b_count)]
        rows.append({"center": center, "name": name, "gt": gt, "buckets": buckets})

    return title, bucket_names, rows


def generate_table_html(title: str, bucket_names: List[str], rows: List[dict], is_adtv: bool) -> str:
    """
    Generates pixel-perfect HTML table styled exactly like the user's manual report.
    Proportions and typography are calibrated for ultra-sharp Retina rendering.
    """
    esc_title = html.escape(title)
    num_b = len(bucket_names)
    thead_b_th = "".join(f'<th class="th-bucket">{html.escape(b)}</th>' for b in bucket_names)

    tbody_rows = ""
    for row in rows:
        gt_val = int(float(row["gt"] or 0))
        if is_adtv:
            gt_cls = "gt-adtv-val" if gt_val > 0 else "gt-adtv-zero"
            gt_text = str(gt_val)
        else:
            gt_cls = "gt-adl-val" if gt_val > 0 else "gt-adl-zero"
            gt_text = str(gt_val) if gt_val > 0 else ""

        b_tds = ""
        for i, val in enumerate(row["buckets"]):
            v = int(float(val or 0))
            if v > 0:
                cls = "cell-green" if i == 0 else "cell-red"
                b_tds += f'<td class="{cls}">{v}</td>'
            else:
                b_tds += '<td class="cell-empty"></td>'

        esc_center = html.escape(str(row['center']))
        esc_name = html.escape(str(row['name']))

        tbody_rows += f"""
        <tr>
            <td class="col-center">{esc_center}</td>
            <td class="col-name">{esc_name}</td>
            <td class="{gt_cls}">{gt_text}</td>
            {b_tds}
        </tr>
        """

    return f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #ffffff;
            font-family: Calibri, 'Segoe UI', Arial, sans-serif;
            display: inline-block;
            padding: 2px;
            -webkit-font-smoothing: antialiased;
        }}
        .table-box {{
            border: 2px solid #000000;
            display: inline-block;
            background: #ffffff;
        }}
        .banner {{
            background-color: #9c4108;
            color: #ffffff;
            font-size: 24px;
            font-weight: bold;
            padding: 6px 10px;
            border-bottom: 2px solid #000000;
            height: 40px;
            line-height: 28px;
            letter-spacing: 0.3px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 18.5px;
            color: #000000;
        }}
        th, td {{
            border: 1px solid #7f7f7f;
            padding: 3px 8px;
            height: 33px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 18px;
            border: 1px solid #000000;
        }}
        .th-center {{ text-align: left; width: 235px; min-width: 235px; }}
        .th-name {{ text-align: left; width: 245px; min-width: 245px; }}
        .th-gt {{ text-align: center; width: 110px; min-width: 110px; }}
        .th-pending {{ text-align: center; }}
        .th-bucket {{ text-align: center; width: 70px; min-width: 70px; }}
        
        .col-center {{ text-align: left; font-size: 18px; font-weight: bold; color: #000000; }}
        .col-name {{ text-align: left; font-size: 18px; font-weight: bold; color: #000000; }}
        
        .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 19px; background-color: #d9d9d9; color: #000000; }}
        .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
        
        .gt-adtv-val {{ text-align: center; font-weight: bold; font-size: 19px; background-color: #dce6f1; color: #000000; }}
        .gt-adtv-zero {{ text-align: center; font-size: 18px; font-weight: bold; background-color: #dce6f1; color: #a6b9d0; }}
        
        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 19px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 19px;
        }}
    </style>
    </head>
    <body>
        <div class="table-box">
            <div class="banner">{title}</div>
            <table>
                <thead>
                    <tr>
                        <th rowspan="2" class="th-center">CENTER</th>
                        <th rowspan="2" class="th-name">TeamLeaderName</th>
                        <th rowspan="2" class="th-gt">Grand Total</th>
                        <th colspan="{num_b}" class="th-pending">Pending Days</th>
                    </tr>
                    <tr>
                        {thead_b_th}
                    </tr>
                </thead>
                <tbody>
                    {tbody_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


def generate_report_images(sections: Dict[str, pd.DataFrame] = None) -> List[Path]:
    """
    Renders high-definition Retina report images (1600px+ width) using Playwright.
    Ensures images fill 100% of the WhatsApp mobile chat bubble without shrinking,
    and works natively on both Windows and headless Ubuntu Linux.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract ADL data
    if sections and "adl_team" in sections:
        adl_title, adl_buckets, adl_rows = extract_table_data_from_dataframe(sections["adl_team"], is_adtv=False)
    else:
        adl_title, adl_buckets, adl_rows = extract_table_data_from_excel(is_adtv=False)
    html_adl = generate_table_html(adl_title, adl_buckets, adl_rows, is_adtv=False)

    # 2. Extract ADTv data
    if sections and "adtv_team" in sections:
        adtv_title, adtv_buckets, adtv_rows = extract_table_data_from_dataframe(sections["adtv_team"], is_adtv=True)
    else:
        adtv_title, adtv_buckets, adtv_rows = extract_table_data_from_excel(is_adtv=True)
    html_adtv = generate_table_html(adtv_title, adtv_buckets, adtv_rows, is_adtv=True)

    # 3. Render via Playwright with 2.2x scale factor for crisp 1600px+ width
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if sys.platform == "win32":
            launch_kwargs["channel"] = "chrome"

        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as e_launch:
            if "channel" in launch_kwargs:
                launch_kwargs.pop("channel", None)
                browser = p.chromium.launch(**launch_kwargs)
            else:
                raise e_launch

        page = browser.new_page(device_scale_factor=2.4)

        # Render ADL Image (Saved as JPEG for perfect WhatsApp mobile display)
        page.set_content(html_adl)
        page.locator(".table-box").screenshot(
            path=str(ADL_REPORT_IMAGE_PATH.resolve()),
            type="jpeg",
            quality=95,
        )
        img_adl = Image.open(str(ADL_REPORT_IMAGE_PATH))
        print(f"[OK] Rendered Retina ADL: {ADL_REPORT_IMAGE_PATH.name} (Size: {img_adl.size}, Ratio: {img_adl.width/img_adl.height:.3f})")

        # Render ADTv Image
        page.set_content(html_adtv)
        page.locator(".table-box").screenshot(
            path=str(ADTV_REPORT_IMAGE_PATH.resolve()),
            type="jpeg",
            quality=95,
        )
        img_adtv = Image.open(str(ADTV_REPORT_IMAGE_PATH))
        print(f"[OK] Rendered Retina ADTv: {ADTV_REPORT_IMAGE_PATH.name} (Size: {img_adtv.size}, Ratio: {img_adtv.width/img_adtv.height:.3f})")

        browser.close()

    # 4. Also generate side-by-side combined image for archiving
    gap = 30
    combined_w = img_adl.width + img_adtv.width + gap
    combined_h = max(img_adl.height, img_adtv.height)
    combined = Image.new("RGB", (combined_w, combined_h), color=(255, 255, 255))
    combined.paste(img_adl, (0, 0))
    combined.paste(img_adtv, (img_adl.width + gap, 0))
    combined.save(str(REPORT_IMAGE_PATH.resolve()), "JPEG", quality=95)
    print(f"[OK] Saved Combined Image: {REPORT_IMAGE_PATH.name} ({combined.size})")

    return [ADL_REPORT_IMAGE_PATH, ADTV_REPORT_IMAGE_PATH]


def extract_acso_table_data_from_dataframe(df: pd.DataFrame, is_adtv: bool = False) -> Tuple[str, List[str], List[dict], dict]:
    """Extracts ACSO table data and Grand Total row directly from computed DataFrame."""
    title = "ADTv Complaint Pending (ACSO)" if is_adtv else "ADL Complaint Pending (ACSO)"
    bucket_cols = [c for c in df.columns if c not in ("CENTER", "Name", "Grand Total")]

    # Determine longest non-zero bucket
    max_b_idx = 1
    for idx, b_col in enumerate(bucket_cols):
        col_sum = pd.to_numeric(df[b_col], errors="coerce").fillna(0).sum()
        if col_sum > 0:
            max_b_idx = max(max_b_idx, idx)

    active_b_count = max_b_idx + 1
    active_buckets = bucket_cols[:active_b_count]

    rows = []
    total_row = None
    for _, r in df.iterrows():
        center = str(r.get("CENTER", "")).strip()
        name = str(r.get("Name", "")).strip()
        gt = r.get("Grand Total", 0)
        buckets = [r.get(b, 0) for b in active_buckets]
        if center.casefold() == "grand total":
            total_row = {"center": "Grand Total", "name": "", "gt": gt, "buckets": buckets}
        else:
            rows.append({"center": center, "name": name, "gt": gt, "buckets": buckets})

    if not total_row:
        gt_tot = sum(int(float(r["gt"] or 0)) for r in rows)
        tot_buckets = [sum(int(float(r["buckets"][i] or 0)) for r in rows) for i in range(active_b_count)]
        total_row = {"center": "Grand Total", "name": "", "gt": gt_tot, "buckets": tot_buckets}

    return title, active_buckets, rows, total_row


def extract_acso_table_data_from_excel(is_adtv: bool = False) -> Tuple[str, List[str], List[dict], dict]:
    """
    Extracts ACSO table data from Excel workbook sheet 'Post Paid & Prepaid' (Rows 33-45 plus Row 46 Grand Total).
    Dynamically detects active pending day columns up to the longest pending complaint.
    """
    wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
    ws = wb.sheet_by_name("Post Paid & Prepaid")

    start_c = 16 if is_adtv else 0
    bucket_start_c = 19 if is_adtv else 3
    bucket_end_c = min(ws.ncols, 31 if is_adtv else 15)
    title = "ADTv Complaint Pending (ACSO)" if is_adtv else "ADL Complaint Pending (ACSO)"

    # Rows 33 to 45 in Excel correspond to 0-based indices 32 to 44
    # Row 46 is index 45 (Grand Total)
    max_b_idx = 1
    for b_idx in range(bucket_end_c - bucket_start_c):
        col_c = bucket_start_c + b_idx
        col_sum = sum(float(ws.cell_value(r, col_c) or 0) for r in range(32, 46))
        if col_sum > 0:
            max_b_idx = max(max_b_idx, b_idx)

    active_b_count = max_b_idx + 1
    bucket_names = [str(ws.cell_value(31, bucket_start_c + i)).strip() for i in range(active_b_count)]

    rows = []
    for r in range(32, 45):
        center = str(ws.cell_value(r, start_c)).strip()
        name = str(ws.cell_value(r, start_c + 1)).strip()
        gt = ws.cell_value(r, start_c + 2)
        buckets = [ws.cell_value(r, bucket_start_c + i) for i in range(active_b_count)]
        rows.append({"center": center, "name": name, "gt": gt, "buckets": buckets})

    # Grand Total row (Row 46 / index 45)
    gt_tot = ws.cell_value(45, start_c + 2)
    tot_buckets = [ws.cell_value(45, bucket_start_c + i) for i in range(active_b_count)]
    total_row = {"center": "Grand Total", "name": "", "gt": gt_tot, "buckets": tot_buckets}

    return title, bucket_names, rows, total_row


def generate_acso_table_html(title: str, bucket_names: List[str], rows: List[dict], total_row: dict, is_adtv: bool) -> str:
    """
    Generates pixel-perfect HTML table for ACSO report including the bottom Grand Total row.
    """
    esc_title = html.escape(title)
    num_b = len(bucket_names)
    thead_b_th = "".join(f'<th class="th-bucket">{html.escape(b)}</th>' for b in bucket_names)

    tbody_rows = ""
    for row in rows:
        gt_val = int(float(row["gt"] or 0))
        if is_adtv:
            gt_cls = "gt-adtv-val" if gt_val > 0 else "gt-adtv-zero"
            gt_text = str(gt_val)
        else:
            gt_cls = "gt-adl-val" if gt_val > 0 else "gt-adl-zero"
            gt_text = str(gt_val) if gt_val > 0 else ""

        b_tds = ""
        for i, val in enumerate(row["buckets"]):
            v = int(float(val or 0))
            if v > 0:
                cls = "cell-green" if i == 0 else "cell-red"
                b_tds += f'<td class="{cls}">{v}</td>'
            else:
                b_tds += '<td class="cell-empty"></td>'

        esc_center = html.escape(str(row['center']))
        esc_name = html.escape(str(row['name']))

        tbody_rows += f"""
        <tr>
            <td class="col-center">{esc_center}</td>
            <td class="col-name">{esc_name}</td>
            <td class="{gt_cls}">{gt_text}</td>
            {b_tds}
        </tr>
        """

    # Format Grand Total row
    tot_gt_val = int(float(total_row["gt"] or 0))
    tot_gt_cls = "gt-total-adtv" if is_adtv else "gt-total-adl"
    tot_label_cls = "label-total-adtv" if is_adtv else "label-total-adl"

    tot_b_tds = ""
    for i, val in enumerate(total_row["buckets"]):
        v = int(float(val or 0))
        if v > 0:
            cls = "cell-green font-total" if i == 0 else "cell-red font-total"
            tot_b_tds += f'<td class="{cls}">{v}</td>'
        else:
            tot_b_tds += '<td class="cell-empty border-total"></td>'

    tbody_rows += f"""
    <tr class="row-total">
        <td colspan="2" class="{tot_label_cls}">Grand Total</td>
        <td class="{tot_gt_cls}">{tot_gt_val}</td>
        {tot_b_tds}
    </tr>
    """

    return f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #ffffff;
            font-family: Calibri, 'Segoe UI', Arial, sans-serif;
            display: inline-block;
            padding: 2px;
            -webkit-font-smoothing: antialiased;
        }}
        .table-box {{
            border: 2px solid #000000;
            display: inline-block;
            background: #ffffff;
        }}
        .banner {{
            background-color: #9c4108;
            color: #ffffff;
            font-size: 26px;
            font-weight: bold;
            padding: 6px 12px;
            border-bottom: 2px solid #000000;
            height: 42px;
            line-height: 30px;
            letter-spacing: 0.3px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 20px;
            color: #000000;
        }}
        th, td {{
            border: 1px solid #7f7f7f;
            padding: 5px 8px;
            height: 40px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 19px;
            border: 1px solid #000000;
        }}
        .th-center {{ text-align: left; width: 220px; min-width: 220px; }}
        .th-name {{ text-align: left; width: 230px; min-width: 230px; }}
        .th-gt {{ text-align: center; width: 105px; min-width: 105px; }}
        .th-pending {{ text-align: center; }}
        .th-bucket {{ text-align: center; width: 68px; min-width: 68px; }}
        
        .col-center {{ text-align: left; font-size: 20px; font-weight: bold; color: #000000; }}
        .col-name {{ text-align: left; font-size: 20px; font-weight: bold; color: #000000; }}
        
        .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 21px; background-color: #d9d9d9; color: #000000; }}
        .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
        
        .gt-adtv-val {{ text-align: center; font-weight: bold; font-size: 21px; background-color: #dce6f1; color: #000000; }}
        .gt-adtv-zero {{ text-align: center; font-size: 19px; font-weight: bold; background-color: #dce6f1; color: #a6b9d0; }}
        
        .label-total-adl {{
            text-align: center;
            font-weight: bold;
            font-size: 21px;
            background-color: #d9d9d9;
            color: #000000;
            border-top: 2px solid #000000;
        }}
        .label-total-adtv {{
            text-align: center;
            font-weight: bold;
            font-size: 21px;
            background-color: #dce6f1;
            color: #000000;
            border-top: 2px solid #000000;
        }}
        .gt-total-adl {{
            text-align: center;
            font-weight: bold;
            font-size: 22px;
            background-color: #d9d9d9;
            color: #000000;
            border-top: 2px solid #000000;
        }}
        .gt-total-adtv {{
            text-align: center;
            font-weight: bold;
            font-size: 22px;
            background-color: #dce6f1;
            color: #000000;
            border-top: 2px solid #000000;
        }}
        .font-total {{
            font-size: 21px;
            font-weight: bold;
            border-top: 2px solid #000000;
        }}
        .border-total {{
            border-top: 2px solid #000000;
        }}
        
        .row-total td {{
            border-top: 2px solid #000000;
            border-bottom: 2px solid #000000;
            height: 46px;
        }}

        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 21px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 21px;
        }}
    </style>
    </head>
    <body>
        <div class="table-box">
            <div class="banner">{title}</div>
            <table>
                <thead>
                    <tr>
                        <th rowspan="2" class="th-center">CENTER</th>
                        <th rowspan="2" class="th-name">ACSO</th>
                        <th rowspan="2" class="th-gt">Grand Total</th>
                        <th colspan="{num_b}" class="th-pending">Pending Days</th>
                    </tr>
                    <tr>
                        {thead_b_th}
                    </tr>
                </thead>
                <tbody>
                    {tbody_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


def generate_acso_report_images(sections: Dict[str, pd.DataFrame] = None) -> List[Path]:
    """
    Renders high-definition Retina ACSO report images (1600px+ width) using Playwright.
    Generates ADL_ACSO_Complaint_Pending.jpg and ADTv_ACSO_Complaint_Pending.jpg.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract ADL ACSO data
    if sections and "adl_acso" in sections:
        adl_title, adl_buckets, adl_rows, adl_tot = extract_acso_table_data_from_dataframe(sections["adl_acso"], is_adtv=False)
    else:
        adl_title, adl_buckets, adl_rows, adl_tot = extract_acso_table_data_from_excel(is_adtv=False)
    html_adl = generate_acso_table_html(adl_title, adl_buckets, adl_rows, adl_tot, is_adtv=False)

    # 2. Extract ADTv ACSO data
    if sections and "adtv_acso" in sections:
        adtv_title, adtv_buckets, adtv_rows, adtv_tot = extract_acso_table_data_from_dataframe(sections["adtv_acso"], is_adtv=True)
    else:
        adtv_title, adtv_buckets, adtv_rows, adtv_tot = extract_acso_table_data_from_excel(is_adtv=True)
    html_adtv = generate_acso_table_html(adtv_title, adtv_buckets, adtv_rows, adtv_tot, is_adtv=True)

    # 3. Render via Playwright with 2.2x scale factor for crisp 1600px+ width
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if sys.platform == "win32":
            launch_kwargs["channel"] = "chrome"

        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as e_launch:
            if "channel" in launch_kwargs:
                launch_kwargs.pop("channel", None)
                browser = p.chromium.launch(**launch_kwargs)
            else:
                raise e_launch

        page = browser.new_page(device_scale_factor=2.4)

        # Render ADL ACSO Image
        page.set_content(html_adl)
        page.locator(".table-box").screenshot(
            path=str(ADL_ACSO_REPORT_IMAGE_PATH.resolve()),
            type="jpeg",
            quality=95,
        )
        img_adl = Image.open(str(ADL_ACSO_REPORT_IMAGE_PATH))
        print(f"[OK] Rendered Retina ADL ACSO: {ADL_ACSO_REPORT_IMAGE_PATH.name} (Size: {img_adl.size}, Ratio: {img_adl.width/img_adl.height:.3f})")

        # Render ADTv ACSO Image
        page.set_content(html_adtv)
        page.locator(".table-box").screenshot(
            path=str(ADTV_ACSO_REPORT_IMAGE_PATH.resolve()),
            type="jpeg",
            quality=95,
        )
        img_adtv = Image.open(str(ADTV_ACSO_REPORT_IMAGE_PATH))
        print(f"[OK] Rendered Retina ADTv ACSO: {ADTV_ACSO_REPORT_IMAGE_PATH.name} (Size: {img_adtv.size}, Ratio: {img_adtv.width/img_adtv.height:.3f})")

        browser.close()

    return [ADL_ACSO_REPORT_IMAGE_PATH, ADTV_ACSO_REPORT_IMAGE_PATH]


def generate_all_report_images(sections: Dict[str, pd.DataFrame] = None) -> Dict[str, List[Path]]:
    """Generates both Team Leader and ACSO report images."""
    tl_images = generate_report_images(sections)
    acso_images = generate_acso_report_images(sections)
    return {"team_leader": tl_images, "acso": acso_images}


if __name__ == "__main__":
    print("--- Generating Team Leader Report Images ---")
    generate_report_images()
    print("\n--- Generating ACSO Report Images ---")
    generate_acso_report_images()

