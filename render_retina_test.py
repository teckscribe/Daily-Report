import sys
from pathlib import Path
from PIL import Image
import xlrd
from playwright.sync_api import sync_playwright
from config import TARGET_EXCEL_PATH, OUTPUT_DIR

wb = xlrd.open_workbook(str(Path(TARGET_EXCEL_PATH).resolve()))
ws = wb.sheet_by_name("Post Paid & Prepaid")

def build_table_data(is_adtv=False):
    start_c = 16 if is_adtv else 0
    bucket_start_c = 19 if is_adtv else 3
    bucket_end_c = 31 if is_adtv else 15
    title = "ADTv Complaint Pending" if is_adtv else "ADL Complaint Pending"

    max_b_idx = 0
    for b_idx in range(bucket_end_c - bucket_start_c):
        col_c = bucket_start_c + b_idx
        col_sum = sum(float(ws.cell_value(r, col_c) or 0) for r in range(3, 25))
        if col_sum > 0:
            max_b_idx = b_idx
    
    active_b_count = max(2, max_b_idx + 1)
    bucket_names = [ws.cell_value(2, bucket_start_c + i) for i in range(active_b_count)]
    
    rows = []
    for r in range(3, 25):
        center = ws.cell_value(r, start_c)
        name = ws.cell_value(r, start_c + 1)
        gt = ws.cell_value(r, start_c + 2)
        buckets = [ws.cell_value(r, bucket_start_c + i) for i in range(active_b_count)]
        rows.append({"center": center, "name": name, "gt": gt, "buckets": buckets})
        
    return title, bucket_names, rows, is_adtv

def render_html(title, bucket_names, rows, is_adtv):
    num_b = len(bucket_names)
    thead_b_th = "".join(f'<th class="th-bucket">{b}</th>' for b in bucket_names)
    
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
                
        tbody_rows += f"""
        <tr>
            <td class="col-center">{row['center']}</td>
            <td class="col-name">{row['name']}</td>
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
            font-size: 19px;
            font-weight: bold;
            padding: 3px 8px;
            border-bottom: 2px solid #000000;
            height: 30px;
            line-height: 24px;
        }}
        table {{
            border-collapse: collapse;
            font-size: 16px;
            color: #000000;
        }}
        th, td {{
            border: 1px solid #7f7f7f;
            padding: 1.5px 7px;
            height: 24px;
            white-space: nowrap;
        }}
        thead th {{
            background-color: #d9d9d9;
            font-weight: bold;
            font-size: 16px;
            border: 1px solid #000000;
        }}
        .th-center {{ text-align: left; width: 230px; min-width: 230px; }}
        .th-name {{ text-align: left; width: 240px; min-width: 240px; }}
        .th-gt {{ text-align: center; width: 110px; min-width: 110px; }}
        .th-pending {{ text-align: center; }}
        .th-bucket {{ text-align: center; width: 75px; min-width: 75px; }}
        
        .col-center {{ text-align: left; font-size: 15.5px; font-weight: 500; }}
        .col-name {{ text-align: left; font-size: 15.5px; font-weight: 500; }}
        
        .gt-adl-val {{ text-align: center; font-weight: bold; font-size: 16px; background-color: #d9d9d9; }}
        .gt-adl-zero {{ text-align: center; background-color: #ffffff; }}
        
        .gt-adtv-val {{ text-align: center; font-weight: bold; font-size: 16px; background-color: #dce6f1; color: #000000; }}
        .gt-adtv-zero {{ text-align: center; font-size: 16px; background-color: #dce6f1; color: #a6b9d0; }}
        
        .cell-empty {{ background-color: #ffffff; }}
        .cell-green {{
            background-color: #00b050;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 16.5px;
        }}
        .cell-red {{
            background-color: #ff0000;
            color: #ffffff;
            font-weight: bold;
            text-align: center;
            font-size: 16.5px;
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

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome" if sys.platform == "win32" else None)
    page = browser.new_page(device_scale_factor=2.2)
    
    # 1. ADL
    t, b_names, r, is_tv = build_table_data(is_adtv=False)
    html_adl = render_html(t, b_names, r, is_tv)
    page.set_content(html_adl)
    p_adl = OUTPUT_DIR / "retina_adl.jpg"
    page.locator(".table-box").screenshot(path=str(p_adl.resolve()), type="jpeg", quality=95)
    
    # 2. ADTv
    t, b_names, r, is_tv = build_table_data(is_adtv=True)
    html_adtv = render_html(t, b_names, r, is_tv)
    page.set_content(html_adtv)
    p_adtv = OUTPUT_DIR / "retina_adtv.jpg"
    page.locator(".table-box").screenshot(path=str(p_adtv.resolve()), type="jpeg", quality=95)
    
    browser.close()

im_a = Image.open(str(p_adl))
im_tv = Image.open(str(p_adtv))
print(f"ADL Image: size={im_a.size}, ratio={im_a.width/im_a.height:.3f}")
print(f"ADTv Image: size={im_tv.size}, ratio={im_tv.width/im_tv.height:.3f}")
