"""
report_layout.py
================
Exact row layout of the `Daily Complint Tracker.xls` report, copied cell-for-cell from the
golden workbook. See docs/REPORT_GENERATION_REFERENCE.md for the full explanation.

IMPORTANT
---------
* The DISPLAY labels (what is printed on the report) come from sheet `Post Paid & Prepaid`.
* The LOOKUP keys (what COUNTIF/COUNTIFS actually match on) come from the intermediate
  sheets `Pending Days` and `Prepaid Pending`. They are NOT always the same as the display
  labels (e.g. row 6 shows "Remesh.R" but counts "Anil V.U" / Emp Code 656).
* Keys are kept byte-for-byte, including trailing spaces ("Jithin .P  ", "Muhammed Kabeer  "),
  because Excel's COUNTIF matches them exactly (case-insensitive, NOT trimmed).

If the Excel template is changed (new Team Leader, new Emp Code ...), update this file and
run `python verify_engine.py` to prove the engine still matches the workbook.
"""
from dataclasses import dataclass
from typing import Union

from config import DEFAULT_REGION_ID

# Pending-days buckets: (report column label, Excel COUNTIFS criterion)
BUCKETS = [
    ("< 1day", "<1"),
    ("1 day", "1"),
    ("2 day", "2"),
    ("3 day", "3"),
    ("4 day", "4"),
    ("5 day", "5"),
    ("6 day", "6"),
    ("7 day", "7"),
    ("8 day", "8"),
    ("9 day", "9"),
    ("10 day", "10"),
    ("> 10 day", ">10"),
]
BUCKET_LABELS = [b[0] for b in BUCKETS]
BUCKET_CRITERIA = [b[1] for b in BUCKETS]


@dataclass(frozen=True)
class TeamLeaderRow:
    """One Team Leader row (Excel rows 4-26 in all three report sheets)."""
    excel_row: int
    # --- display (sheet 'Post Paid & Prepaid') ---
    adl_center: str          # col A
    adl_name: str            # col B
    adtv_center: str         # col Q
    adtv_name: str           # col R
    # --- lookup keys ---
    pd_adl_name_key: str     # 'Pending Days'!B  -> matched against 'ADL P'!AU (TEAMLEADERNAME)
    pd_adtv_name_key: str    # 'Pending Days'!R  -> matched against 'ADTv P'!AC (TEAMLEADERNAME)
    pp_adl_emp_code: Union[int, str]   # 'Prepaid Pending'!C -> matched against Prepaid!T (Alloted To)
    pp_adtv_emp_code: Union[int, str]  # 'Prepaid Pending'!U -> matched against Prepaid!T (Alloted To)


@dataclass(frozen=True)
class AcsoRow:
    """One ACSO / Center row. Intermediate sheets rows 33-45 -> final sheet rows 34-46."""
    pd_row: int              # row in 'Pending Days' / 'Prepaid Pending'
    final_row: int           # row in 'Post Paid & Prepaid' (= pd_row + 1)
    # --- display (sheet 'Post Paid & Prepaid') ---
    adl_center: str          # col A
    adl_acso: str            # col B
    adtv_center: str         # col Q
    adtv_acso: str           # col R
    # --- lookup keys ---
    pd_adl_center_key: str   # 'Pending Days'!A    -> 'ADL P'!AE (AREA)
    pd_adtv_center_key: str  # 'Pending Days'!Q    -> 'ADTv P'!S (SERVICEAMO)
    pp_adl_center_key: str   # 'Prepaid Pending'!A -> Prepaid!Z (Area)
    pp_adtv_center_key: str  # 'Prepaid Pending'!S -> Prepaid!Z (Area)


# Source column headers (row 1 of each input sheet) and their Excel letters in the template.
ADL_COLS = {"team": "TEAMLEADERNAME", "center": "AREA", "days": "DAYSELAPSED"}            # AU, AE, AL
ADTV_COLS = {"team": "TEAMLEADERNAME", "center": "SERVICEAMO", "days": "DAYSELAPSED"}     # AC, S,  V
PREPAID_COLS = {"emp": "Alloted To", "issue": "Issue Service Type", "days": "TAT", "center": "Area"}  # T, I, P, Z
PREPAID_INTERNET = "Internet Issue"   # ADL prepaid  = Issue Service Type == "Internet Issue"
                                       # ADTv prepaid = Issue Service Type <> "Internet Issue"


def get_layout_for_region(region_id: str = DEFAULT_REGION_ID):
    """Loads the selected region's layout from SQLite without cross-region fallback."""
    try:
        from db_manager import get_team_leaders, get_acsos
        tls_db = get_team_leaders(region_id)
        acsos_db = get_acsos(region_id)
        if tls_db or acsos_db:
            tl_rows = [
                TeamLeaderRow(
                    excel_row=idx + 4,
                    adl_center=r["center_name"],
                    adl_name=r["name"],
                    adtv_center=r["adtv_center"],
                    adtv_name=r["adtv_name"],
                    pd_adl_name_key=r["pd_adl_name_key"],
                    pd_adtv_name_key=r["pd_adtv_name_key"],
                    pp_adl_emp_code=int(r["pp_adl_emp_code"]) if str(r["pp_adl_emp_code"]).isdigit() else r["pp_adl_emp_code"],
                    pp_adtv_emp_code=int(r["pp_adtv_emp_code"]) if str(r["pp_adtv_emp_code"]).isdigit() else r["pp_adtv_emp_code"],
                )
                for idx, r in enumerate(tls_db)
            ]
            acso_rows = [
                AcsoRow(
                    pd_row=32 + idx,
                    final_row=33 + idx,
                    adl_center=r["adl_center_display"],
                    adl_acso=r["acso_name"],
                    adtv_center=r["adtv_center_display"],
                    adtv_acso=r.get("adtv_acso_name") or r["acso_name"],
                    pd_adl_center_key=r["pd_adl_center_key"],
                    pd_adtv_center_key=r["pd_adtv_center_key"],
                    pp_adl_center_key=r["pp_adl_center_key"],
                    pp_adtv_center_key=r["pp_adtv_center_key"],
                )
                for idx, r in enumerate(acsos_db)
            ]
            return tl_rows, acso_rows
    except Exception:
        pass
    return [], []

