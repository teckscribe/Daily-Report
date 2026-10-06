"""
report_engine.py
================
Pure-Python replica of the formulas in `Daily Complint Tracker.xls`.

    Input sheets  : 'ADL P', 'ADTv P', 'Prepaid'          (raw CRM downloads, no formulas)
    Engine sheets : 'Pending Days'    (postpaid)  = COUNTIF/COUNTIFS on ADL P / ADTv P
                    'Prepaid Pending' (prepaid)   = COUNTIFS on Prepaid
    Final sheet   : 'Post Paid & Prepaid' = 'Pending Days' + 'Prepaid Pending' (cell by cell)

Every function below mirrors one Excel formula family. See docs/REPORT_GENERATION_REFERENCE.md.
The Excel workbook itself is NEVER written by this module.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from report_layout import (
    ACSO_ROWS,
    ADL_COLS,
    ADTV_COLS,
    BUCKET_CRITERIA,
    BUCKET_LABELS,
    PREPAID_COLS,
    PREPAID_INTERNET,
    TEAM_LEADER_ROWS,
    get_layout_for_region,
)

# ---------------------------------------------------------------------------
# 1. Excel COUNTIF criterion semantics
# ---------------------------------------------------------------------------
_OP_RE = re.compile(r"^(<=|>=|<>|<|>|=)?(.*)$", re.S)


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v == "")


def _to_number(v: Any) -> Optional[float]:
    """Numeric value of a cell, or None. Text that looks like a number counts (as COUNTIF does)."""
    if _is_blank(v) or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _wildcard_regex(text: str) -> re.Pattern:
    """Excel wildcards: * any run, ? one char, ~ escapes. Case-insensitive, whole-cell match."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "~" and i + 1 < len(text):
            out.append(re.escape(text[i + 1])); i += 2; continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.I | re.S)


def make_matcher(criterion: Any):
    """Return f(cell)->bool that behaves like one COUNTIFS criterion."""
    # Numeric criterion (e.g. Emp Code 980): equals numeric cell or numeric-looking text.
    if isinstance(criterion, (int, float)) and not isinstance(criterion, bool):
        target = float(criterion)
        return lambda v: _to_number(v) == target

    op, rhs = _OP_RE.match(str(criterion)).groups()
    op = op or "="
    rhs_num = _to_number(rhs) if rhs != "" else None

    if op in ("<", ">", "<=", ">="):
        if rhs_num is None:  # text comparison is never used by this workbook
            raise ValueError(f"Unsupported criterion {criterion!r}")
        cmp = {"<": float.__lt__, ">": float.__gt__, "<=": float.__le__, ">=": float.__ge__}[op]

        def num_cmp(v):
            # Only REAL numbers are compared; blanks and text are ignored (Excel behaviour).
            if _is_blank(v) or isinstance(v, (str, bool)):
                return False
            return cmp(float(v), rhs_num)
        return num_cmp

    if rhs_num is not None:  # "=1" / "1"  -> numeric equality (text "1" also matches)
        eq = lambda v: _to_number(v) == rhs_num
    elif rhs == "":
        eq = _is_blank
    else:  # text equality, case-insensitive, NOT trimmed, wildcards honoured
        rx = _wildcard_regex(rhs)
        eq = lambda v: (not _is_blank(v)) and bool(rx.match(str(v)))
    return eq if op == "=" else (lambda v: not eq(v))   # "<>" also counts blanks, like Excel


def countifs(*pairs) -> int:
    """countifs(col1, crit1, col2, crit2, ...) over equal-length python lists."""
    cols = pairs[0::2]
    matchers = [make_matcher(c) for c in pairs[1::2]]
    n = len(cols[0])
    return sum(1 for i in range(n) if all(m(col[i]) for col, m in zip(cols, matchers)))


# ---------------------------------------------------------------------------
# 2. Result containers
# ---------------------------------------------------------------------------
@dataclass
class ReportRow:
    center: str
    name: str
    grand_total: int
    buckets: List[int]  # 12 values aligned with BUCKET_LABELS

    def as_dict(self) -> Dict[str, Any]:
        d = {"CENTER": self.center, "Name": self.name, "Grand Total": self.grand_total}
        d.update(dict(zip(BUCKET_LABELS, self.buckets)))
        return d


@dataclass
class Table:
    title: str
    rows: List[ReportRow]
    total: Optional[ReportRow] = None  # Grand Total row (ACSO tables only)

    def to_frame(self) -> pd.DataFrame:
        rows = self.rows + ([self.total] if self.total else [])
        return pd.DataFrame([r.as_dict() for r in rows])


@dataclass
class ReportResult:
    pending_days: Dict[str, Table] = field(default_factory=dict)     # postpaid engine
    prepaid_pending: Dict[str, Table] = field(default_factory=dict)  # prepaid engine
    final: Dict[str, Table] = field(default_factory=dict)            # 'Post Paid & Prepaid'


# ---------------------------------------------------------------------------
# 3. Input helpers
# ---------------------------------------------------------------------------
def _column(df: pd.DataFrame, header: str) -> List[Any]:
    """Get a column by its row-1 header (case/space-insensitive header lookup)."""
    if df is None or df.empty:
        return []
    want = header.strip().casefold()
    for c in df.columns:
        if str(c).strip().casefold() == want:
            return df[c].tolist()
    raise KeyError(f"Column '{header}' not found. Available: {list(df.columns)}")


def _sum_rows(rows: List[ReportRow], center="Grand Total", name="") -> ReportRow:
    return ReportRow(
        center, name,
        sum(r.grand_total for r in rows),
        [sum(r.buckets[i] for r in rows) for i in range(len(BUCKET_LABELS))],
    )


def _add(a: ReportRow, b: ReportRow, center: str, name: str) -> ReportRow:
    return ReportRow(center, name, a.grand_total + b.grand_total,
                     [x + y for x, y in zip(a.buckets, b.buckets)])


# ---------------------------------------------------------------------------
# 4. Sheet 'Pending Days'  (postpaid)
# ---------------------------------------------------------------------------
def _postpaid_row(key_col, days_col, key, center, name) -> ReportRow:
    # Grand Total : =COUNTIF(<key col>, key)               (NO days condition)
    # Buckets     : =COUNTIFS(<key col>, key, <days col>, "<1" | "1" ... "10" | ">10")
    gt = countifs(key_col, key)
    buckets = [countifs(key_col, key, days_col, crit) for crit in BUCKET_CRITERIA]
    return ReportRow(center, name, gt, buckets)


def compute_pending_days(
    df_adl: pd.DataFrame,
    df_adtv: pd.DataFrame,
    team_leader_rows: Optional[List[TeamLeaderRow]] = None,
    acso_rows: Optional[List[AcsoRow]] = None,
    region_id: str = "thrissur",
) -> Dict[str, Table]:
    if team_leader_rows is None or acso_rows is None:
        tl_db, acso_db = get_layout_for_region(region_id)
        team_leader_rows = team_leader_rows or tl_db
        acso_rows = acso_rows or acso_db

    adl_team, adl_area, adl_days = (_column(df_adl, ADL_COLS[k]) for k in ("team", "center", "days"))
    tv_team, tv_amo, tv_days = (_column(df_adtv, ADTV_COLS[k]) for k in ("team", "center", "days"))

    adl_tl = [_postpaid_row(adl_team, adl_days, r.pd_adl_name_key, r.adl_center, r.adl_name)
              for r in team_leader_rows]
    adtv_tl = [_postpaid_row(tv_team, tv_days, r.pd_adtv_name_key, r.adtv_center, r.adtv_name)
               for r in team_leader_rows]
    adl_acso = [_postpaid_row(adl_area, adl_days, r.pd_adl_center_key, r.pd_adl_center_key, r.adl_acso)
                for r in acso_rows]
    adtv_acso = [_postpaid_row(tv_amo, tv_days, r.pd_adtv_center_key, r.pd_adtv_center_key, r.adtv_acso)
                 for r in acso_rows]
    return {
        "adl_team": Table("ADL Pending", adl_tl),
        "adtv_team": Table("ADTv Pending", adtv_tl),
        "adl_acso": Table("ADL Pending (ACSO)", adl_acso, _sum_rows(adl_acso)),
        "adtv_acso": Table("ADTv Pending (ACSO)", adtv_acso, _sum_rows(adtv_acso)),
    }


# ---------------------------------------------------------------------------
# 5. Sheet 'Prepaid Pending'  (prepaid)
# ---------------------------------------------------------------------------
def _prepaid_row(key_col, issue_col, days_col, key, issue_crit, center, name) -> ReportRow:
    # Total   : =COUNTIFS(Prepaid!T or Z, key, Prepaid!I, "Internet Issue" | "<>Internet Issue")
    # Buckets : same + Prepaid!P (TAT), "<1" | "1" ... ">10"
    gt = countifs(key_col, key, issue_col, issue_crit)
    buckets = [countifs(key_col, key, issue_col, issue_crit, days_col, crit) for crit in BUCKET_CRITERIA]
    return ReportRow(center, name, gt, buckets)


def compute_prepaid_pending(
    df_prepaid: pd.DataFrame,
    team_leader_rows: Optional[List[TeamLeaderRow]] = None,
    acso_rows: Optional[List[AcsoRow]] = None,
    region_id: str = "thrissur",
) -> Dict[str, Table]:
    if team_leader_rows is None or acso_rows is None:
        tl_db, acso_db = get_layout_for_region(region_id)
        team_leader_rows = team_leader_rows or tl_db
        acso_rows = acso_rows or acso_db

    emp, issue, tat, area = (_column(df_prepaid, PREPAID_COLS[k]) for k in ("emp", "issue", "days", "center"))
    adl_c, tv_c = PREPAID_INTERNET, "<>" + PREPAID_INTERNET

    adl_tl = [_prepaid_row(emp, issue, tat, r.pp_adl_emp_code, adl_c, r.adl_center, r.adl_name)
              for r in team_leader_rows]
    adtv_tl = [_prepaid_row(emp, issue, tat, r.pp_adtv_emp_code, tv_c, r.adtv_center, r.adtv_name)
               for r in team_leader_rows]
    adl_acso = [_prepaid_row(area, issue, tat, r.pp_adl_center_key, adl_c, r.pp_adl_center_key, r.adl_acso)
                for r in acso_rows]
    adtv_acso = [_prepaid_row(area, issue, tat, r.pp_adtv_center_key, tv_c, r.pp_adtv_center_key, r.adtv_acso)
                 for r in acso_rows]
    return {
        "adl_team": Table("ADL Prepaid Complaint", adl_tl),
        "adtv_team": Table("ADTv Prepaid Complaint", adtv_tl),
        "adl_acso": Table("ADL Prepaid Complaint (ACSO)", adl_acso, _sum_rows(adl_acso)),
        "adtv_acso": Table("ADTv Prepaid Complaint (ACSO)", adtv_acso, _sum_rows(adtv_acso)),
    }


# ---------------------------------------------------------------------------
# 6. Sheet 'Post Paid & Prepaid'  (final) = Pending Days + Prepaid Pending
# ---------------------------------------------------------------------------
def compute_report(
    df_adl: pd.DataFrame,
    df_adtv: pd.DataFrame,
    df_prepaid: pd.DataFrame,
    region_id: str = "thrissur",
    team_leader_rows: Optional[List[TeamLeaderRow]] = None,
    acso_rows: Optional[List[AcsoRow]] = None,
) -> ReportResult:
    if team_leader_rows is None or acso_rows is None:
        tl_db, acso_db = get_layout_for_region(region_id)
        team_leader_rows = team_leader_rows or tl_db
        acso_rows = acso_rows or acso_db

    pd_ = compute_pending_days(df_adl, df_adtv, team_leader_rows=team_leader_rows, acso_rows=acso_rows, region_id=region_id)
    pp = compute_prepaid_pending(df_prepaid, team_leader_rows=team_leader_rows, acso_rows=acso_rows, region_id=region_id)
    final: Dict[str, Table] = {}

    for key, title in (("adl_team", "ADL Complaint Pending"), ("adtv_team", "ADTv Complaint Pending")):
        is_tv = key.startswith("adtv")
        rows = []
        for lay, a, b in zip(team_leader_rows, pd_[key].rows, pp[key].rows):
            center = lay.adtv_center if is_tv else lay.adl_center
            name = lay.adtv_name if is_tv else lay.adl_name
            rows.append(_add(a, b, center, name))
        final[key] = Table(title, rows)

    for key, title in (("adl_acso", "ADL Pending (ACSO)"), ("adtv_acso", "ADTv Pending (ACSO)")):
        is_tv = key.startswith("adtv")
        rows = []
        for lay, a, b in zip(acso_rows, pd_[key].rows, pp[key].rows):
            center = lay.adtv_center if is_tv else lay.adl_center
            name = lay.adtv_acso if is_tv else lay.adl_acso
            rows.append(_add(a, b, center, name))
        total = _add(pd_[key].total, pp[key].total, "Grand Total", "")
        final[key] = Table(title, rows, total)

    return ReportResult(pending_days=pd_, prepaid_pending=pp, final=final)


# ---------------------------------------------------------------------------
# 7. Load the three input sheets from a workbook (read-only)
# ---------------------------------------------------------------------------
def load_inputs_from_workbook(path: str | Path):
    """Read 'ADL P', 'ADTv P', 'Prepaid' exactly as stored (no stripping, no type coercion)."""
    p = Path(path)
    if not p.exists():
        from config import resolve_target_excel_path
        resolved_str = resolve_target_excel_path()
        resolved_p = Path(resolved_str)
        if resolved_p.exists():
            p = resolved_p
    path = str(p)
    kw = dict(dtype=object, keep_default_na=False, na_values=[])
    df_adl = pd.read_excel(path, sheet_name="ADL P", **kw)
    df_adtv = pd.read_excel(path, sheet_name="ADTv P", **kw)
    df_prepaid = pd.read_excel(path, sheet_name="Prepaid", **kw)
    return df_adl, df_adtv, df_prepaid


# ---------------------------------------------------------------------------
# 8. Input integrity check (catches data pasted under the wrong headers)
# ---------------------------------------------------------------------------
def _share(values, pred) -> float:
    vals = [v for v in values if not _is_blank(v)]
    return (sum(1 for v in vals if pred(v)) / len(vals)) if vals else 1.0


def validate_inputs(df_adl, df_adtv, df_prepaid, region_id: str = "thrissur", min_share: float = 0.5) -> List[str]:
    """Return human-readable warnings. Empty list = inputs look correctly aligned."""
    warnings: List[str] = []
    try:
        tl_db, _ = get_layout_for_region(region_id)
        tl_source = tl_db if tl_db else TEAM_LEADER_ROWS
    except Exception:
        tl_source = TEAM_LEADER_ROWS

    tl_keys = {str(r.pd_adl_name_key).strip().casefold() for r in tl_source} | \
              {str(r.pd_adtv_name_key).strip().casefold() for r in tl_source}
    is_tl = lambda v: str(v).strip().casefold() in tl_keys
    is_num = lambda v: _to_number(v) is not None

    checks = [
        ("ADL P", df_adl, ADL_COLS["team"], is_tl, "Team Leader names"),
        ("ADL P", df_adl, ADL_COLS["days"], is_num, "numeric days"),
        ("ADTv P", df_adtv, ADTV_COLS["team"], is_tl, "Team Leader names"),
        ("ADTv P", df_adtv, ADTV_COLS["days"], is_num, "numeric days"),
        ("ADTv P", df_adtv, ADTV_COLS["center"], lambda v: str(v).strip().casefold() != region_id.strip().casefold(), "AMO centre names (not the region)"),
        ("Prepaid", df_prepaid, PREPAID_COLS["days"], is_num, "numeric TAT"),
        ("Prepaid", df_prepaid, PREPAID_COLS["issue"], lambda v: "issue" in str(v).casefold() or "both" in str(v).casefold(), "Issue Service Type values"),
    ]
    for sheet, df, header, pred, what in checks:
        try:
            col = _column(df, header)
        except KeyError as e:
            warnings.append(f"[{sheet}] {e}")
            continue
        share = _share(col, pred)
        if share < min_share:
            sample = [v for v in col if not _is_blank(v)][:3]
            warnings.append(
                f"[{sheet}] column '{header}' should contain {what}, but only {share:.0%} do "
                f"(sample: {sample}). Data is probably shifted / pasted under the wrong header."
            )
    return warnings
