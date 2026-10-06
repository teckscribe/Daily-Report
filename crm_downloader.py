import os
import sys
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import requests
import urllib3
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    SOFTCODE_PORTAL_URL,
    CRMS_URL,
    ADL_REPORT_URL,
    ADTV_REPORT_URL,
    ADL_EXPORT_QUERY,
    ADTV_EXPORT_QUERY,
    get_adl_export_query,
    get_adtv_export_query,
    PREPAID_PORTAL_URL,
    PREPAID_REPORT_URL,
    PREPAID_EXPORT_URL,
    SOFTCODE_USER,
    SOFTCODE_PWD,
    PREPAID_USER,
    PREPAID_PWD,
    CRM_SSL_VERIFY,
    DOWNLOADS_DIR,
    DATA_DIR,
    DATA_RETENTION_HOURS,
)


def cleanup_old_download_files(hours: int = DATA_RETENTION_HOURS) -> int:
    """
    Cleans up raw downloaded Excel / CSV files older than `hours` (default 24h).
    Scans both DATA_DIR and DOWNLOADS_DIR. Never touches critical directory configurations.
    Preserves at least the single latest file of each type as a fallback.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(hours=hours)
    patterns = [
        "Pending Tickets - *.xlsx",
        "Pending Tickets DTv - *.xlsx",
        "Pending_tickets_Report - *.csv",
        "Pending_tickets_Report - *.xlsx",
        "Pending_SR_*.xlsx",
        "Daily_Service_Request_*.xlsx",
    ]
    deleted_count = 0
    for search_dir in [DATA_DIR, DOWNLOADS_DIR]:
        if not search_dir or not search_dir.exists():
            continue
        for pat in patterns:
            matching = sorted(search_dir.glob(pat), key=lambda f: f.stat().st_mtime)
            if len(matching) <= 1:
                # Always keep at least the latest file as a local fallback
                continue
            for f in matching[:-1]:
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink(missing_ok=True)
                        deleted_count += 1
                except Exception:
                    pass

    if deleted_count > 0:
        print(f"[Data Retention] Automatically purged {deleted_count} CRM export file(s) older than {hours} hours.")
    return deleted_count


def find_latest_file(directory: Path, pattern: str) -> Optional[Path]:
    """Finds the most recently modified file matching pattern in directory."""
    files = list(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)


def get_latest_local_downloads() -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """Checks data and downloads directories for existing latest pending complaint files."""
    for search_dir in [DATA_DIR, DOWNLOADS_DIR]:
        adl_file = find_latest_file(search_dir, "Pending Tickets - *.xlsx") or find_latest_file(search_dir, "Pending Tickets.xlsx")
        adtv_file = find_latest_file(search_dir, "Pending Tickets DTv - *.xlsx") or find_latest_file(search_dir, "Pending Tickets DTv.xlsx")
        prep_file = find_latest_file(search_dir, "Pending_tickets_Report - *.csv") or find_latest_file(search_dir, "Pending_tickets_Report*.xlsx") or find_latest_file(search_dir, "Pending_tickets_Report.csv")

        if adl_file and adtv_file and prep_file:
            print(f"[CRM Downloader] Discovered existing files in {search_dir}:")
            print(f"  ADL:     {adl_file.name}")
            print(f"  ADTv:    {adtv_file.name}")
            print(f"  Prepaid: {prep_file.name}")
            return adl_file, adtv_file, prep_file

    return None, None, None


last_crm_error: Optional[str] = None


def download_via_http_session(region: str = "Thrissur") -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Direct, ultra-fast headless HTTP session downloader for Softcode and Prepaid portals.
    Executes in 2-3 seconds without browser overhead or profile lock issues.
    """
    global last_crm_error
    last_crm_error = None
    print(f"[CRM Downloader] Trying direct HTTP Session download for region: '{region}'...")
    adl_path = None
    adtv_path = None
    prep_path = None
    ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")

    # 1. Softcode / CRMS Download
    if SOFTCODE_USER and SOFTCODE_PWD:
        try:
            print("[CRM Downloader] Connecting to Softcode Portal (portal.asianet.co.in)...")
            s = requests.Session()
            s.verify = CRM_SSL_VERIFY
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            })

            # Fetch portal login page to get initial session cookie
            s.get(SOFTCODE_PORTAL_URL, timeout=15)

            # Authenticate via loginAuth
            login_url = "https://portal.asianet.co.in/portal/loginAuth"
            login_payload = {
                "DUser": SOFTCODE_USER,
                "Pwd": SOFTCODE_PWD,
                "DefCompanyCode": "",
            }
            login_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": SOFTCODE_PORTAL_URL,
            }
            res_login = s.post(login_url, data=login_payload, headers=login_headers, timeout=15)
            login_resp_text = res_login.text.strip()

            if "Invalid Credientials" in login_resp_text:
                last_crm_error = f"Softcode authentication failed: Invalid Credentials for '{SOFTCODE_USER}'."
                print(f"[CRM Downloader] Softcode authentication failed: Invalid Credentials for user '{SOFTCODE_USER}'.")
            else:
                print("[CRM Downloader] Softcode authenticated successfully! Entering CRMS module...")
                # Redirect into CRMS module (establishes CRMS session token)
                redirect_url = "https://portal.asianet.co.in/portal/redirect?module=CRMS"
                res_redir = s.get(redirect_url, timeout=20, allow_redirects=True)
                print(f"[CRM Downloader] CRMS module reached: {res_redir.url[:60]}...")

                # Fetch ADL Broadband report
                print(f"[CRM Downloader] Downloading ADL Broadband Pending Tickets (RFCRM014) for region '{region}'...")
                adl_url = "https://portal.asianet.co.in/crms/getReportData"
                params_adl = {
                    "RptCode": "RFCRM014",
                    "dataSql": get_adl_export_query(region),
                }
                res_adl = s.get(adl_url, params=params_adl, timeout=60)
                if res_adl.status_code == 200 and len(res_adl.content) > 1000:
                    adl_path = DATA_DIR / f"Pending Tickets - {ts}.xlsx"
                    adl_path.write_bytes(res_adl.content)
                    print(f"  [+] Saved ADL to: {adl_path.name} ({len(res_adl.content):,} bytes)")
                else:
                    last_crm_error = f"ADL download failed: HTTP {res_adl.status_code} ({len(res_adl.content)} bytes)"
                    print(f"  [!] ADL download received HTTP {res_adl.status_code}, size: {len(res_adl.content)} bytes")

                # Fetch ADTv Digital TV report
                print(f"[CRM Downloader] Downloading ADTv Digital TV Pending Tickets (RFCRM015) for region '{region}'...")
                params_adtv = {
                    "RptCode": "RFCRM015",
                    "dataSql": get_adtv_export_query(region),
                }
                res_adtv = s.get(adl_url, params=params_adtv, timeout=60)
                if res_adtv.status_code == 200 and len(res_adtv.content) > 1000:
                    adtv_path = DATA_DIR / f"Pending Tickets DTv - {ts}.xlsx"
                    adtv_path.write_bytes(res_adtv.content)
                    print(f"  [+] Saved ADTv to: {adtv_path.name} ({len(res_adtv.content):,} bytes)")
                else:
                    last_crm_error = f"ADTv download failed: HTTP {res_adtv.status_code} ({len(res_adtv.content)} bytes)"
                    print(f"  [!] ADTv download received HTTP {res_adtv.status_code}, size: {len(res_adtv.content)} bytes")

        except Exception as e_softcode:
            last_crm_error = f"Softcode CRM Portal error: {e_softcode}"
            print(f"[CRM Downloader] Softcode HTTP session notice: {e_softcode}")
    else:
        print("[CRM Downloader] Softcode credentials not fully set in .env (SOFTCODE_USER / SOFTCODE_PWD).")

    # 2. Prepaid SMS Portal Download
    if PREPAID_USER and PREPAID_PWD:
        try:
            print("[CRM Downloader] Connecting to Prepaid SMS Portal (sms.ali.asianetindia.com)...")
            s_prep = requests.Session()
            s_prep.verify = CRM_SSL_VERIFY
            s_prep.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            })

            # Fetch login page to extract CSRF token
            res_login_page = s_prep.get(PREPAID_PORTAL_URL, timeout=15)
            csrf_token = ""
            m = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', res_login_page.text)
            if not m:
                m = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']csrfmiddlewaretoken["\']', res_login_page.text)
            if m:
                csrf_token = m.group(1)

            # Perform login
            payload = {
                "csrfmiddlewaretoken": csrf_token,
                "username": PREPAID_USER,
                "password": PREPAID_PWD,
                "next_url": "/",
            }
            headers_post = {
                "Referer": PREPAID_PORTAL_URL,
            }
            res_auth = s_prep.post(PREPAID_PORTAL_URL, data=payload, headers=headers_post, timeout=15)
            if "invalid" in res_auth.text.lower() or "incorrect" in res_auth.text.lower():
                last_crm_error = f"Prepaid portal authentication failed: Invalid Credentials for '{PREPAID_USER}'."
                print(f"[CRM Downloader] Prepaid portal authentication failed: Invalid Credentials for user '{PREPAID_USER}'.")
            else:
                print("[CRM Downloader] Prepaid portal authenticated successfully! Downloading pending tickets...")
                res_export = s_prep.get(PREPAID_EXPORT_URL, timeout=60)
                if res_export.status_code == 200 and len(res_export.content) > 100:
                    prep_path = DATA_DIR / f"Pending_tickets_Report - {ts}.csv"
                    prep_path.write_bytes(res_export.content)
                    print(f"  [+] Saved Prepaid to: {prep_path.name} ({len(res_export.content):,} bytes)")
                else:
                    last_crm_error = f"Prepaid export failed: HTTP {res_export.status_code} ({len(res_export.content)} bytes)"
                    print(f"  [!] Prepaid export received HTTP {res_export.status_code}, size: {len(res_export.content)} bytes")

        except Exception as e_prep:
            last_crm_error = f"Prepaid SMS Portal error: {e_prep}"
            print(f"[CRM Downloader] Prepaid HTTP session notice: {e_prep}")
    else:
        print("[CRM Downloader] Prepaid credentials not fully set in .env (PREPAID_USER / PREPAID_PWD).")

    return adl_path, adtv_path, prep_path


def download_via_playwright(headless: bool = False, region: str = "Thrissur") -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Playwright browser automation fallback.
    Launches browser, fills login fields, clicks elements, and captures file chooser downloads.
    """
    print(f"[CRM Downloader] Initiating Playwright browser automation fallback for region: '{region}'...")
    adl_path = None
    adtv_path = None
    prep_path = None
    ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")

    try:
        with sync_playwright() as p:
            user_data_dir = DATA_DIR / "browser_session"
            user_data_dir.mkdir(parents=True, exist_ok=True)

            launch_kwargs = {
                "headless": headless,
                "user_data_dir": str(user_data_dir),
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if sys.platform == "win32":
                launch_kwargs["channel"] = "chrome"

            try:
                context = p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e_launch:
                if "channel" in launch_kwargs:
                    print(f"[CRM Downloader] Chrome launch notice ({e_launch}). Falling back to bundled Chromium...")
                    launch_kwargs.pop("channel", None)
                    context = p.chromium.launch_persistent_context(**launch_kwargs)
                else:
                    raise e_launch

            page = context.new_page()

            # 1. Softcode Portal
            if SOFTCODE_USER and SOFTCODE_PWD:
                print(f"[CRM Downloader] Navigating to Softcode: {SOFTCODE_PORTAL_URL}")
                page.goto(SOFTCODE_PORTAL_URL, timeout=60000)

                if page.locator("input[name='DUser'], #DUser").count() > 0:
                    print(f"[CRM Downloader] Logging into Softcode as {SOFTCODE_USER}...")
                    page.fill("input[name='DUser'], #DUser", SOFTCODE_USER)
                    page.fill("input[name='Pwd'], #Pwd", SOFTCODE_PWD)
                    # Click #login anchor button
                    if page.locator("#login, a#login").count() > 0:
                        page.click("#login, a#login")
                    else:
                        page.press("input[name='Pwd'], #Pwd", "Enter")
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)

                # Enter CRMS module
                print("[CRM Downloader] Navigating to CRMS module redirect...")
                page.goto("https://portal.asianet.co.in/portal/redirect?module=CRMS", timeout=60000)
                page.wait_for_load_state("networkidle")
                time.sleep(2)

                # Download ADL
                try:
                    print(f"[CRM Downloader] Fetching ADL report via datatable for '{region}'...")
                    sql_adl = get_adl_export_query(region)
                    encoded_sql_adl = urllib.parse.quote(sql_adl)
                    direct_adl_url = f"https://portal.asianet.co.in/crms/getReportData?RptCode=RFCRM014&dataSql={encoded_sql_adl}"
                    with page.expect_download(timeout=45000) as download_info:
                        page.goto(direct_adl_url)
                    download = download_info.value
                    adl_path = DATA_DIR / f"Pending Tickets - {ts}.xlsx"
                    download.save_as(str(adl_path))
                    print(f"  [+] Saved ADL to: {adl_path.name}")
                except Exception as e:
                    print(f"  [!] ADL download error: {e}")

                # Download ADTv
                try:
                    print(f"[CRM Downloader] Fetching ADTv report via datatable for '{region}'...")
                    sql_adtv = get_adtv_export_query(region)
                    encoded_sql_adtv = urllib.parse.quote(sql_adtv)
                    direct_adtv_url = f"https://portal.asianet.co.in/crms/getReportData?RptCode=RFCRM015&dataSql={encoded_sql_adtv}"
                    with page.expect_download(timeout=45000) as download_info:
                        page.goto(direct_adtv_url)
                    download = download_info.value
                    adtv_path = DATA_DIR / f"Pending Tickets DTv - {ts}.xlsx"
                    download.save_as(str(adtv_path))
                    print(f"  [+] Saved ADTv to: {adtv_path.name}")
                except Exception as e:
                    print(f"  [!] ADTv download error: {e}")

            # 2. Prepaid Portal
            if PREPAID_USER and PREPAID_PWD:
                print(f"[CRM Downloader] Navigating to Prepaid: {PREPAID_PORTAL_URL}")
                page.goto(PREPAID_PORTAL_URL, timeout=60000)

                if page.locator("input[name='username']").count() > 0:
                    print(f"[CRM Downloader] Logging into Prepaid as {PREPAID_USER}...")
                    page.fill("input[name='username']", PREPAID_USER)
                    page.fill("input[name='password']", PREPAID_PWD)
                    page.click("button[type='submit'], input[type='submit']")
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)

                try:
                    print("[CRM Downloader] Fetching Prepaid export...")
                    with page.expect_download(timeout=45000) as download_info:
                        page.goto(PREPAID_EXPORT_URL)
                    download = download_info.value
                    prep_path = DATA_DIR / f"Pending_tickets_Report - {ts}.csv"
                    download.save_as(str(prep_path))
                    print(f"  [+] Saved Prepaid to: {prep_path.name}")
                except Exception as e:
                    print(f"  [!] Prepaid download error: {e}")

            context.close()

    except Exception as e_playwright:
        last_crm_error = f"Playwright browser automation error: {e_playwright}"
        print(f"[CRM Downloader] Playwright automation error: {e_playwright}")

    return adl_path, adtv_path, prep_path


def download_from_crm(
    headless: bool = True,
    region: str = "Thrissur",
    allow_stale: bool = True,
) -> Tuple[Path, Path, Path]:
    """
    Unified entrypoint:
    1. Attempts direct ultra-fast HTTP Session download.
    2. If missing files, falls back to Playwright browser automation.
    3. If still missing files, falls back to latest local downloads from Downloads/ or data/ (if allow_stale=True).
    """
    global last_crm_error
    print("=" * 60)
    print(f"[CRM Downloader] Starting Automated Portal Download Pipeline for Region: {region}")
    print("=" * 60)

    adl_path = None
    adtv_path = None
    prep_path = None

    # Step 1: Fast HTTP session
    credentials_configured = bool((SOFTCODE_USER and SOFTCODE_PWD) or (PREPAID_USER and PREPAID_PWD))
    if credentials_configured:
        adl_path, adtv_path, prep_path = download_via_http_session(region=region)

    # Step 2: Browser automation fallback if any file missing
    if not (adl_path and adtv_path and prep_path):
        if credentials_configured:
            print("\n[CRM Downloader] Some files not retrieved via HTTP. Attempting Playwright browser fallback...")
            b_adl, b_adtv, b_prep = download_via_playwright(headless=headless, region=region)
            adl_path = adl_path or b_adl
            adtv_path = adtv_path or b_adtv
            prep_path = prep_path or b_prep

    # If credentials were configured and online download failed, enforce allow_stale policy
    if credentials_configured and not (adl_path and adtv_path and prep_path) and not allow_stale:
        raise RuntimeError(
            f"Asianet CRM Portal is down or unreachable: {last_crm_error or 'Failed to download fresh tickets'}. "
            f"Automated run aborted to prevent stale dispatch. Please retry once CRM portal is restored."
        )

    # Step 3: Local downloads fallback
    if not (adl_path and adtv_path and prep_path):
        print("\n[CRM Downloader] Online download incomplete or credentials missing. Checking local downloads directory...")
        local_adl, local_adtv, local_prep = get_latest_local_downloads()
        adl_path = adl_path or local_adl
        adtv_path = adtv_path or local_adtv
        prep_path = prep_path or local_prep

    if not (adl_path and adtv_path and prep_path):
        raise FileNotFoundError(
            "Could not obtain all 3 complaint files (ADL, ADTv, Prepaid). "
            "Please configure portal credentials in .env or ensure latest files are in Downloads."
        )

    print("\n[CRM Downloader] All 3 complaint data sources acquired successfully:")
    print(f"  [+] ADL:     {adl_path}")
    print(f"  [+] ADTv:    {adtv_path}")
    print(f"  [+] Prepaid: {prep_path}")
    print("=" * 60)

    try:
        cleanup_old_download_files()
    except Exception:
        pass

    return adl_path, adtv_path, prep_path


if __name__ == "__main__":
    download_from_crm(headless=False)
