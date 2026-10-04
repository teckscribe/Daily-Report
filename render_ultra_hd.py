import sys
from pathlib import Path
from PIL import Image
import pandas as pd
import xlrd
from playwright.sync_api import sync_playwright

from config import (
    TARGET_EXCEL_PATH,
    OUTPUT_DIR,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    REPORT_IMAGE_PATH,
)

wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
ws = wb.sheet_by_name("Post Paid & Prepaid")

# Extract ADL data
adl_rows = []
for r in range(3, 25):
    center = ws.cell_value(r, 0)
    name = ws.cell_value(r, 1)
    gt = ws.cell_value(r, 2)
    b_lt1 = ws.cell_value(r, 3)
    b_1d = ws.cell_value(r, 4)
    adl_rows.append({"CENTER": center, "Name": name, "Grand Total": gt, "< 1day": b_lt1, "1 day": b_1d})
df_adl = pd.DataFrame(adl_rows)

# Extract ADTv data
adtv_rows = []
for r in range(3, 25):
    center = ws.cell_value(r, 16)
    name = ws.cell_value(r, 17)
    gt = ws.cell_value(r, 18)
    b_lt1 = ws.cell_value(r, 19)
    b_1d = ws.cell_value(r, 20)
    adtv_rows.append({"CENTER": center, "Name": name, "Grand Total": gt, "< 1day": b_lt1, "1 day": b_1d})
df_adtv = pd.DataFrame(adtv_rows)


def make_html(title, df, is_adtv=False):
    rows_html = ""
    for _, row in df.iterrows():
        gt = int(row["Grand Total"])
        if is_adtv:
            gt_cls = "gt-adtv-val" if gt > 0 else "gt-adtv-zero"
            gt_text = str(gt)
        else:
            gt_cls = "gt-adl-val" if gt > 0 else "gt-adl-zero"
            gt_text = str(gt) if gt > 0 else ""

        c_lt1 = int(row["< 1day"])
        c_1d = int(row["1 day"])

        t_lt1 = f'<td class="cell-green">{c_lt1}</td>' if c_lt1 > 0 else '<td class="cell-empty"></td>'
        t_1d = f'<td class="cell-red">{c_1d}</td>' if c_1d > 0 else '<td class="cell-empty"></td>'

        rows_html += f"""
        <tr>
            <td class="col-center">{row['CENTER']}</td>
            <td class="col-name">{row['Name']}</td>
            <td class="{gt_cls}">{gt_text}</td>
            {t_lt1}
            {t_1d}
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
            font-family: Arial, "Segoe UI", -apple-system, sans-serif;
            display: inline-block;
            padding: 3px;
        }}
        .table-box {{
            border: 2px solid #000000;
            display: inline-block;
            background: #ffffff;
        }}
        .banner {{
            background-color: #94380b;
            color: #ffffff;
            font-size: 20px;
            font-weight: bold;
            padding: 8px 14px;
            border-bottom: 2px solid #000000;
            letter-spacing: 0.3px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 16px;
            color: #000000;
        }}
        th, td {{
            border: 1.5px solid #000000;
            padding: 6px 12px;
            height: 32px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 16px;
        }}
        .th-center {{ text-align: left; width: 190px; }}
        .th-name {{ text-align: left; width: 210px; }}
        .th-gt {{ text-align: center; width: 110px; }}
        .th-pending {{ text-align: center; }}
        .th-bucket {{ text-align: center; width: 75px; }}
        
        .col-center {{ text-align: left; font-size: 15px; }}
        .col-name {{ text-align: left; font-size: 15px; }}
        
        .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 16px; background-color: #d9d9d9; }}
        .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
        
        .gt-adtv-val {{ text-align: center; font-weight: bold; font-size: 16px; background-color: #dce6f1; color: #000000; }}
        .gt-adtv-zero {{ text-align: center; font-size: 15px; background-color: #dce6f1; color: #9bb0c9; }}
        
        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 18px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 18px;
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
                        <th colspan="2" class="th-pending">Pending Days</th>
                    </tr>
                    <tr>
                        <th class="th-bucket">&lt; 1day</th>
                        <th class="th-bucket">1 day</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome" if sys.platform == "win32" else None)
    # High-density 2.5x device scale factor (Ultra HD Retina)
    page = browser.new_page(device_scale_factor=2.5)

    # Render ADL
    page.set_content(make_html("ADL Complaint Pending", df_adl, is_adtv=False))
    page.locator(".table-box").screenshot(path=str(ADL_REPORT_IMAGE_PATH.resolve()))
    print(f"SUCCESS! Rendered Ultra-HD ADL: {ADL_REPORT_IMAGE_PATH}")

    # Render ADTv
    page.set_content(make_html("ADTv Complaint Pending", df_adtv, is_adtv=True))
    page.locator(".table-box").screenshot(path=str(ADTV_REPORT_IMAGE_PATH.resolve()))
    print(f"SUCCESS! Rendered Ultra-HD ADTv: {ADTV_REPORT_IMAGE_PATH}")

    browser.close()

# Also make combined image
img_adl = Image.open(str(ADL_REPORT_IMAGE_PATH))
img_adtv = Image.open(str(ADTV_REPORT_IMAGE_PATH))
gap = 25
combined_w = img_adl.width + img_adtv.width + gap
combined_h = max(img_adl.height, img_adtv.height)
combined = Image.new("RGB", (combined_w, combined_h), color=(255, 255, 255))
combined.paste(img_adl, (0, 0))
combined.paste(img_adtv, (img_adl.width + gap, 0))
combined.save(str(REPORT_IMAGE_PATH.resolve()))
print(f"SUCCESS! Rendered Ultra-HD Combined: {REPORT_IMAGE_PATH} Size: {combined.size}")
