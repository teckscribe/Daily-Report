import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
import pandas as pd

# Ensure UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import logger_setup
logger_setup.init_logging()

from config import (
    REPORT_IMAGE_PATH,
    ADL_REPORT_IMAGE_PATH,
    ADTV_REPORT_IMAGE_PATH,
    ADL_ACSO_REPORT_IMAGE_PATH,
    ADTV_ACSO_REPORT_IMAGE_PATH,
    TARGET_EXCEL_PATH,
    SCHEDULE_TIMES,
    WHATSAPP_GROUPS,
    DEFAULT_REGION_ID,
)
from crm_downloader import download_from_crm, get_latest_local_downloads
from data_processor import (
    filter_adl,
    filter_adtv,
    filter_prepaid,
    compute_all_sections,
    ensure_region_directory_ready,
    update_excel_file,
)
from report_image_generator import generate_report_images, generate_acso_report_images
from whatsapp_sender import flash_report_image


def execute_cycle(download_online: bool = True, send_whatsapp: bool = True, region_id: str = DEFAULT_REGION_ID) -> bool:
    """Executes the complete operational pipeline."""
    now = datetime.now()
    print("=" * 60)
    print(f"[START] EXECUTING DAILY COMPLAINT REPORT CYCLE: {now.strftime('%d-%b-%Y %I:%M:%S %p')}")
    print("=" * 60)
    ensure_region_directory_ready(region_id)

    # 1. Download or retrieve raw complaint files
    if download_online:
        print("\n[Step 1/5] Fetching pending complaint files from CRM...")
        adl_path, adtv_path, prep_path = download_from_crm(
            headless=False if sys.platform == "win32" else True,
            region=region_id,
        )
    else:
        print("\n[Step 1/5] Loading latest local downloaded files...")
        adl_path, adtv_path, prep_path = get_latest_local_downloads()

    if not (adl_path and adtv_path and prep_path):
        print("[!] Error: Missing required files. Aborting cycle.")
        return False

    print(f"  [+] ADL Source:     {adl_path.name}")
    print(f"  [+] ADTv Source:    {adtv_path.name}")
    print(f"  [+] Prepaid Source: {prep_path.name}")

    # 2. Filter data
    print("\n[Step 2/5] Applying filtering rules...")
    raw_adl = pd.read_excel(adl_path)
    raw_adtv = pd.read_excel(adtv_path)
    raw_prep = pd.read_csv(prep_path) if str(prep_path).endswith(".csv") else pd.read_excel(prep_path)

    df_adl = filter_adl(raw_adl, region=region_id)
    df_adtv = filter_adtv(raw_adtv, region=region_id)
    df_prep = filter_prepaid(raw_prep, region=region_id)

    print(f"  [+] Filtered ADL:     {len(df_adl)} records (from {len(raw_adl)})")
    print(f"  [+] Filtered ADTv:    {len(df_adtv)} records (from {len(raw_adtv)})")
    print(f"  [+] Filtered Prepaid: {len(df_prep)} records (from {len(raw_prep)})")

    # 3. Compute equations & update Excel report
    print("\n[Step 3/5] Calculating pending days equations & updating Excel report...")
    sections = compute_all_sections(df_adl, df_adtv, df_prep, region_id=region_id)
    update_excel_file(df_adl, df_adtv, df_prep, target_path=TARGET_EXCEL_PATH)
    print("  [+] Excel equations & sheets updated successfully.")

    # 4. Generate High-DPI Report Images (ADL, ADTv, Combined, ACSO)
    print("\n[Step 4/5] Rendering Exact Report Images...")
    tl_images = generate_report_images(sections)
    acso_images = generate_acso_report_images(sections)
    all_images = tl_images + acso_images
    print(f"  [+] Generated {len(all_images)} report images:")
    for img in all_images:
        print(f"      - {img.name}")

    # 5. Flash to WhatsApp
    if send_whatsapp:
        print("\n[Step 5/5] Flashing report images to WhatsApp...")
        images_to_flash = [
            ADL_REPORT_IMAGE_PATH,
            ADTV_REPORT_IMAGE_PATH,
            ADL_ACSO_REPORT_IMAGE_PATH,
            ADTV_ACSO_REPORT_IMAGE_PATH,
        ]
        success = flash_report_image(images_to_flash, target_recipients=WHATSAPP_GROUPS)
        if success:
            print("  [+] Reports successfully flashed to WhatsApp!")
        else:
            print("  [!] WhatsApp flash notice: please review console logs.")
    else:
        print("\n[Step 5/5] WhatsApp sending skipped (--generate-only mode).")

    print("\n" + "=" * 60)
    print(f"[OK] CYCLE COMPLETED SUCCESSFULLY AT: {datetime.now().strftime('%I:%M:%S %p')}")
    print("=" * 60 + "\n")
    return True


def run_scheduler_loop(region_id: str = DEFAULT_REGION_ID):
    """Runs a 24/7 background scheduler monitoring 8:00 AM and 3:00 PM triggers."""
    print("=" * 60)
    print("[SERVICE] 24/7 BACKGROUND COMPLAINT AUTOMATION SERVICE RUNNING")
    print(f"  Scheduled Daily Run Times: {', '.join(SCHEDULE_TIMES)}")
    print(f"  Target WhatsApp Groups:    {', '.join(WHATSAPP_GROUPS)}")
    print("=" * 60)

    executed_slots = set()

    while True:
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        date_today_str = now.strftime("%Y-%m-%d")

        for sched_slot in SCHEDULE_TIMES:
            slot_id = f"{date_today_str}_{sched_slot}"
            if current_time_str == sched_slot and slot_id not in executed_slots:
                print(f"\n[Scheduler] Scheduled time reached: {sched_slot}! Initiating report cycle...")
                try:
                    execute_cycle(download_online=True, send_whatsapp=True, region_id=region_id)
                    executed_slots.add(slot_id)
                except Exception as e:
                    print(f"[Scheduler] Error executing cycle: {e}")

        time.sleep(25)


def main():
    parser = argparse.ArgumentParser(description="Daily Complaint Pending Report Automation Engine")
    parser.add_argument("--run-now", action="store_true", help="Execute complete cycle now with CRM download & WhatsApp flash")
    parser.add_argument("--test-local", action="store_true", help="Execute cycle now using existing local download files")
    parser.add_argument("--generate-only", action="store_true", help="Generate Excel and image without sending to WhatsApp")
    parser.add_argument("--schedule", action="store_true", help="Run 24/7 continuous scheduler (8:00 AM and 3:00 PM)")
    parser.add_argument("--region", default=DEFAULT_REGION_ID, help="Region ID/name to download, filter, and report")

    args = parser.parse_args()

    if args.schedule:
        run_scheduler_loop(args.region)
    elif args.test_local:
        execute_cycle(download_online=False, send_whatsapp=not args.generate_only, region_id=args.region)
    elif args.generate_only:
        execute_cycle(download_online=False, send_whatsapp=False, region_id=args.region)
    elif args.run_now:
        execute_cycle(download_online=True, send_whatsapp=True, region_id=args.region)
    else:
        print("\n=== Daily Complaint Pending Report Automation ===")
        print("1. Run Full Cycle Now (CRM Download + Filter + Excel + Image + WhatsApp)")
        print("2. Test Run with Local Files (Instant Filter + Excel + Image)")
        print("3. Start 24/7 Background Scheduler (8:00 AM & 3:00 PM)")
        print("4. Exit")
        choice = input("\nEnter choice [1-4]: ").strip()

        if choice == "1":
            execute_cycle(download_online=True, send_whatsapp=True)
        elif choice == "2":
            execute_cycle(download_online=False, send_whatsapp=False)
        elif choice == "3":
            run_scheduler_loop()
        else:
            print("Exiting.")


if __name__ == "__main__":
    main()
