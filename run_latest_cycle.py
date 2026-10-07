"""
run_latest_cycle.py
===================
Pulls the latest tickets, filters them, computes the report,
renders all 4 high-DPI Retina images, writes an updated Excel working copy,
and delivers the reports to WhatsApp (+919633889430).
"""

import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

from config import (
    DATA_DIR,
    OUTPUT_DIR,
    TARGET_EXCEL_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
    DEFAULT_REGION_ID,
)
from crm_downloader import download_from_crm
from data_processor import (
    filter_adl,
    filter_adtv,
    filter_prepaid,
    write_working_copy,
)
from report_engine import compute_report, validate_inputs
from report_image_generator import generate_report_images, generate_acso_report_images
from whatsapp_sender import flash_report_image

def run():
    print("=" * 65)
    print(f"[CYCLE START] Running at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 1. Download latest from CRM
    adl_path, adtv_path, prep_path = download_from_crm(headless=True)
    print(f"\n[1/5] Downloaded complaint files:")
    print(f"  ADL:     {adl_path.name}")
    print(f"  ADTv:    {adtv_path.name}")
    print(f"  Prepaid: {prep_path.name}")

    # 2. Filter data
    print("\n[2/5] Filtering raw tickets...")
    raw_adl = pd.read_excel(adl_path)
    raw_adtv = pd.read_excel(adtv_path)
    raw_prep = pd.read_csv(prep_path) if str(prep_path).endswith(".csv") else pd.read_excel(prep_path)

    df_adl = filter_adl(raw_adl, region=DEFAULT_REGION_ID)
    df_adtv = filter_adtv(raw_adtv, region=DEFAULT_REGION_ID)
    df_prep = filter_prepaid(raw_prep, region=DEFAULT_REGION_ID)

    print(f"  ADL Records:     {len(df_adl)} (from {len(raw_adl)})")
    print(f"  ADTv Records:    {len(df_adtv)} (from {len(raw_adtv)})")
    print(f"  Prepaid Records: {len(df_prep)} (from {len(raw_prep)})")

    # Validate inputs
    warnings = validate_inputs(df_adl, df_adtv, df_prep)
    if warnings:
        print("\n[!] Input Warnings detected:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  Input validation: 100% PASS (Zero header shifts)")

    # 3. Compute equations
    print("\n[3/5] Computing report tables with pure-Python engine...")
    result = compute_report(df_adl, df_adtv, df_prep, region_id=DEFAULT_REGION_ID)

    adl_tot = result.final["adl_acso"].total.grand_total
    adtv_tot = result.final["adtv_acso"].total.grand_total
    adl_post = result.pending_days["adl_acso"].total.grand_total
    adl_pre = result.prepaid_pending["adl_acso"].total.grand_total
    adtv_post = result.pending_days["adtv_acso"].total.grand_total
    adtv_pre = result.prepaid_pending["adtv_acso"].total.grand_total

    print(f"  [RESULT] ADL Broadband Grand Total:  {adl_tot} ({adl_post} postpaid + {adl_pre} prepaid)")
    print(f"  [RESULT] ADTv Digital TV Grand Total: {adtv_tot} ({adtv_post} postpaid + {adtv_pre} prepaid)")

    # 4. Save working copy of Excel (Golden file remains untouched)
    print("\n[4/5] Creating dated working copy of Excel workbook...")
    try:
        copy_path = write_working_copy(df_adl, df_adtv, df_prep, template_path=TARGET_EXCEL_PATH)
        if copy_path:
            print(f"  [+] Saved: {copy_path.name}")
        else:
            print("  [!] Notice: Excel win32com working copy generation skipped.")
    except Exception as e:
        print(f"  [!] Notice: {e}")

    # 5. Render High-DPI Retina report images
    print("\n[5/5] Rendering High-Definition Retina report images...")
    df_sections = {
        "adl_team": result.final["adl_team"].to_frame(),
        "adtv_team": result.final["adtv_team"].to_frame(),
        "adl_acso": result.final["adl_acso"].to_frame(),
        "adtv_acso": result.final["adtv_acso"].to_frame(),
    }
    tl_images = generate_report_images(df_sections)
    acso_images = generate_acso_report_images(df_sections)
    all_images = tl_images + acso_images
    for img in all_images:
        print(f"  [+] Rendered: {img.name}")

    # 6. Dispatch to WhatsApp
    print("\n[6/6] Dispatching all 4 report cards to WhatsApp (+919633889430)...")
    images_to_flash = [
        ADL_REPORT_IMAGE_PATH,
        ADTV_REPORT_IMAGE_PATH,
        ADL_ACSO_REPORT_IMAGE_PATH,
        ADTV_ACSO_REPORT_IMAGE_PATH,
    ]
    success = flash_report_image(images_to_flash, target_recipients=["+919633889430"])
    if success:
        print("  [SUCCESS] All 4 report cards delivered to WhatsApp!")
    else:
        print("  [!] WhatsApp dispatch failed or skipped.")

    print("\n" + "=" * 65)
    print(f"[CYCLE COMPLETE] Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

if __name__ == "__main__":
    run()
