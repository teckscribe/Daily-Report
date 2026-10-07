import json
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")


def _load_region_config() -> dict[str, str]:
    """Load the installation-specific region configuration from JSON."""
    configured_path = Path(os.getenv("REGION_CONFIG_PATH", BASE_DIR / "region.json"))
    if not configured_path.exists():
        return {}
    try:
        payload = json.loads(configured_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid region configuration at {configured_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid region configuration at {configured_path}: expected a JSON object")
    required = ("region_id", "region_name", "softcode_region", "prepaid_region")
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise RuntimeError(f"Invalid region configuration at {configured_path}: missing {', '.join(missing)}")
    region_id = str(payload["region_id"]).strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]+", region_id):
        raise RuntimeError("region_id must contain only lowercase letters, numbers, hyphens, or underscores")
    return {
        "region_id": region_id,
        "region_name": str(payload["region_name"]).strip(),
        "softcode_region": str(payload["softcode_region"]).strip(),
        "prepaid_region": str(payload["prepaid_region"]).strip(),
    }


REGION_CONFIG = _load_region_config()
REGION_CONFIG_PATH = Path(os.getenv("REGION_CONFIG_PATH", BASE_DIR / "region.json"))
DEFAULT_REGION_ID = REGION_CONFIG.get("region_id") or os.getenv("DEFAULT_REGION_ID", "").strip().lower()
if not DEFAULT_REGION_ID:
    raise RuntimeError("Configure region.json or DEFAULT_REGION_ID in .env before starting the application")
DEFAULT_REGION_NAME = REGION_CONFIG.get("region_name") or os.getenv("DEFAULT_REGION_NAME", DEFAULT_REGION_ID.replace("_", " ").title()).strip()
TARGET_REGION = REGION_CONFIG.get("softcode_region") or os.getenv("TARGET_REGION", DEFAULT_REGION_NAME).strip()
PREPAID_REGION = REGION_CONFIG.get("prepaid_region") or os.getenv("PREPAID_REGION", DEFAULT_REGION_NAME).strip()

# --- Directories ---
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
BACKUPS_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", os.path.expanduser(r"~\Downloads")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))
DATA_RETENTION_HOURS = int(os.getenv("DATA_RETENTION_HOURS", "24"))

# --- Excel Report Paths ---
def resolve_target_excel_path() -> str:
    """
    Robustly resolves a valid, existing Excel master workbook path.
    1. Checks TARGET_EXCEL_PATH in .env (if it exists on current filesystem).
    2. Checks the installation-local data folder for the uploaded master workbook.
    3. Checks output and fallback locations.
    Prevents [Errno 2] No such file or directory when running across Windows and Linux.
    """
    env_val = os.getenv("TARGET_EXCEL_PATH", "").strip()
    if env_val:
        # On Linux/macOS, ignore Windows paths (e.g. C:\...) configured from development .env
        if sys.platform != "win32" and ((":" in env_val and len(env_val) >= 2 and env_val[1] == ":") or "\\" in env_val):
            pass
        else:
            p = Path(env_val)
            if p.exists():
                return str(p.resolve())
            rel_p = (BASE_DIR / env_val).resolve()
            if rel_p.exists():
                return str(rel_p)

    candidates = [
        DATA_DIR / "Daily Complint Tracker.xls",
        OUTPUT_DIR / "Daily_Complaint_Pending_Report.xlsx",
        OUTPUT_DIR / "Daily_Complaint_Pending_Report.xls",
        BASE_DIR / "output" / "Daily_Complaint_Pending_Report.xlsx",
        # Compatibility only for existing installations. New uploads are stored in data/.
        BASE_DIR / "Daily Complint Tracker.xls",
        BASE_DIR / "Daily Complint pending Report.xls",
    ]
    if sys.platform == "win32":
        candidates.extend([
            Path(r"C:\Users\Anoop P\Desktop\Daily Tracker\Daily Complint pending Report.xls"),
            Path(r"C:\Users\Anoop P\Desktop\Daily Tracker\Daily Complint pending Report..xls"),
            Path.home() / "Desktop" / "Daily Tracker" / "Daily Complint pending Report.xls",
            Path.home() / "Desktop" / "Daily Tracker" / "Daily Complint pending Report..xls",
        ])

    for c in candidates:
        if c.exists():
            return str(c.resolve())

    return str((DATA_DIR / "Daily Complint Tracker.xls").resolve())

TARGET_EXCEL_PATH = resolve_target_excel_path()

# Output image paths
REPORT_IMAGE_PATH = OUTPUT_DIR / "Daily_Complaint_Report_latest.jpg"
ADL_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADL_Complaint_Pending.jpg"
ADTV_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADTv_Complaint_Pending.jpg"
ADL_ACSO_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADL_ACSO_Complaint_Pending.jpg"
ADTV_ACSO_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADTv_ACSO_Complaint_Pending.jpg"

# --- Portal URLs ---
SOFTCODE_PORTAL_URL = "https://portal.asianet.co.in/portal/"
CRMS_URL = "https://portal.asianet.co.in/crms/"
ADL_REPORT_URL = "https://portal.asianet.co.in/crms/serversideDatatable?RptCode=RFCRM014"
ADTV_REPORT_URL = "https://portal.asianet.co.in/crms/serversideDatatable?RptCode=RFCRM015"

PREPAID_PORTAL_URL = "https://sms.ali.asianetindia.com/login/"
PREPAID_REPORT_URL = "https://sms.ali.asianetindia.com/admin/reports/customised/pending-tickets"
PREPAID_EXPORT_URL = "https://sms.ali.asianetindia.com/api/reports/customised/pending-tickets/export?lco="

def get_adl_export_query(region: str | None = None) -> str:
    """Generates the Softcode CRMS SQL export query for ADL Broadband for a specific region."""
    clean_region = (region or TARGET_REGION).strip().replace("'", "''")
    return (
        " SELECT SubCode,NAME,'NA' AS Address, 'NA' AS MobileNo, TICKETNO, LOGINTIME,TicketStatus,subStatus, "
        "followUpDate,followUpRemarks,modifiedBy as FollowUpBy,ComplaintType, ProblemType,ProblemSubType, "
        "reason,ProblemDescription,problemRaisedBy,UserId,SourceOfComplaint, TicketType,OutageID,category,"
        "WhyPendingDescription,probResolution, DescriptionByWhom, ReopenedRemarks, reopenedByWhom,NoofCalls,"
        "FREQ_Complaints,FibreNode, Area,Center,Region, MAC,SecondMobileNo, PhoneNo, PackageName,DaysElapsed,"
        "HoursElapsed, CallBackStatus,ASSOCIATEID, NewTicketSubCode, ClassDesc ,OutageStatus, Dues,status,"
        "teamLeaderName, RegCode,ModemType,Technology_Type,allotEname,canvassedBy, Apprecom_Analysis, "
        "canvassedByName,activatedOn,GPONSINO,[CRMS].[dbo].[New_AON_ADL_Table].[Age] as AON "
        "FROM crms.dbo.Rpt_Pending_Tickets "
        "LEFT join [CRMS].[dbo].[New_AON_ADL_Table] on [CRMS].[dbo].[New_AON_ADL_Table].BP_Code=SubCode "
        f"where 1=1 and region in ( '{clean_region}' ) and complaintType in ( 'Network' ) and problemType in ( 'Network Complaints','Onsite Visit' ) "
        "ORDER BY LOGINTIME DESC"
    )

def get_adtv_export_query(region: str | None = None) -> str:
    """Generates the Softcode CRMS SQL export query for ADTv Digital TV for a specific region."""
    clean_region = (region or TARGET_REGION).strip().replace("'", "''")
    return (
        "  SELECT     Subcode,TICKETNO, CustomerNAME,'NA' as Address,SMSNo,TICKETNO,LOGINTIME,Ticketstatus,ComplaintType,  "
        "problemType,problemSubType,ProblemRemarks,ProblemRaisedBy,WhyPendingDescription,descriptionByWhom,   "
        "ReopenedRemarks,reopenedByWhom,FibreNode,ServiceAMO,Region,TicketType, DaysElapsed,HoursElapsed,NoOfCalls,   "
        "MAC,AMCDueDt, 'NA' as MobileNo,'NA' as PhoneNo, teamLeaderName,SchemeName,CustomerAMO, AMOCHANGENAME,     "
        "AMOCHANGEDATE,Dues, SubscriberStatus, FranchiseeCode,FranchiseeType,  CostDate as UpdatedDate,  "
        "IRResPersonName as UpdatedName,CostNo,allotEname,Technology,modemType,[CRMS].[dbo].[New_AON_ACS_Table].[Age] as AON   "
        "FROM  Rpt_DTV_Pending_Tickets  "
        "LEFT  join [CRMS].[dbo].[New_AON_ACS_Table] on [CRMS].[dbo].[New_AON_ACS_Table].BP_Code=SubCode  "
        f"where 1=1  and region = '{clean_region}' and complaintType in ( 'Network' ) "
        "ORDER BY LOGINTIME DESC"
    )

# Direct SQL query used by Softcode CRMS export for this installation's region.
ADL_EXPORT_QUERY = get_adl_export_query()
ADTV_EXPORT_QUERY = get_adtv_export_query()

# --- Credentials (from .env, supporting both _PWD and _PASS variants) ---
SOFTCODE_USER = os.getenv("SOFTCODE_USER", "")
SOFTCODE_PWD = os.getenv("SOFTCODE_PWD") or os.getenv("SOFTCODE_PASS", "")

PREPAID_USER = os.getenv("PREPAID_USER", "")
PREPAID_PWD = os.getenv("PREPAID_PWD") or os.getenv("PREPAID_PASS", "")
CRM_SSL_VERIFY = os.getenv("CRM_SSL_VERIFY", "true").lower() in ("true", "1", "yes")

# Web API protection. Production deployments must set this to a long random value.
# The API fails closed when it is missing rather than exposing the operations portal.
WEB_API_TOKEN = os.getenv("WEB_API_TOKEN", "").strip()

# --- Filter Criteria ---
ADL_COMPLAINT_TYPE = "Network"
ADL_PROBLEM_TYPES = ["network complaint", "onsite visit"]
ADTV_COMPLAINT_TYPE = "Network"
PREPAID_COMPLAINT_TYPE = "Network"

# --- WhatsApp Configuration ---
# Specify your WhatsApp group name(s) here or in .env (comma-separated)
# e.g. WHATSAPP_GROUPS="Network Team Kottayam,ACSO Management"
raw_groups = os.getenv("WHATSAPP_GROUPS", "NW Team TCR- REGION")
WHATSAPP_GROUPS = [g.strip() for g in raw_groups.split(",") if g.strip()]

# Chrome Profile for WhatsApp Web (Windows default)
CHROME_USER_DATA_DIR = os.getenv(
    "CHROME_USER_DATA_DIR",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data")
    if sys.platform == "win32"
    else "",
)
CHROME_PROFILE_NAME = os.getenv("CHROME_PROFILE_NAME", "Profile 13")

# WhatsApp Bot service URL (if using Docker container on Ubuntu)
WHATSAPP_BOT_URL = os.getenv("WHATSAPP_BOT_URL", "http://localhost:3000")
WHATSAPP_BOT_TOKEN = os.getenv("WHATSAPP_BOT_TOKEN", "asianet")

# --- Schedule Times (24-hour format HH:MM) ---
SCHEDULE_TIMES = ["08:00", "15:00"]

# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
raw_tg_users = os.getenv("TELEGRAM_ALLOWED_USERS", "").strip()
TELEGRAM_ALLOWED_USERS = [
    int(u.strip()) for u in raw_tg_users.split(",") if u.strip().isdigit()
]
TELEGRAM_DEFAULT_CHAT_ID = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "").strip()
TELEGRAM_TEST_PHONE = os.getenv("TELEGRAM_TEST_PHONE", "").strip()
TELEGRAM_WEB_URL = os.getenv("TELEGRAM_WEB_URL", "http://127.0.0.1:8201").strip()

# --- Service Request (SR) Configuration ---
SR_RAW_EXCEL_PATH = BASE_DIR / "Service Request - Raw Data.xls"
SR_EXCEL_REPORT_PATH = OUTPUT_DIR / "Daily_Service_Request_Pending_Report.xlsx"
ADL_SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADL_SR_Pending.jpg"
ADTV_SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "ADTv_SR_Pending.jpg"
SR_REPORT_IMAGE_PATH = OUTPUT_DIR / "Daily_SR_Report_latest.jpg"

