import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")

# --- Directories ---
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
BACKUPS_DIR = BASE_DIR / "backups"
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", os.path.expanduser(r"~\Downloads")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# --- Excel Report Paths ---
TARGET_EXCEL_PATH = os.getenv(
    "TARGET_EXCEL_PATH",
    str(BASE_DIR / "Daily Complint Tracker.xls")
    if (BASE_DIR / "Daily Complint Tracker.xls").exists()
    else (
        r"C:\Users\Anoop P\Desktop\Daily Tracker\Daily Complint pending Report..xls"
        if sys.platform == "win32"
        else str(BASE_DIR / "output" / "Daily_Complaint_Pending_Report.xlsx")
    ),
)

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

def get_adl_export_query(region: str = "Thrissur") -> str:
    """Generates the Softcode CRMS SQL export query for ADL Broadband for a specific region."""
    clean_region = region.strip().replace("'", "''")
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

def get_adtv_export_query(region: str = "Thrissur") -> str:
    """Generates the Softcode CRMS SQL export query for ADTv Digital TV for a specific region."""
    clean_region = region.strip().replace("'", "''")
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

# Direct SQL query used by Softcode CRMS export (default to Thrissur baseline)
ADL_EXPORT_QUERY = get_adl_export_query("Thrissur")
ADTV_EXPORT_QUERY = get_adtv_export_query("Thrissur")

# --- Credentials (from .env, supporting both _PWD and _PASS variants) ---
SOFTCODE_USER = os.getenv("SOFTCODE_USER", "")
SOFTCODE_PWD = os.getenv("SOFTCODE_PWD") or os.getenv("SOFTCODE_PASS", "")

PREPAID_USER = os.getenv("PREPAID_USER", "")
PREPAID_PWD = os.getenv("PREPAID_PWD") or os.getenv("PREPAID_PASS", "")

# --- Filter Criteria ---
TARGET_REGION = "Thrissur"
ADL_COMPLAINT_TYPE = "Network"
ADL_PROBLEM_TYPES = ["network complaint", "onsite visit"]
ADTV_COMPLAINT_TYPE = "Network"
PREPAID_REGION = "Thrissur"
PREPAID_COMPLAINT_TYPE = "Network"

# --- WhatsApp Configuration ---
# Specify your WhatsApp group name(s) here or in .env (comma-separated)
# e.g. WHATSAPP_GROUPS="Network Team Thrissur,ACSO Management"
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
