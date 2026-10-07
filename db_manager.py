"""
db_manager.py
=============
SQLite database manager for Kerala Multi-Region Network Complaint Tracker.
Stores and manages Centers, Team Leaders, ACSO Officers, and Employee Codes region-by-region.
"""
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from config import DATA_DIR, DEFAULT_REGION_ID, DEFAULT_REGION_NAME, PREPAID_REGION, TARGET_REGION

DB_PATH = DATA_DIR / "region_config.db"

DEFAULT_REGIONS = [
    (DEFAULT_REGION_ID, DEFAULT_REGION_NAME, TARGET_REGION, PREPAID_REGION),
]
KERALA_DISTRICTS = DEFAULT_REGIONS


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH.resolve()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initializes schema and ensures the configured default region exists."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS regions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        softcode_region TEXT NOT NULL,
        prepaid_region TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS centers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        center_name TEXT NOT NULL,
        adl_area_key TEXT NOT NULL,
        adtv_amo_key TEXT NOT NULL,
        prepaid_area_key TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS acsos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        center_name TEXT NOT NULL,
        acso_name TEXT NOT NULL,
        adtv_acso_name TEXT,
        adl_center_display TEXT NOT NULL,
        adtv_center_display TEXT NOT NULL,
        pd_adl_center_key TEXT NOT NULL,
        pd_adtv_center_key TEXT NOT NULL,
        pp_adl_center_key TEXT NOT NULL,
        pp_adtv_center_key TEXT NOT NULL,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        crm_name TEXT DEFAULT '',
        emp_code TEXT DEFAULT '',
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS team_leaders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        center_name TEXT NOT NULL,
        name TEXT NOT NULL,
        adtv_center TEXT NOT NULL,
        adtv_name TEXT NOT NULL,
        pd_adl_name_key TEXT NOT NULL,
        pd_adtv_name_key TEXT NOT NULL,
        pp_adl_emp_code TEXT NOT NULL,
        pp_adtv_emp_code TEXT NOT NULL,
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        emp_code TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        center_name TEXT,
        phone TEXT,
        email TEXT,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    conn.commit()

    c.execute("""
    CREATE TABLE IF NOT EXISTS dispatch_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        rule_name TEXT NOT NULL,
        report_type TEXT NOT NULL,
        target_recipients TEXT NOT NULL,
        description TEXT,
        is_enabled INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    # Dynamic migrations for existing databases
    c.execute("PRAGMA table_info(team_leaders)")
    tl_cols = [r[1] for r in c.fetchall()]
    if "phone" not in tl_cols:
        c.execute("ALTER TABLE team_leaders ADD COLUMN phone TEXT DEFAULT ''")
    if "email" not in tl_cols:
        c.execute("ALTER TABLE team_leaders ADD COLUMN email TEXT DEFAULT ''")

    c.execute("PRAGMA table_info(acsos)")
    acso_cols = [r[1] for r in c.fetchall()]
    if "adtv_acso_name" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN adtv_acso_name TEXT")
        c.execute("UPDATE acsos SET adtv_acso_name = acso_name WHERE adtv_acso_name IS NULL")
    if "phone" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN phone TEXT DEFAULT ''")
    if "email" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN email TEXT DEFAULT ''")
    if "crm_name" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN crm_name TEXT DEFAULT ''")
        c.execute("UPDATE acsos SET crm_name = acso_name WHERE crm_name IS NULL OR crm_name = ''")
    if "emp_code" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN emp_code TEXT DEFAULT ''")

    c.execute("PRAGMA table_info(employees)")
    emp_cols = [r[1] for r in c.fetchall()]
    if "email" not in emp_cols:
        c.execute("ALTER TABLE employees ADD COLUMN email TEXT DEFAULT ''")

    c.execute("PRAGMA table_info(dispatch_rules)")
    rule_cols = [r[1] for r in c.fetchall()]
    if "description" not in rule_cols:
        c.execute("ALTER TABLE dispatch_rules ADD COLUMN description TEXT")
        conn.commit()


    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region_id TEXT NOT NULL,
        run_time TEXT NOT NULL,
        label TEXT,
        is_enabled INTEGER DEFAULT 1,
        last_run TEXT,
        report_type TEXT DEFAULT 'complaint',
        created_at TEXT,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    c.execute("PRAGMA table_info(schedule_times)")
    sched_cols = [r[1] for r in c.fetchall()]
    if "report_type" not in sched_cols:
        c.execute("ALTER TABLE schedule_times ADD COLUMN report_type TEXT DEFAULT 'complaint'")
        conn.commit()

    c.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()

    # Only the configured default is mandatory; deleted optional regions stay deleted.
    now_str = datetime.now().isoformat()
    for r_id, r_name, sc_reg, pp_reg in DEFAULT_REGIONS:
        c.execute("""
        INSERT INTO regions (id, name, softcode_region, prepaid_region, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            softcode_region = excluded.softcode_region,
            prepaid_region = excluded.prepaid_region,
            updated_at = excluded.updated_at
        """, (r_id, r_name, sc_reg, pp_reg, now_str, now_str))

    # Keep the configured installation region; remove any other empty placeholder.
    c.execute("""
    DELETE FROM regions 
    WHERE id != ?
      AND (SELECT COUNT(*) FROM team_leaders WHERE region_id = regions.id) = 0
      AND (SELECT COUNT(*) FROM acsos WHERE region_id = regions.id) = 0
      AND (SELECT COUNT(*) FROM centers WHERE region_id = regions.id) = 0
      AND (SELECT COUNT(*) FROM employees WHERE region_id = regions.id) = 0
      AND (SELECT COUNT(*) FROM schedule_times WHERE region_id = regions.id) = 0
      AND (SELECT COUNT(*) FROM dispatch_rules WHERE region_id = regions.id) = 0
    """, (DEFAULT_REGION_ID,))
    conn.commit()
    # Seed Default Master Setting if empty
    c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('scheduler_enabled', '1')")
    conn.commit()

    conn.close()


# --- Database Operations ---

def ensure_region_exists(region_id: str, name: Optional[str] = None) -> bool:
    """Ensures a region exists in the database, automatically creating it if necessary."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM regions WHERE id = ?", (region_id.lower().strip(),))
    row = c.fetchone()
    if not row:
        now_str = datetime.now().isoformat()
        r_name = name or region_id.capitalize()
        c.execute("""
        INSERT INTO regions (id, name, softcode_region, prepaid_region, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (region_id.lower().strip(), r_name, r_name, r_name, now_str, now_str))
        conn.commit()
    conn.close()
    return True


def get_all_regions() -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT r.*,
           (SELECT COUNT(*) FROM centers WHERE region_id = r.id) as center_count,
           (SELECT COUNT(*) FROM team_leaders WHERE region_id = r.id) as tl_count,
           (SELECT COUNT(*) FROM acsos WHERE region_id = r.id) as acso_count,
           (SELECT COUNT(*) FROM employees WHERE region_id = r.id) as emp_count,
           (SELECT COUNT(*) FROM schedule_times WHERE region_id = r.id) as schedule_count,
           (SELECT COUNT(*) FROM dispatch_rules WHERE region_id = r.id) as dispatch_rule_count
    FROM regions r
    ORDER BY r.name ASC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_region_by_id(region_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM regions WHERE id = ?", (region_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def add_region(region_id: str, name: str, softcode_region: str, prepaid_region: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    try:
        c.execute("""
        INSERT INTO regions (id, name, softcode_region, prepaid_region, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (region_id.lower().strip(), name.strip(), softcode_region.strip(), prepaid_region.strip(), now_str, now_str))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def delete_region(region_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM regions WHERE id = ?", (region_id,))
    conn.commit()
    conn.close()
    return True


# --- Team Leaders ---

def get_team_leaders(region_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM team_leaders WHERE region_id = ? ORDER BY sort_order ASC, id ASC", (region_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_team_leader(region_id: str, data: Dict[str, Any]) -> int:
    ensure_region_exists(region_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO team_leaders 
    (region_id, center_name, name, adtv_center, adtv_name, pd_adl_name_key, pd_adtv_name_key, pp_adl_emp_code, pp_adtv_emp_code, phone, email, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        region_id,
        data.get("center_name", "").strip(),
        data.get("name", "").strip(),
        data.get("adtv_center", data.get("center_name", "")).strip(),
        data.get("adtv_name", data.get("name", "")).strip(),
        data.get("pd_adl_name_key", data.get("name", "")),
        data.get("pd_adtv_name_key", data.get("adtv_name", data.get("name", ""))),
        str(data.get("pp_adl_emp_code", "")).strip(),
        str(data.get("pp_adtv_emp_code", data.get("pp_adl_emp_code", ""))).strip(),
        str(data.get("phone", "")).strip(),
        str(data.get("email", data.get("gmail", ""))).strip(),
        int(data.get("sort_order", 0))
    ))
    tl_id = c.lastrowid
    conn.commit()
    conn.close()
    return tl_id


def update_team_leader(tl_id: int, data: Dict[str, Any], region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE team_leaders SET
        center_name = ?,
        name = ?,
        adtv_center = ?,
        adtv_name = ?,
        pd_adl_name_key = ?,
        pd_adtv_name_key = ?,
        pp_adl_emp_code = ?,
        pp_adtv_emp_code = ?,
        phone = ?,
        email = ?,
        sort_order = ?
    WHERE id = ?
    """ + (" AND region_id = ?" if region_id else "") + """
    """, (
        data.get("center_name", "").strip(),
        data.get("name", ""),
        data.get("adtv_center", "").strip(),
        data.get("adtv_name", ""),
        data.get("pd_adl_name_key", ""),
        data.get("pd_adtv_name_key", ""),
        str(data.get("pp_adl_emp_code", "")).strip(),
        str(data.get("pp_adtv_emp_code", "")).strip(),
        str(data.get("phone", "")).strip(),
        str(data.get("email", data.get("gmail", ""))).strip(),
        int(data.get("sort_order", 0)),
        tl_id,
        *((region_id,) if region_id else ()),
    ))
    conn.commit()
    conn.close()
    return True


def delete_team_leader(tl_id: int, region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    if region_id:
        c.execute("DELETE FROM team_leaders WHERE id = ? AND region_id = ?", (tl_id, region_id))
    else:
        c.execute("DELETE FROM team_leaders WHERE id = ?", (tl_id,))
    conn.commit()
    conn.close()
    return True


# --- ACSOs ---

def get_acsos(region_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM acsos WHERE region_id = ? ORDER BY sort_order ASC, id ASC", (region_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_acso(region_id: str, data: Dict[str, Any]) -> int:
    ensure_region_exists(region_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO acsos 
    (region_id, center_name, acso_name, adtv_acso_name, adl_center_display, adtv_center_display, pd_adl_center_key, pd_adtv_center_key, pp_adl_center_key, pp_adtv_center_key, phone, email, sort_order, crm_name, emp_code)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        region_id,
        data.get("center_name", "").strip(),
        data.get("acso_name", "").strip(),
        data.get("adtv_acso_name", data.get("acso_name", "")).strip(),
        data.get("adl_center_display", data.get("center_name", "")).strip(),
        data.get("adtv_center_display", data.get("center_name", "")).strip(),
        data.get("pd_adl_center_key", data.get("center_name", "")).strip(),
        data.get("pd_adtv_center_key", data.get("adtv_center_display", data.get("center_name", ""))).strip(),
        data.get("pp_adl_center_key", data.get("center_name", "")).strip(),
        data.get("pp_adtv_center_key", data.get("center_name", "")).strip(),
        str(data.get("phone", "")).strip(),
        str(data.get("email", data.get("gmail", ""))).strip(),
        int(data.get("sort_order", 0)),
        str(data.get("crm_name", data.get("acso_name", ""))).strip(),
        str(data.get("emp_code", "")).strip()
    ))
    acso_id = c.lastrowid
    conn.commit()
    conn.close()
    return acso_id


def update_acso(acso_id: int, data: Dict[str, Any], region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE acsos SET
        center_name = ?,
        acso_name = ?,
        adtv_acso_name = ?,
        adl_center_display = ?,
        adtv_center_display = ?,
        pd_adl_center_key = ?,
        pd_adtv_center_key = ?,
        pp_adl_center_key = ?,
        pp_adtv_center_key = ?,
        phone = ?,
        email = ?,
        sort_order = ?,
        crm_name = ?,
        emp_code = ?
    WHERE id = ?
    """ + (" AND region_id = ?" if region_id else "") + """
    """, (
        data.get("center_name", "").strip(),
        data.get("acso_name", "").strip(),
        data.get("adtv_acso_name", data.get("acso_name", "")).strip(),
        data.get("adl_center_display", "").strip(),
        data.get("adtv_center_display", "").strip(),
        data.get("pd_adl_center_key", "").strip(),
        data.get("pd_adtv_center_key", "").strip(),
        data.get("pp_adl_center_key", "").strip(),
        data.get("pp_adtv_center_key", "").strip(),
        str(data.get("phone", "")).strip(),
        str(data.get("email", data.get("gmail", ""))).strip(),
        int(data.get("sort_order", 0)),
        str(data.get("crm_name", data.get("acso_name", ""))).strip(),
        str(data.get("emp_code", "")).strip(),
        acso_id,
        *((region_id,) if region_id else ()),
    ))
    conn.commit()
    conn.close()
    return True


def delete_acso(acso_id: int, region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    if region_id:
        c.execute("DELETE FROM acsos WHERE id = ? AND region_id = ?", (acso_id, region_id))
    else:
        c.execute("DELETE FROM acsos WHERE id = ?", (acso_id,))
    conn.commit()
    conn.close()
    return True


# --- Centers ---

def get_centers(region_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM centers WHERE region_id = ? ORDER BY sort_order ASC, id ASC", (region_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_center(region_id: str, data: Dict[str, Any]) -> int:
    ensure_region_exists(region_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO centers (region_id, center_name, adl_area_key, adtv_amo_key, prepaid_area_key, sort_order)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        region_id,
        data.get("center_name", "").strip(),
        data.get("adl_area_key", data.get("center_name", "")).strip(),
        data.get("adtv_amo_key", data.get("center_name", "")).strip(),
        data.get("prepaid_area_key", data.get("center_name", "")).strip(),
        int(data.get("sort_order", 0))
    ))
    cid = c.lastrowid
    conn.commit()
    conn.close()
    return cid


def update_center(center_id: int, data: Dict[str, Any]) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE centers SET
        center_name = ?,
        adl_area_key = ?,
        adtv_amo_key = ?,
        prepaid_area_key = ?,
        sort_order = ?
    WHERE id = ?
    """, (
        data.get("center_name", "").strip(),
        data.get("adl_area_key", "").strip(),
        data.get("adtv_amo_key", "").strip(),
        data.get("prepaid_area_key", "").strip(),
        int(data.get("sort_order", 0)),
        center_id
    ))
    conn.commit()
    conn.close()
    return True


def delete_center(center_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM centers WHERE id = ?", (center_id,))
    conn.commit()
    conn.close()
    return True


# --- Employees ---

def get_employees(region_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM employees WHERE region_id = ? ORDER BY emp_code ASC", (region_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def validate_region_report_directory(region_id: str) -> List[str]:
    """Return actionable layout issues before a region report is generated.

    The Employee Directory is the source of truth only for the identifiers
    used by each report.  A TL's Postpaid CRM name is a separate lookup field
    and may differ from their customised display name; its Prepaid employee
    code must exist in the Employee Directory.  Center-wise complaints and
    Service Requests use the center name.
    """
    def text(value: Any) -> str:
        return str(value or "").strip().casefold()

    def code(value: Any) -> str:
        value = str(value or "").strip()
        return value[:-2] if value.endswith(".0") and value[:-2].isdigit() else value

    issues: List[str] = []
    centers = get_centers(region_id)
    team_leaders = get_team_leaders(region_id)
    acsos = get_acsos(region_id)
    employees = get_employees(region_id)
    center_names = {text(row.get("center_name")) for row in centers if text(row.get("center_name"))}

    if not centers:
        return [f"[{region_id}] No centers are configured in the Employee Directory."]
    if team_leaders and not employees:
        return [f"[{region_id}] Employee Directory is empty. Import the regional directory before generating reports."]

    team_leader_codes = {
        code(row.get("emp_code"))
        for row in employees
        if "team" in text(row.get("role")) and code(row.get("emp_code"))
    }

    for row in team_leaders:
        name = row.get("name")
        label = f"Team Leader {name!r}"

        # Postpaid sources identify the TL by the dedicated CRM-name field.
        # It intentionally is not compared with Employee Display Name, which
        # users may customise.  Prepaid identifies the TL by employee code.
        postpaid_name_fields = ("pd_adl_name_key", "pd_adtv_name_key")
        prepaid_code_fields = ("pp_adl_emp_code", "pp_adtv_emp_code")
        for field in postpaid_name_fields:
            value = row.get(field)
            if not str(value or "").strip():
                issues.append(f"{label} is missing required postpaid TL-name key {field}.")
        for field in prepaid_code_fields:
            value = row.get(field)
            if not str(value or "").strip():
                issues.append(f"{label} is missing required prepaid employee-code key {field}.")
            elif code(value) not in team_leader_codes:
                issues.append(f"{label} prepaid employee-code key {field}={value!r} is not in the Employee Directory.")

    for row in acsos:
        center = row.get("center_name")
        label = f"Center {center!r}"
        if text(center) not in center_names:
            issues.append(f"{label} references a center missing from the Center Directory.")
        for field in ("pd_adl_center_key", "pd_adtv_center_key", "pp_adl_center_key", "pp_adtv_center_key"):
            if not str(row.get(field) or "").strip():
                issues.append(f"{label} is missing required center lookup key {field}.")

    return issues


def add_employee(region_id: str, data: Dict[str, Any]) -> int:
    ensure_region_exists(region_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO employees (region_id, emp_code, name, role, center_name, phone, email)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        region_id,
        str(data.get("emp_code", "")).strip(),
        data.get("name", "").strip(),
        data.get("role", "Technician").strip(),
        data.get("center_name", "").strip(),
        data.get("phone", "").strip(),
        str(data.get("email", data.get("gmail", ""))).strip()
    ))
    eid = c.lastrowid
    conn.commit()
    conn.close()
    return eid


def update_employee(emp_id: int, data: Dict[str, Any], region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE employees SET
        emp_code = ?,
        name = ?,
        role = ?,
        center_name = ?,
        phone = ?,
        email = ?
    WHERE id = ?
    """ + (" AND region_id = ?" if region_id else "") + """
    """, (
        str(data.get("emp_code", "")).strip(),
        data.get("name", "").strip(),
        data.get("role", "").strip(),
        data.get("center_name", "").strip(),
        data.get("phone", "").strip(),
        str(data.get("email", data.get("gmail", ""))).strip(),
        emp_id,
        *((region_id,) if region_id else ()),
    ))
    conn.commit()
    conn.close()
    return True


def delete_employee(emp_id: int, region_id: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    if region_id:
        c.execute("DELETE FROM employees WHERE id = ? AND region_id = ?", (emp_id, region_id))
    else:
        c.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()
    return True


# --- Dispatch Rules ---

def get_dispatch_rules(region_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    if region_id:
        c.execute("SELECT * FROM dispatch_rules WHERE region_id = ? ORDER BY id ASC", (region_id,))
    else:
        c.execute("SELECT * FROM dispatch_rules ORDER BY region_id ASC, id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_dispatch_rule(data: Dict[str, Any]) -> int:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    c.execute("""
    INSERT INTO dispatch_rules (region_id, rule_name, report_type, target_recipients, description, is_enabled, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("region_id", DEFAULT_REGION_ID).strip(),
        data.get("rule_name", "").strip(),
        data.get("report_type", "all").strip(),
        data.get("target_recipients", "").strip(),
        data.get("description", "").strip(),
        1 if data.get("is_enabled", 1) else 0,
        now_str,
        now_str
    ))
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_dispatch_rule(rule_id: int, data: Dict[str, Any]) -> bool:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    c.execute("""
    UPDATE dispatch_rules SET
        rule_name = ?,
        report_type = ?,
        target_recipients = ?,
        description = ?,
        is_enabled = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        data.get("rule_name", "").strip(),
        data.get("report_type", "all").strip(),
        data.get("target_recipients", "").strip(),
        data.get("description", "").strip(),
        1 if data.get("is_enabled", 1) else 0,
        now_str,
        rule_id
    ))
    conn.commit()
    conn.close()
    return True


def delete_dispatch_rule(rule_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM dispatch_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True


def toggle_dispatch_rule(rule_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE dispatch_rules SET is_enabled = CASE WHEN is_enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True


# --- Schedule Times ---

def get_schedule_times(region_id: Optional[str] = None, report_type: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT * FROM schedule_times WHERE 1=1"
    params = []
    if region_id:
        query += " AND region_id = ?"
        params.append(region_id)
    if report_type:
        if report_type == "complaint":
            query += " AND (report_type = 'complaint' OR report_type IS NULL OR report_type = '')"
        else:
            query += " AND report_type = ?"
            params.append(report_type)
    query += " ORDER BY run_time ASC"
    c.execute(query, tuple(params))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_schedule_time(region_id: str, run_time: str, label: str = "", report_type: str = "complaint") -> int:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    c.execute("""
    INSERT INTO schedule_times (region_id, run_time, label, is_enabled, report_type, created_at)
    VALUES (?, ?, ?, 1, ?, ?)
    """, (region_id.strip(), run_time.strip(), label.strip(), report_type.strip(), now_str))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def update_schedule_time(time_id: int, run_time: str, label: str = "", is_enabled: int = 1, report_type: Optional[str] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    if report_type is not None:
        c.execute("""
        UPDATE schedule_times SET
            run_time = ?,
            label = ?,
            is_enabled = ?,
            report_type = ?
        WHERE id = ?
        """, (run_time.strip(), label.strip(), 1 if is_enabled else 0, report_type.strip(), time_id))
    else:
        c.execute("""
        UPDATE schedule_times SET
            run_time = ?,
            label = ?,
            is_enabled = ?
        WHERE id = ?
        """, (run_time.strip(), label.strip(), 1 if is_enabled else 0, time_id))
    conn.commit()
    conn.close()
    return True


def delete_schedule_time(time_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM schedule_times WHERE id = ?", (time_id,))
    conn.commit()
    conn.close()
    return True


def toggle_schedule_time(time_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE schedule_times SET is_enabled = CASE WHEN is_enabled = 1 THEN 0 ELSE 1 END WHERE id = ?", (time_id,))
    conn.commit()
    conn.close()
    return True


def update_last_run(time_id: int, timestamp: str = "") -> bool:
    conn = get_connection()
    c = conn.cursor()
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE schedule_times SET last_run = ? WHERE id = ?", (ts, time_id))
    conn.commit()
    conn.close()
    return True


# --- System Settings ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return str(row[0]) if row else default


def set_setting(key: str, value: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
    return True


def get_telegram_alert_recipients() -> List[str]:
    """Returns all configured or recorded Telegram chat IDs for alert broadcasts."""
    recipients = set()
    try:
        from config import TELEGRAM_ALLOWED_USERS, TELEGRAM_DEFAULT_CHAT_ID
        if TELEGRAM_DEFAULT_CHAT_ID:
            recipients.add(str(TELEGRAM_DEFAULT_CHAT_ID).strip())
        for uid in TELEGRAM_ALLOWED_USERS:
            recipients.add(str(uid).strip())
    except Exception:
        pass

    raw_stored = get_setting("telegram_alert_chat_ids", "")
    if raw_stored:
        for cid in raw_stored.split(","):
            if cid.strip():
                recipients.add(cid.strip())
    return sorted(list(recipients))


def register_telegram_alert_recipient(chat_id: Any) -> bool:
    """Registers a chat ID as an authorized alert recipient."""
    cid_str = str(chat_id).strip()
    if not cid_str:
        return False
    current = set(get_setting("telegram_alert_chat_ids", "").split(","))
    current.discard("")
    if cid_str not in current:
        current.add(cid_str)
        set_setting("telegram_alert_chat_ids", ",".join(sorted(current)))
    return True


# Auto-initialize on first import
init_db()


# --- Configuration Backup & Restore Operations ---

def export_backup(region_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Exports full database or specific region configuration to a serializable dictionary.
    Includes Centers, TLs, ACSOs, Employees, Schedule Times, Dispatch Rules, and Settings.
    """
    conn = get_connection()
    c = conn.cursor()
    tables = [
        "regions",
        "centers",
        "acsos",
        "team_leaders",
        "employees",
        "schedule_times",
        "dispatch_rules",
        "system_settings"
    ]
    backup = {
        "_meta": {
            "description": f"Configuration backup for {region_id or 'all regions'}",
            "exported_at": datetime.now().isoformat(),
            "version": "2.0",
            "region_id": region_id or "all"
        },
        "tables": {}
    }
    for t in tables:
        if region_id and t not in ("regions", "system_settings"):
            c.execute(f'SELECT * FROM "{t}" WHERE region_id = ?', (region_id,))
        else:
            c.execute(f'SELECT * FROM "{t}"')
        rows = c.fetchall()
        c.execute(f'PRAGMA table_info("{t}")')
        cols = [col[1] for col in c.fetchall()]
        backup["tables"][t] = [dict(zip(cols, r)) for r in rows]
    conn.close()
    return backup


def restore_backup(data: Dict[str, Any], target_region: Optional[str] = None, clear_existing: bool = True) -> Dict[str, int]:
    """
    Restores database tables from a backup dictionary.
    Safe and idempotent with column validation.
    """
    if target_region:
        ensure_region_exists(target_region)
    conn = get_connection()
    c = conn.cursor()
    counts = {}
    tables = data.get("tables", {})

    # 1. System Settings
    if "system_settings" in tables:
        for r in tables["system_settings"]:
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (r["key"], str(r["value"])))
        counts["system_settings"] = len(tables["system_settings"])

    # 2. Regions
    if "regions" in tables:
        for r in tables["regions"]:
            c.execute("""
            INSERT OR REPLACE INTO regions (id, name, softcode_region, prepaid_region, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (r["id"], r["name"], r["softcode_region"], r["prepaid_region"], r.get("is_active", 1), r.get("created_at"), r.get("updated_at")))
        counts["regions"] = len(tables["regions"])

    # Determine region scope
    meta_reg = data.get("_meta", {}).get("region_id")
    is_full_backup = (meta_reg == "all")

    scoped_tables = ["centers", "acsos", "team_leaders", "employees", "schedule_times", "dispatch_rules"]
    for t in scoped_tables:
        if t not in tables:
            continue
        rows = tables[t]
        if clear_existing:
            if target_region and not is_full_backup:
                c.execute(f'DELETE FROM "{t}" WHERE region_id = ?', (target_region,))
            elif is_full_backup and not target_region:
                c.execute(f'DELETE FROM "{t}"')
            elif target_region and is_full_backup:
                c.execute(f'DELETE FROM "{t}" WHERE region_id = ?', (target_region,))

        for r in rows:
            if target_region and not is_full_backup:
                dest_reg = target_region
            else:
                dest_reg = r.get("region_id", target_region or DEFAULT_REGION_ID)

            r_copy = dict(r)
            r_copy["region_id"] = dest_reg

            c.execute(f'PRAGMA table_info("{t}")')
            valid_cols = [col[1] for col in c.fetchall() if col[1] != 'id']
            cols_to_insert = [k for k in valid_cols if k in r_copy]
            vals = [r_copy[k] for k in cols_to_insert]
            placeholders = ", ".join(["?"] * len(cols_to_insert))
            col_names = ", ".join(cols_to_insert)
            c.execute(f'INSERT INTO "{t}" ({col_names}) VALUES ({placeholders})', vals)

        counts[t] = len(rows)

    conn.commit()
    conn.close()
    return counts


def restore_from_file(filepath: str | Path, target_region: Optional[str] = None) -> Dict[str, int]:
    """Reads a JSON backup file and restores it into the database."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Backup file not found at: {p.resolve()}")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return restore_backup(data, target_region=target_region)


def load_sample_preset(region_id: str = DEFAULT_REGION_ID) -> Dict[str, int]:
    """Loads a sample configuration preset into the specified region."""
    seed_paths = [DATA_DIR / "seeds" / "sample_preset.json"]
    for sp in seed_paths:
        if sp.exists():
            return restore_from_file(sp, target_region=region_id)
    raise FileNotFoundError("Sample seed preset file not found.")


# --- Unified Employee Directory Functions ---

def get_unified_directory(region_id: str = DEFAULT_REGION_ID, auto_sync: bool = True) -> List[Dict[str, Any]]:
    """Returns employee directory in unified format with Position matching user template."""
    if auto_sync:
        try:
            auto_sync_directory_from_disk(region_id)
        except Exception:
            pass
    tls = get_team_leaders(region_id)
    region = get_region_by_id(region_id) or {}
    region_name = region.get("name") or region_id
    acsos_list = get_acsos(region_id)
    acso_map = {a["center_name"].lower().strip(): a for a in acsos_list}
    emps = get_employees(region_id)
    emp_map = {}
    for e in emps:
        code = str(e.get("emp_code") or "").strip()
        name = str(e.get("name") or "").strip().lower()
        if code:
            emp_map[code] = e
        if name:
            emp_map[name] = e

    result = []
    # 1. Team Leaders
    for t in tls:
        c = acso_map.get(t["center_name"].lower().strip(), {})
        code = str(t.get("pp_adl_emp_code", "")).strip()
        name_key = str(t.get("name", "")).strip().lower()
        matched_emp = emp_map.get(code) or emp_map.get(name_key) or {}
        phone = str(t.get("phone") or matched_emp.get("phone") or "").strip()
        email = str(t.get("email") or matched_emp.get("email") or "").strip()

        result.append({
            "id": t["id"],
            "region_id": region_id,
            "region_name": region_name,
            "entry_type": "tl",
            "position": "Team Leader",
            "emp_code": code,
            "emp_name": t.get("name", "").strip(),
            "phone": phone,
            "email": email,
            "center_name": t.get("center_name", "").strip(),
            "crm_name": t.get("pd_adl_name_key") or t.get("name", ""),
            "adl_center": c.get("pd_adl_center_key", t.get("center_name", "")).strip(),
            "adtv_center": c.get("pd_adtv_center_key", t.get("adtv_center", t.get("center_name", ""))).strip(),
            "prepaid_center": c.get("pp_adl_center_key", t.get("center_name", "")).strip(),
        })

    # 2. ACSOs
    for a in acsos_list:
        name_key = str(a.get("acso_name", "")).strip().lower()
        code = str(a.get("emp_code") or "").strip()
        matched_emp = (emp_map.get(code) if code else None) or emp_map.get(name_key) or {}
        phone = str(a.get("phone") or matched_emp.get("phone") or "").strip()
        email = str(a.get("email") or matched_emp.get("email") or "").strip()
        if not code:
            code = str(matched_emp.get("emp_code") or "").strip()
        crm_name = a.get("crm_name") if a.get("crm_name") else a.get("acso_name", "").strip()

        result.append({
            "id": a["id"],
            "region_id": region_id,
            "region_name": region_name,
            "entry_type": "acso",
            "position": "ACSO",
            "emp_code": code,
            "emp_name": a.get("acso_name", "").strip(),
            "phone": phone,
            "email": email,
            "center_name": a.get("center_name", "").strip(),
            "crm_name": crm_name,
            "adl_center": a.get("pd_adl_center_key", a.get("center_name", "")).strip(),
            "adtv_center": a.get("pd_adtv_center_key", a.get("adtv_center_display", a.get("center_name", ""))).strip(),
            "prepaid_center": a.get("pp_adl_center_key", a.get("center_name", "")).strip(),
            "pp_adtv_center": a.get("pp_adtv_center_key", "").strip(),
        })

    return result


def import_unified_directory(region_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Imports complete employee directory for a region from uploaded template data.
    Automatically categorizes by Position ('Team Leader' vs 'ACSO') and keeps
    team_leaders, employees, and acsos tables perfectly synchronized with contact details.
    """
    ensure_region_exists(region_id)
    conn = get_connection()
    c = conn.cursor()

    # Clear existing data for this region
    c.execute("DELETE FROM team_leaders WHERE region_id = ?", (region_id,))
    c.execute("DELETE FROM employees WHERE region_id = ?", (region_id,))
    c.execute("DELETE FROM acsos WHERE region_id = ?", (region_id,))
    c.execute("DELETE FROM centers WHERE region_id = ?", (region_id,))

    centers_map = {}
    tl_count = 0
    acso_count = 0

    for idx, r in enumerate(rows):
        emp_code = str(r.get("emp_code") or r.get("Emp Code") or "").strip()
        if emp_code.endswith(".0"):
            emp_code = emp_code[:-2]
        if emp_code.lower() in ("nan", "none", "null"):
            emp_code = ""

        emp_name = str(r.get("emp_name") or r.get("Employee Display name") or "").strip()
        position = str(r.get("position") or r.get("Position") or "Team Leader").strip()
        phone = str(r.get("phone") or r.get("Phone Number") or r.get("Phone") or r.get("Mobile") or "").strip()
        if phone.lower() in ("nan", "none", "null"):
            phone = ""
        elif phone.endswith(".0"):
            phone = phone[:-2]

        email = str(r.get("email") or r.get("gmail") or r.get("Gmail") or r.get("Email") or r.get("Email / Gmail") or "").strip()
        if email.lower() in ("nan", "none", "null"):
            email = ""
        center_name = str(r.get("center_name") or r.get("Center Display name") or "").strip()
        c_key = center_name.lower().strip()
        crm_name_raw = r.get("crm_name") or r.get("Name in Postpaid CRM")
        if crm_name_raw is not None and str(crm_name_raw).strip().lower() not in ("nan", "none", "null", ""):
            crm_name = str(crm_name_raw)
        else:
            crm_name = emp_name
        adl_center = str(r.get("adl_center") or r.get("Center Name in Postpaid ADL") or center_name).strip()
        adtv_center = str(r.get("adtv_center") or r.get("Center Name in Postpaid ADTv") or center_name).strip()
        prepaid_center = str(r.get("prepaid_center") or r.get("Center name in Prepaid") or center_name).strip()

        pp_adl_center = str(r.get("pp_adl_center") or prepaid_center).strip()
        pp_adtv_center_raw = r.get("pp_adtv_center") or r.get("adtv_prepaid_center")
        if pp_adtv_center_raw:
            pp_adtv_center = str(pp_adtv_center_raw).strip()
        else:
            pp_adtv_center = prepaid_center

        if not emp_name and not center_name:
            continue

        is_acso = "acso" in position.lower()

        # Update center details in centers_map
        if c_key:
            if c_key not in centers_map:
                centers_map[c_key] = {
                    "center_name": center_name,
                    "emp_code": emp_code if is_acso else "",
                    "acso_name": emp_name if is_acso else center_name,
                    "crm_name": crm_name if is_acso else (center_name if not is_acso else emp_name),
                    "adtv_acso_name": emp_name if is_acso else center_name,
                    "adl_center_display": center_name,
                    "adtv_center_display": adtv_center,
                    "pd_adl_center_key": adl_center,
                    "pd_adtv_center_key": adtv_center,
                    "pp_adl_center_key": pp_adl_center,
                    "pp_adtv_center_key": pp_adtv_center,
                    "phone": phone if is_acso else "",
                    "email": email if is_acso else "",
                    "sort_order": len(centers_map) + 1
                }
            elif is_acso:
                centers_map[c_key]["acso_name"] = emp_name
                centers_map[c_key]["crm_name"] = crm_name
                if emp_code:
                    centers_map[c_key]["emp_code"] = emp_code
                centers_map[c_key]["adtv_acso_name"] = emp_name
                if phone:
                    centers_map[c_key]["phone"] = phone
                if email:
                    centers_map[c_key]["email"] = email
                if adtv_center:
                    centers_map[c_key]["adtv_center_display"] = adtv_center
                    centers_map[c_key]["pd_adtv_center_key"] = adtv_center
                if adl_center:
                    centers_map[c_key]["pd_adl_center_key"] = adl_center
                if prepaid_center:
                    centers_map[c_key]["pp_adl_center_key"] = pp_adl_center
                    centers_map[c_key]["pp_adtv_center_key"] = pp_adtv_center

        if is_acso:
            acso_count += 1
            c.execute("""
            INSERT INTO employees (region_id, emp_code, name, role, center_name, phone, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                region_id,
                emp_code,
                emp_name,
                "ACSO",
                center_name,
                phone,
                email
            ))
        else:
            tl_count += 1
            c.execute("""
            INSERT INTO team_leaders 
            (region_id, center_name, name, adtv_center, adtv_name, pd_adl_name_key, pd_adtv_name_key, pp_adl_emp_code, pp_adtv_emp_code, phone, email, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                region_id,
                center_name,
                emp_name,
                adtv_center,
                emp_name,
                crm_name,
                crm_name,
                emp_code,
                emp_code,
                phone,
                email,
                tl_count
            ))

            c.execute("""
            INSERT INTO employees (region_id, emp_code, name, role, center_name, phone, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                region_id,
                emp_code,
                emp_name,
                "Team Leader",
                center_name,
                phone,
                email
            ))

    # Auto-resolve cross-center adtv_acso_name (e.g. Olavakkod ADTv center OTTAPALAM -> Binoy .B)
    for c_key, c_info in centers_map.items():
        adtv_c = str(c_info.get("adtv_center_display") or "").strip().lower()
        if adtv_c and adtv_c != c_key:
            target = next((v for k, v in centers_map.items() if k in adtv_c or adtv_c in k), None)
            if target and target.get("acso_name"):
                c_info["adtv_acso_name"] = target["acso_name"]

    # Insert Centers and ACSOs for all unique centers
    for c_key, c_info in centers_map.items():
        c.execute("""
        INSERT INTO centers (region_id, center_name, adl_area_key, adtv_amo_key, prepaid_area_key, sort_order)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            region_id,
            c_info["center_name"],
            c_info.get("adl_area_key", c_info["center_name"]),
            c_info.get("adtv_amo_key", c_info["center_name"]),
            c_info.get("prepaid_area_key", c_info["center_name"]),
            c_info["sort_order"]
        ))

        c.execute("""
        INSERT INTO acsos
        (region_id, center_name, acso_name, adtv_acso_name, adl_center_display, adtv_center_display,
         pd_adl_center_key, pd_adtv_center_key, pp_adl_center_key, pp_adtv_center_key, phone, email, sort_order,
         crm_name, emp_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            region_id,
            c_info["center_name"],
            c_info["acso_name"],
            c_info["adtv_acso_name"],
            c_info["adl_center_display"],
            c_info["adtv_center_display"],
            c_info["pd_adl_center_key"],
            c_info["pd_adtv_center_key"],
            c_info["pp_adl_center_key"],
            c_info["pp_adtv_center_key"],
            c_info.get("phone", ""),
            c_info.get("email", ""),
            c_info["sort_order"],
            c_info.get("crm_name") or c_info["acso_name"],
            c_info.get("emp_code", "")
        ))

    conn.commit()
    conn.close()

    try:
        sync_directory_to_json(region_id)
    except Exception:
        pass

    return {
        "team_leaders_imported": tl_count,
        "acsos_imported": acso_count,
        "total_employees_imported": tl_count + acso_count,
        "centers_configured": len(centers_map)
    }


def add_unified_directory_row(region_id: str, data: Dict[str, Any]) -> int:
    """Adds a single employee directory row."""
    emp_code = str(data.get("emp_code") or "").strip()
    emp_name = str(data.get("emp_name") or "").strip()
    position = str(data.get("position") or "Team Leader").strip()
    phone = str(data.get("phone") or "").strip()
    email = str(data.get("email") or data.get("gmail") or "").strip()
    center_name = str(data.get("center_name") or "").strip()
    crm_name = str(data.get("crm_name") or emp_name).strip()
    adl_center = str(data.get("adl_center") or center_name).strip()
    adtv_center = str(data.get("adtv_center") or center_name).strip()
    prepaid_center = str(data.get("prepaid_center") or center_name).strip()

    is_acso = "acso" in position.lower()

    if is_acso:
        row_id = add_acso(region_id, {
            "center_name": center_name,
            "acso_name": emp_name,
            "adtv_acso_name": emp_name,
            "adl_center_display": center_name,
            "adtv_center_display": adtv_center,
            "pd_adl_center_key": adl_center,
            "pd_adtv_center_key": adtv_center,
            "pp_adl_center_key": prepaid_center,
            "pp_adtv_center_key": prepaid_center,
            "phone": phone,
            "email": email,
            "crm_name": crm_name,
            "emp_code": emp_code,
        })
        add_employee(region_id, {
            "emp_code": emp_code,
            "name": emp_name,
            "role": "ACSO",
            "center_name": center_name,
            "phone": phone,
            "email": email,
        })
    else:
        row_id = add_team_leader(region_id, {
            "center_name": center_name,
            "name": emp_name,
            "adtv_center": adtv_center,
            "adtv_name": emp_name,
            "pd_adl_name_key": crm_name,
            "pd_adtv_name_key": crm_name,
            "pp_adl_emp_code": emp_code,
            "pp_adtv_emp_code": emp_code,
            "phone": phone,
            "email": email,
        })
        add_employee(region_id, {
            "emp_code": emp_code,
            "name": emp_name,
            "role": "Team Leader",
            "center_name": center_name,
            "phone": phone,
            "email": email,
        })
        # Ensure center exists in acsos
        acsos = get_acsos(region_id)
        if not any(a["center_name"].lower().strip() == center_name.lower().strip() for a in acsos):
            add_acso(region_id, {
                "center_name": center_name,
                "acso_name": center_name,
                "adtv_acso_name": center_name,
                "adl_center_display": center_name,
                "adtv_center_display": adtv_center,
                "pd_adl_center_key": adl_center,
                "pd_adtv_center_key": adtv_center,
                "pp_adl_center_key": prepaid_center,
                "pp_adtv_center_key": prepaid_center,
                "phone": phone,
                "email": email,
                "crm_name": crm_name,
                "emp_code": emp_code,
            })

    try:
        sync_directory_to_json(region_id)
    except Exception:
        pass

    return row_id


def update_unified_directory_row(row_id: int, data: Dict[str, Any], region_id: str = DEFAULT_REGION_ID) -> bool:
    """Updates an existing employee directory row (TL or ACSO)."""
    entry_type = data.get("entry_type", "tl")
    emp_code = str(data.get("emp_code") or "").strip()
    emp_name = str(data.get("emp_name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    email = str(data.get("email") or data.get("gmail") or "").strip()
    center_name = str(data.get("center_name") or "").strip()
    crm_name = str(data.get("crm_name") or emp_name).strip()
    adl_center = str(data.get("adl_center") or center_name).strip()
    adtv_center = str(data.get("adtv_center") or center_name).strip()
    prepaid_center = str(data.get("prepaid_center") or center_name).strip()

    if entry_type == "acso":
        update_acso(row_id, {
            "center_name": center_name,
            "acso_name": emp_name,
            "adtv_acso_name": emp_name,
            "adl_center_display": center_name,
            "adtv_center_display": adtv_center,
            "pd_adl_center_key": adl_center,
            "pd_adtv_center_key": adtv_center,
            "pp_adl_center_key": prepaid_center,
            "pp_adtv_center_key": prepaid_center,
            "phone": phone,
            "email": email,
            "crm_name": crm_name,
            "emp_code": emp_code,
        })
        conn = get_connection()
        c = conn.cursor()
        if emp_code:
            c.execute("UPDATE employees SET name = ?, phone = ?, email = ? WHERE region_id = ? AND emp_code = ?",
                      (emp_name, phone, email, region_id, emp_code))
        else:
            c.execute("UPDATE employees SET name = ?, phone = ?, email = ? WHERE region_id = ? AND role = 'ACSO' AND LOWER(TRIM(center_name)) = LOWER(TRIM(?))",
                      (emp_name, phone, email, region_id, center_name))
        conn.commit()
        conn.close()
    else:
        update_team_leader(row_id, {
            "center_name": center_name,
            "name": emp_name,
            "adtv_center": adtv_center,
            "adtv_name": emp_name,
            "pd_adl_name_key": crm_name,
            "pd_adtv_name_key": crm_name,
            "pp_adl_emp_code": emp_code,
            "pp_adtv_emp_code": emp_code,
            "phone": phone,
            "email": email,
        })
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
        UPDATE acsos SET
            adtv_center_display = ?,
            pd_adl_center_key = ?,
            pd_adtv_center_key = ?,
            pp_adl_center_key = ?,
            pp_adtv_center_key = ?
        WHERE LOWER(TRIM(center_name)) = LOWER(TRIM(?))
        """, (adtv_center, adl_center, adtv_center, prepaid_center, prepaid_center, center_name))
        if emp_code:
            c.execute("UPDATE employees SET name = ?, phone = ?, email = ? WHERE region_id = ? AND emp_code = ?",
                      (emp_name, phone, email, region_id, emp_code))
        else:
            c.execute("UPDATE employees SET name = ?, phone = ?, email = ? WHERE region_id = ? AND role = 'Team Leader' AND LOWER(TRIM(center_name)) = LOWER(TRIM(?))",
                      (emp_name, phone, email, region_id, center_name))
        conn.commit()
        conn.close()

    try:
        sync_directory_to_json(region_id)
    except Exception:
        pass

    return True



def delete_unified_directory_row(row_id: int, entry_type: str = "tl", region_id: str = DEFAULT_REGION_ID) -> bool:
    """Deletes an employee directory row and keeps JSON synced."""
    conn = get_connection()
    c = conn.cursor()
    success = False
    try:
        if entry_type == "acso":
            c.execute("SELECT acso_name, center_name FROM acsos WHERE id = ?", (row_id,))
            row = c.fetchone()
            if row:
                c.execute("DELETE FROM employees WHERE region_id = ? AND role = 'ACSO' AND (name = ? OR center_name = ?)", (region_id, row[0], row[1]))
            c.execute("DELETE FROM acsos WHERE id = ?", (row_id,))
            success = True
        else:
            c.execute("SELECT name, pp_adl_emp_code FROM team_leaders WHERE id = ?", (row_id,))
            row = c.fetchone()
            if row:
                c.execute("DELETE FROM employees WHERE region_id = ? AND (name = ? OR emp_code = ?)", (region_id, row[0], str(row[1])))
            c.execute("DELETE FROM team_leaders WHERE id = ?", (row_id,))
            success = True
        conn.commit()
    except Exception as e:
        print(f"[Delete Directory Row Error]: {e}")
    finally:
        conn.close()

    try:
        sync_directory_to_json(region_id)
    except Exception:
        pass
    return success


def bulk_delete_unified_directory(items: List[Dict[str, Any]], region_id: str = DEFAULT_REGION_ID) -> int:
    """
    Bulk deletes multiple employee directory rows and keeps JSON synced.
    items: [{"id": 1, "entry_type": "tl"}, {"id": 2, "entry_type": "acso"}, ...]
    Returns the number of successfully deleted entries.
    """
    if not items:
        return 0
    conn = get_connection()
    c = conn.cursor()
    deleted_count = 0
    for it in items:
        rid = it.get("id")
        etype = it.get("entry_type", "tl")
        if not rid:
            continue
        try:
            if etype == "acso":
                c.execute("SELECT acso_name, center_name FROM acsos WHERE id = ?", (int(rid),))
                row = c.fetchone()
                if row:
                    c.execute("DELETE FROM employees WHERE region_id = ? AND role = 'ACSO' AND (name = ? OR center_name = ?)", (region_id, row[0], row[1]))
                c.execute("DELETE FROM acsos WHERE id = ?", (int(rid),))
                deleted_count += 1
            else:
                c.execute("SELECT name, pp_adl_emp_code FROM team_leaders WHERE id = ?", (int(rid),))
                row = c.fetchone()
                if row:
                    c.execute("DELETE FROM employees WHERE region_id = ? AND (name = ? OR emp_code = ?)", (region_id, row[0], str(row[1])))
                c.execute("DELETE FROM team_leaders WHERE id = ?", (int(rid),))
                deleted_count += 1
        except Exception as e:
            print(f"[Bulk Delete Error] ID {rid} ({etype}): {e}")

    conn.commit()
    conn.close()

    try:
        sync_directory_to_json(region_id)
    except Exception:
        pass

    return deleted_count


def sync_directory_to_json(region_id: str = DEFAULT_REGION_ID, file_path: Optional[str | Path] = None) -> str:
    """
    Saves the entire Employee Directory for a region into a standalone, human-readable JSON file.
    Default destination: data/employee_directory_{region_id}.json.
    """
    target = Path(file_path) if file_path else DATA_DIR / f"employee_directory_{region_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    directory_data = get_unified_directory(region_id, auto_sync=False)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(directory_data, f, indent=2, ensure_ascii=False)
    try:
        set_setting(f"dir_sync_mtime_{region_id}", str(target.stat().st_mtime))
    except Exception:
        pass
    return str(target.resolve())


def load_directory_from_json(file_path: Optional[str | Path] = None, region_id: str = DEFAULT_REGION_ID) -> Dict[str, Any]:
    """
    Imports and synchronizes the employee directory for a region from a standalone JSON file.
    """
    target = Path(file_path) if file_path else DATA_DIR / f"employee_directory_{region_id}.json"
    if not target.exists():
        raise FileNotFoundError(f"Employee directory JSON file not found at {target}")
    with open(target, "r", encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, list):
        res = import_unified_directory(region_id, rows)
        try:
            set_setting(f"dir_sync_mtime_{region_id}", str(target.stat().st_mtime))
        except Exception:
            pass
        return res
    raise ValueError("JSON file must contain an array of employee directory objects.")


def auto_sync_directory_from_disk(region_id: str = DEFAULT_REGION_ID) -> bool:
    """
    Automatically synchronizes Employee Directory between disk JSON and SQLite without fail.

    1. Checks candidate JSON files on disk:
       - data/employee_directory_{region_id}.json
    2. If a local JSON file exists on disk:
       - Case A: DB has 0 records (fresh/cleared DB, or new setup where JSON is present):
         Loads and imports the records into SQLite, updating the sync timestamp.
       - Case B: DB has records, but JSON file's modified timestamp (mtime) is newer
         than last recorded sync time by > 1.5s (i.e. file was edited or replaced on disk):
         Re-imports into SQLite to sync local disk changes into the database.
       - Case C: DB has records and JSON is in sync:
         No action needed.
    3. If NO JSON file exists on disk, but SQLite has records:
       - Automatically generates and saves data/employee_directory_{region_id}.json from SQLite.
    """
    try:
        candidates = [DATA_DIR / f"employee_directory_{region_id}.json"]
        # An old browser tab or leftover JSON must not recreate a deleted region.
        if get_region_by_id(region_id) is None:
            return False

        target: Optional[Path] = None
        for p in candidates:
            if p and p.exists():
                target = p
                break

        # Check DB record count
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT (SELECT COUNT(*) FROM team_leaders WHERE region_id = ?) + "
            "(SELECT COUNT(*) FROM acsos WHERE region_id = ?) + "
            "(SELECT COUNT(*) FROM employees WHERE region_id = ?)",
            (region_id, region_id, region_id),
        )
        db_count = c.fetchone()[0]
        conn.close()

        last_sync_str = get_setting(f"dir_sync_mtime_{region_id}", "0")
        try:
            last_sync_mtime = float(last_sync_str)
        except Exception:
            last_sync_mtime = 0.0

        if target and target.exists():
            file_mtime = target.stat().st_mtime
            # Case A: DB has 0 records (fresh DB or empty setup where JSON is present)
            if db_count == 0:
                print(f"[Directory Auto-Sync] Empty database detected for '{region_id}'. Loading from {target.name}...")
                with open(target, "r", encoding="utf-8") as f:
                    content = json.load(f)
                if isinstance(content, list) and content:
                    import_unified_directory(region_id, content)
                    set_setting(f"dir_sync_mtime_{region_id}", str(target.stat().st_mtime))
                    print(f"[Directory Auto-Sync] Synced {len(content)} employee records from {target.name} into SQLite.")
                    return True
                elif isinstance(content, dict) and "tables" in content:
                    restore_backup(content, target_region=region_id, clear_existing=True)
                    set_setting(f"dir_sync_mtime_{region_id}", str(target.stat().st_mtime))
                    print(f"[Directory Auto-Sync] Restored configuration from {target.name} into SQLite.")
                    return True

            # Case B: JSON file was modified externally on disk (mtime newer than last recorded sync by > 1.5s)
            elif file_mtime > (last_sync_mtime + 1.5):
                print(f"[Directory Auto-Sync] Detected updated {target.name} on disk (mtime={file_mtime} > last={last_sync_mtime}). Syncing to SQLite...")
                with open(target, "r", encoding="utf-8") as f:
                    content = json.load(f)
                if isinstance(content, list) and content:
                    import_unified_directory(region_id, content)
                    set_setting(f"dir_sync_mtime_{region_id}", str(target.stat().st_mtime))
                    print(f"[Directory Auto-Sync] Auto-synced {len(content)} records from updated {target.name} into SQLite.")
                    return True

            return False

        else:
            # Case C: No JSON on disk, but DB has records -> export so JSON is available on disk
            if db_count > 0:
                sync_directory_to_json(region_id)
                return True

    except Exception as e:
        print(f"[Directory Auto-Sync] [!] Error syncing directory for '{region_id}': {e}")
    return False


# Auto-sync directory on module load
try:
    auto_sync_directory_from_disk(DEFAULT_REGION_ID)
except Exception:
    pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Region Database & Configuration CLI")
    parser.add_argument("--backup", nargs="?", const="backup.json", help="Export full configuration backup to JSON")
    parser.add_argument("--restore", type=str, help="Import and restore configuration from a JSON backup file")
    parser.add_argument("--load-sample", action="store_true", help="Restore the optional sample roster into the selected region")
    parser.add_argument("--region", type=str, default=DEFAULT_REGION_ID, help="Target region ID (defaults to region.json)")
    parser.add_argument("--clear", action="store_true", help="Clear all configured roster data for a region")
    args = parser.parse_args()

    if args.backup:
        out_file = Path(args.backup)
        data = export_backup()
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Full configuration backed up to {out_file.resolve()}")
    elif args.restore:
        counts = restore_from_file(args.restore, target_region=args.region)
        print(f"[OK] Restored configuration from {args.restore}: {counts}")
    elif args.load_sample:
        counts = load_sample_preset(args.region)
        print(f"[OK] Loaded sample preset into '{args.region}': {counts}")
    elif args.clear:
        conn = get_connection()
        c = conn.cursor()
        for t in ["centers", "acsos", "team_leaders", "employees", "schedule_times", "dispatch_rules"]:
            c.execute(f'DELETE FROM "{t}" WHERE region_id = ?', (args.region,))
        conn.commit()
        conn.close()
        print(f"[OK] Cleared all configured data for region '{args.region}'")
    else:
        parser.print_help()

