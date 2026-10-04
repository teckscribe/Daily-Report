import sys
from pathlib import Path
from PIL import Image
import pandas as pd
import xlrd
from playwright.sync_api import sync_playwright

from config import TARGET_EXCEL_PATH, OUTPUT_DIR

wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
ws = wb.sheet_by_name("Post Paid & Prepaid")

adl_rows = []
for r in range(3, 25):
    adl_rows.append({
        "CENTER": ws.cell_value(r, 0),
        "Name": ws.cell_value(r, 1),
        "Grand Total": ws.cell_value(r, 2),
        "< 1day": ws.cell_value(r, 3),
        "1 day": ws.cell_value(r, 4),
    })
df_adl = pd.DataFrame(adl_rows)

rows_html = ""
for _, row in df_adl.iterrows():
    gt = int(row["Grand Total"])
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

html = f"""<!DOCTYPE html>
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
        font-size: 19px;
        font-weight: bold;
        padding: 4px 8px;
        border-bottom: 2px solid #000000;
        height: 32px;
        line-height: 24px;
    }}
    table {{
        border-collapse: collapse;
        font-size: 16.5px;
        color: #000000;
    }}
    th, td {{
        border: 1px solid #7f7f7f;
        padding: 2px 7px;
        height: 24px;
        white-space: nowrap;
    }}
    thead th {{
        background-color: #d9d9d9;
        font-weight: bold;
        font-size: 16.5px;
        border: 1px solid #000000;
    }}
    .th-center {{ text-align: left; width: 200px; min-width: 200px; }}
    .th-name {{ text-align: left; width: 220px; min-width: 220px; }}
    .th-gt {{ text-align: center; width: 105px; min-width: 105px; }}
    .th-pending {{ text-align: center; }}
    .th-bucket {{ text-align: center; width: 68px; min-width: 68px; }}
    
    .col-center {{ text-align: left; font-size: 16px; }}
    .col-name {{ text-align: left; font-size: 16px; }}
    
    .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 16px; background-color: #d9d9d9; }}
    .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
    
    .cell-empty {{ background-color: #ffffff; }}
    .cell-green {{
        background-color: #00b050;
        color: #ffffff;
        font-weight: bold;
        text-align: center;
        font-size: 17px;
    }}
    .cell-red {{
        background-color: #ff0000;
        color: #ffffff;
        font-weight: bold;
        text-align: center;
        font-size: 17px;
    }}
</style>
</head>
<body>
    <div class="table-box">
        <div class="banner">ADL Complaint Pending</div>
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
    page = browser.new_page(device_scale_factor=2.4)
    page.set_content(html)
    p_adl = OUTPUT_DIR / "test_scale_adl.jpg"
    page.locator(".table-box").screenshot(path=str(p_adl.resolve()), type="jpeg", quality=95)
    browser.close()

im = Image.open(str(p_adl))
print(f"SUCCESS! New Scaled ADL Image: {p_adl.name} Size: {im.size} Ratio: {im.width / im.height:.3f}")
