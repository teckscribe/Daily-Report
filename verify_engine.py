"""
verify_engine.py
================
Proves that report_engine.py reproduces the golden workbook EXACTLY.

1. Reads the three input sheets ('ADL P', 'ADTv P', 'Prepaid') from the workbook.
2. Runs the Python engine.
3. Compares every numeric cell of 'Pending Days', 'Prepaid Pending' and
   'Post Paid & Prepaid' against the values Excel last calculated (cached values).
4. Also checks that every row label / lookup key in report_layout.py still matches the sheets.

The workbook is opened read-only (xlrd) and never modified.

Usage:  python verify_engine.py ["path\\to\\Daily Complint Tracker.xls"]
"""
import sys
from pathlib import Path

import xlrd

from config import TARGET_EXCEL_PATH
from report_engine import compute_report, load_inputs_from_workbook
from report_layout import ACSO_ROWS, TEAM_LEADER_ROWS

# (sheet name, result attr, {table: (gt column index, first bucket column index)})
# Column indexes are 0-based (A=0). Rows: TL = layout excel_row, ACSO = pd_row / final_row.
SHEETS = [
    ("Pending Days", "pending_days", {"adl": (2, 3), "adtv": (18, 19)}, False),
    ("Prepaid Pending", "prepaid_pending", {"adl": (3, 4), "adtv": (21, 22)}, False),
    ("Post Paid & Prepaid", "final", {"adl": (2, 3), "adtv": (18, 19)}, True),
]


def _num(v):
    return 0 if v in ("", None) else int(round(float(v)))


def verify(path: str) -> int:
    wb = xlrd.open_workbook(path)
    result = compute_report(*load_inputs_from_workbook(path))
    mismatches, checked = [], 0

    def cmp(sheet, ws, row1, col0, expected):
        nonlocal checked
        got = _num(ws.cell_value(row1 - 1, col0))
        checked += 1
        if got != expected:
            mismatches.append(f"{sheet}!{xlrd.formula.colname(col0)}{row1}: excel={got} engine={expected}")

    for sheet, attr, cols, is_final in SHEETS:
        ws = wb.sheet_by_name(sheet)
        tables = getattr(result, attr)
        for prod, (gt_c, b_c) in cols.items():
            # Team Leader rows
            for lay, row in zip(TEAM_LEADER_ROWS, tables[f"{prod}_team"].rows):
                cmp(sheet, ws, lay.excel_row, gt_c, row.grand_total)
                for i, v in enumerate(row.buckets):
                    cmp(sheet, ws, lay.excel_row, b_c + i, v)
            # ACSO rows + Grand Total row
            acso = tables[f"{prod}_acso"]
            for lay, row in zip(ACSO_ROWS, acso.rows):
                r = lay.final_row if is_final else lay.pd_row
                cmp(sheet, ws, r, gt_c, row.grand_total)
                for i, v in enumerate(row.buckets):
                    cmp(sheet, ws, r, b_c + i, v)
            tot_r = 46 if is_final else 45
            cmp(sheet, ws, tot_r, gt_c, acso.total.grand_total)
            for i, v in enumerate(acso.total.buckets):
                cmp(sheet, ws, tot_r, b_c + i, v)

    # --- layout keys still match the sheets? ---
    key_issues = []
    pdd, ppp, fin = (wb.sheet_by_name(s) for s in ("Pending Days", "Prepaid Pending", "Post Paid & Prepaid"))

    def key(ws, r, c, want, label):
        have = ws.cell_value(r - 1, c)
        if isinstance(have, float) and have.is_integer():
            have = int(have)
        if str(have) != str(want):
            key_issues.append(f"{label} {ws.name}!{xlrd.formula.colname(c)}{r}: sheet={have!r} layout={want!r}")

    for t in TEAM_LEADER_ROWS:
        r = t.excel_row
        key(pdd, r, 1, t.pd_adl_name_key, "TL"); key(pdd, r, 17, t.pd_adtv_name_key, "TL")
        key(ppp, r, 2, t.pp_adl_emp_code, "TL"); key(ppp, r, 20, t.pp_adtv_emp_code, "TL")
        key(fin, r, 0, t.adl_center, "TL"); key(fin, r, 1, t.adl_name, "TL")
        key(fin, r, 16, t.adtv_center, "TL"); key(fin, r, 17, t.adtv_name, "TL")
    for a in ACSO_ROWS:
        key(pdd, a.pd_row, 0, a.pd_adl_center_key, "ACSO"); key(pdd, a.pd_row, 16, a.pd_adtv_center_key, "ACSO")
        key(ppp, a.pd_row, 0, a.pp_adl_center_key, "ACSO"); key(ppp, a.pd_row, 18, a.pp_adtv_center_key, "ACSO")
        key(fin, a.final_row, 1, a.adl_acso, "ACSO"); key(fin, a.final_row, 17, a.adtv_acso, "ACSO")

    print(f"Workbook : {path}")
    print(f"Cells compared : {checked}")
    print(f"Value mismatches: {len(mismatches)}")
    for m in mismatches[:60]:
        print("   ", m)
    print(f"Layout key mismatches: {len(key_issues)}")
    for k in key_issues:
        print("   ", k)
    fin_adl, fin_tv = result.final["adl_acso"].total, result.final["adtv_acso"].total
    print(f"Final Grand Total  ADL={fin_adl.grand_total}  ADTv={fin_tv.grand_total}")
    ok = not mismatches and not key_issues
    print("RESULT:", "PASS - engine == Excel" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(verify(sys.argv[1] if len(sys.argv) > 1 else str(Path(TARGET_EXCEL_PATH))))
