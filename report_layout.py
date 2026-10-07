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
from typing import List, Union

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


# fmt: off
TEAM_LEADER_ROWS: List[TeamLeaderRow] = [
    TeamLeaderRow(4,  "Chalakudy",      "SHYAMKUMAR",        "CHALAKKUDY",            "SHYAMKUMAR",        "SHYAMKUMAR",        "SHYAMKUMAR",        980,  980),
    TeamLeaderRow(5,  "Chalakudy",      "SIJU K.J",          "CHALAKKUDY",            "SIJU K.J",          "SIJU K.J",          "SIJU K.J",          2874, 2874),
    # NOTE: row 6 displays "Remesh.R" but the intermediate sheets still count "Anil V.U" / Emp 656.
    TeamLeaderRow(6,  "Guruvayoor",     "Remesh.R",          "GURUVAYUR (HE01)",      "Remesh.R",          "Anil V.U",          "Anil V.U",          656,  656),
    TeamLeaderRow(7,  "Irinjalakuda",   "Nithin Hari",       "IRINJALAKUDA",          "Nithin Hari",       "Nithin Hari",       "Nithin Hari",       882,  882),
    TeamLeaderRow(8,  "Irinjalakuda",   "SHIBIN K B",        "IRINJALAKUDA",          "SHIBIN K B",        "SHIBIN K B",        "SHIBIN K B",        1423, 1423),
    TeamLeaderRow(9,  "kodungalloor",   "LINU E A",          "KODUNGALLUR",           "LINU E A",          "LINU E A",          "LINU E A",          1462, 1462),
    TeamLeaderRow(10, "kodungalloor",   "SINJO JOSEPH",      "KODUNGALLUR",           "SINJO JOSEPH",      "SINJO JOSEPH",      "SINJO JOSEPH",      1680, 1680),
    TeamLeaderRow(11, "Kunnamkulam",    "RAJU K K",          "KUNNAMKULAM (HE02)",    "RAJU K K",          "RAJU K K",          "RAJU K K",          1800, 1800),
    TeamLeaderRow(12, "Kunnamkulam",    "RAKESH.V.R",        "KUNNAMKULAM (HE02)",    "RAKESH.V.R",        "RAKESH.V.R",        "RAKESH.V.R",        2614, 2614),
    TeamLeaderRow(13, "Manarkad",       "Santhosh E.B",      "MANARKAD",              "Santhosh E.B",      "Santhosh E.B",      "Santhosh E.B",      1780, 1780),
    TeamLeaderRow(14, "Olavakkod",      "Sreenath K.S",      "Olavakkod",             "Sreenath K.S",      "Sreenath K.S",      "Sreenath K.S",      2354, 2354),
    TeamLeaderRow(15, "Ottapalam",      "Muhammed Kabeer  ", "OTTAPALAM",             "Muhammed Kabeer  ", "Muhammed Kabeer  ", "Muhammed Kabeer  ", 2810, 2810),
    TeamLeaderRow(16, "Ottapalam",      "Shameer P.M",       "OTTAPALAM",             "Shameer P.M",       "Shameer P.M",       "Shameer P.M",       2130, 2130),
    TeamLeaderRow(17, "Palakkad",       "Praveen Kumar P",   "PALAKKAD 1 (JA01)",     "Praveen Kumar P",   "Praveen Kumar P",   "Praveen Kumar P",   1877, 1877),
    TeamLeaderRow(18, "Palakkad",       "Rajeev C",          "PALAKKAD 1 (JA01)",     "Rajeev C",          "Rajeev C",          "Rajeev C",          1428, 1428),
    TeamLeaderRow(19, "Pattambi",       "Prasanth P.V",      "PATTAMBI",              "Prasanth P.V",      "Prasanth P.V",      "Prasanth P.V",      2041, 2041),
    TeamLeaderRow(20, "Thathamangalam", "Pradeep U N",       "THATHAMANGALAM",        "Pradeep U N",       "Pradeep U N",       "Pradeep U N",       2049, 2049),
    TeamLeaderRow(21, "Trichur North",  "Jithin .P  ",       "THRISSUR NORTH (HA01)", "Jithin .P  ",       "Jithin .P  ",       "Jithin .P  ",       2699, 2699),
    TeamLeaderRow(22, "Trichur North",  "JUDITH JOSEPH",     "THRISSUR NORTH (HA01)", "JUDITH JOSEPH",     "JUDITH JOSEPH",     "JUDITH JOSEPH",     2728, 2728),
    TeamLeaderRow(23, "Trichur North",  "VISAL N.V",         "THRISSUR NORTH (HA01)", "VISAL N.V",         "VISAL N.V",         "VISAL N.V",         2577, 2577),
    TeamLeaderRow(24, "Trichur South",  "BINEESH BABU",      "THRISSUR SOUTH (HA02)", "BINEESH BABU",      "BINEESH BABU",      "BINEESH BABU",      2598, 2598),
    TeamLeaderRow(25, "Trichur South",  "Sony Joseph",       "THRISSUR SOUTH (HA02)", "Sony Joseph",       "Sony Joseph",       "Sony Joseph",       2215, 2215),
]

ACSO_ROWS: List[AcsoRow] = [
    #      pd  fin  ADL center        ADL ACSO                ADTv center              ADTv ACSO               PD ADL key        PD ADTv key              PP ADL key        PP ADTv key
    AcsoRow(32, 33, "Chalakudy",      "Arun .A.R",            "CHALAKKUDY",            "Arun .A.R",            "Chalakudy",      "CHALAKKUDY",            "Chalakudy",      "Chalakudy"),
    AcsoRow(33, 34, "Guruvayoor",     "Abhilash .P.Verghese", "GURUVAYUR (HE01)",      "Abhilash .P.Verghese", "Guruvayoor",     "GURUVAYUR (HE01)",      "Guruvayoor",     "Guruvayoor"),
    AcsoRow(34, 35, "Irinjalakuda",   "Midhun Mohan",         "IRINJALAKUDA",          "Midhun Mohan",         "Irinjalakuda",   "IRINJALAKUDA",          "Irinjalakuda",   "Irinjalakuda"),
    AcsoRow(35, 36, "kodungalloor",   "Sunilraj",             "KODUNGALLUR",           "Sunilraj",             "kodungalloor",   "KODUNGALLUR",           "kodungalloor",   "kodungalloor"),
    AcsoRow(36, 37, "Kunnamkulam",    "Remesh.R",             "KUNNAMKULAM (HE02)",    "Remesh.R",             "Kunnamkulam",    "KUNNAMKULAM (HE02)",    "Kunnamkulam",    "Kunnamkulam"),
    AcsoRow(37, 38, "Manarkad",       "Manikandan .M.P",      "MANARKAD",              "Manikandan .M.P",      "Manarkad",       "MANARKAD",              "Manarkad",       "Manarkad"),
    # NOTE rows 38-40: ADL and ADTv tables list centres in a different order, and the ADTv
    # prepaid keys (Prepaid Pending col S) differ from the ADTv postpaid keys (Pending Days col Q).
    AcsoRow(38, 39, "Olavakkod",      "Mohammed Navaf",       "OTTAPALAM",             "Binoy .B",             "Olavakkod",      "OTTAPALAM",             "Olavakkod",      "Ottapalam"),
    AcsoRow(39, 40, "Ottapalam",      "Binoy .B",             "PALAKKAD 1 (JA01)",     "Mohammed Navaf",       "Ottapalam",      "PALAKKAD 1 (JA01)",     "Ottapalam",      "Palakkad"),
    AcsoRow(40, 41, "Palakkad",       "Mohammed Navaf",       "PALAKKAD 2 (JA02)",     "Mohammed Navaf",       "Palakkad",       "PALAKKAD 2 (JA02)",     "Palakkad",       "Olavakkod"),
    AcsoRow(41, 42, "Pattambi",       "Haridasan .T.P",       "PATTAMBI",              "Haridasan .T.P",       "Pattambi",       "PATTAMBI",              "Pattambi",       "Pattambi"),
    AcsoRow(42, 43, "Thathamangalam", "Mohammed Navaf",       "THATHAMANGALAM",        "Mohammed Navaf",       "Thathamangalam", "THATHAMANGALAM",        "Thathamangalam", "Thathamangalam"),
    AcsoRow(43, 44, "Trichur North",  "Johnson K.C",          "THRISSUR NORTH (HA01)", "Johnson K.C",          "Trichur North",  "THRISSUR NORTH (HA01)", "Trichur North",  "Trichur North"),
    AcsoRow(44, 45, "Trichur South",  "Narayanan .P",         "THRISSUR SOUTH (HA02)", "Narayanan .P",         "Trichur South",  "THRISSUR SOUTH (HA02)", "Trichur South",  "Trichur South"),
]
# fmt: on

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

