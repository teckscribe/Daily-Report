import sys
from pathlib import Path
from PIL import Image
import pandas as pd
import xlrd
from playwright.sync_api import sync_playwright

from config import TARGET_EXCEL_PATH, OUTPUT_DIR

wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
ws = wb.sheet_by_name("Post Paid & Prepaid")

# ADL data
adl_rows = []
for r in range(3, 25):
    center = ws.cell_value(r, 0)
    name = ws.cell_value(r, 1)
    gt = ws.cell_value(r, 2)
    b_lt1 = ws.cell_value(r, 3)
    b_1d = ws.cell_value(r, 4)
    adl_rows.append({"CENTER": center, "Name": name, "Grand Total": gt, "< 1day": b_lt1, "1 day": b_1d})
df_adl = pd.DataFrame(adl_rows)

# ADTv data
adtv_rows = []
for r in range(3, 25):
    center = ws.cell_value(r, 16)
    name = ws.cell_value(r, 17)
    gt = ws.cell_value(r, 18)
    b_lt1 = ws.cell_value(r, 19)
    b_1d = ws.cell_value(r, 20)
    adtv_rows.append({"CENTER": center, "Name": name, "Grand Total": gt, "< 1day": b_lt1, "1 day": b_1d})
df_adtv = pd.DataFrame(adtv_rows)


def make_compact_html(title, df, is_adtv=False):
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
            font-family: Calibri, 'Segoe UI', Arial, sans-serif;
            display: inline-block;
            padding: 1px;
            -webkit-font-smoothing: antialiased;
        }}
        .table-box {{
            border: 1.5px solid #000000;
            display: inline-block;
            background: #ffffff;
        }}
        .banner {{
            background-color: #9c4108;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 2px 6px;
            border-bottom: 1.5px solid #000000;
            letter-spacing: 0.1px;
            height: 22px;
            line-height: 18px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 12px;
            color: #000000;
        }}
        th, td {{
            border: 1px solid #7f7f7f;
            padding: 1px 5px;
            height: 17.5px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 12px;
            border: 1px solid #000000;
        }}
        .th-center {{ text-align: left; width: 142px; min-width: 142px; }}
        .th-name {{ text-align: left; width: 155px; min-width: 155px; }}
        .th-gt {{ text-align: center; width: 75px; min-width: 75px; }}
        .th-pending {{ text-align: center; }}
        .th-bucket {{ text-align: center; width: 48px; min-width: 48px; }}
        
        .col-center {{ text-align: left; font-size: 12px; }}
        .col-name {{ text-align: left; font-size: 12px; }}
        
        .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 12px; background-color: #d9d9d9; }}
        .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
        
        .gt-adtv-val {{ text-align: center; font-weight: bold; font-size: 12px; background-color: #dce6f1; color: #000000; }}
        .gt-adtv-zero {{ text-align: center; font-size: 12px; background-color: #dce6f1; color: #a6b9d0; }}
        
        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 12px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 12px;
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
    # Render with device_scale_factor=2 for crisp Retina without distorting aspect ratio
    page = browser.new_page(device_scale_factor=2.0)

    # ADL
    page.set_content(make_compact_html("ADL Complaint Pending", df_adl, is_adtv=False))
    p_adl = OUTPUT_DIR / "compact_retina_adl.png"
    page.locator(".table-box").screenshot(path=str(p_adl.resolve()))

    # ADTv
    page.set_content(make_compact_html("ADTv Complaint Pending", df_adtv, is_adtv=True))
    p_adtv = OUTPUT_DIR / "compact_retina_adtv.png"
    page.locator(".table-box").screenshot(path=str(p_adtv.resolve()))

    browser.close()

img_adl = Image.open(str(p_adl))
img_adtv = Image.open(str(p_adtv))
print(f"Compact Retina ADL size: {img_adl.size} Ratio: {img_adl.width / img_adl.height:.3f}")
print(f"Compact Retina ADTv size: {img_adtv.size} Ratio: {img_adtv.width / img_adtv.height:.3f}")
