"""
db_manager.py
=============
SQLite database manager for Kerala Multi-Region Network Complaint Tracker.
Stores and manages Centers, Team Leaders, ACSO Officers, and Employee Codes region-by-region.
"""
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from config import DATA_DIR

DB_PATH = DATA_DIR / "region_config.db"

KERALA_DISTRICTS = [
    ("thrissur", "Thrissur", "Thrissur", "Thrissur"),
    ("ernakulam", "Ernakulam (Kochi)", "Ernakulam", "Ernakulam"),
    ("kozhikode", "Kozhikode (Calicut)", "Kozhikode", "Kozhikode"),
    ("trivandrum", "Thiruvananthapuram", "Trivandrum", "Trivandrum"),
    ("kannur", "Kannur", "Kannur", "Kannur"),
    ("palakkad", "Palakkad", "Palakkad", "Palakkad"),
    ("kollam", "Kollam", "Kollam", "Kollam"),
    ("kottayam", "Kottayam", "Kottayam", "Kottayam"),
    ("malappuram", "Malappuram", "Malappuram", "Malappuram"),
    ("alappuzha", "Alappuzha", "Alappuzha", "Alappuzha"),
    ("pathanamthitta", "Pathanamthitta", "Pathanamthitta", "Pathanamthitta"),
    ("idukki", "Idukki", "Idukki", "Idukki"),
    ("wayanad", "Wayanad", "Wayanad", "Wayanad"),
    ("kasaragod", "Kasaragod", "Kasaragod", "Kasaragod"),
]


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH.resolve()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initializes schema and seeds default Kerala regions & Thrissur baseline data."""
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
        sort_order INTEGER DEFAULT 0,
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
    c.execute("PRAGMA table_info(acsos)")
    acso_cols = [r[1] for r in c.fetchall()]
    if "adtv_acso_name" not in acso_cols:
        c.execute("ALTER TABLE acsos ADD COLUMN adtv_acso_name TEXT")
        c.execute("UPDATE acsos SET adtv_acso_name = acso_name WHERE adtv_acso_name IS NULL")
        conn.commit()

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
        created_at TEXT,
        FOREIGN KEY (region_id) REFERENCES regions (id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()

    # Seed Regions
    now_str = datetime.now().isoformat()
    for r_id, r_name, sc_reg, pp_reg in KERALA_DISTRICTS:
        c.execute("""
        INSERT OR IGNORE INTO regions (id, name, softcode_region, prepaid_region, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (r_id, r_name, sc_reg, pp_reg, now_str, now_str))
    conn.commit()

    # Seed Thrissur Team Leaders if empty
    c.execute("SELECT COUNT(*) FROM team_leaders WHERE region_id = 'thrissur'")
    if c.fetchone()[0] == 0:
        from report_layout import TEAM_LEADER_ROWS, ACSO_ROWS
        
        # 1. Team leaders
        for idx, tl in enumerate(TEAM_LEADER_ROWS, 1):
            c.execute("""
            INSERT INTO team_leaders 
            (region_id, center_name, name, adtv_center, adtv_name, pd_adl_name_key, pd_adtv_name_key, pp_adl_emp_code, pp_adtv_emp_code, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "thrissur", tl.adl_center, tl.adl_name, tl.adtv_center, tl.adtv_name,
                tl.pd_adl_name_key, tl.pd_adtv_name_key, str(tl.pp_adl_emp_code), str(tl.pp_adtv_emp_code), idx
            ))

            # Also seed employee code
            c.execute("""
            INSERT INTO employees (region_id, emp_code, name, role, center_name, phone)
            VALUES (?, ?, ?, 'Team Leader', ?, '')
            """, ("thrissur", str(tl.pp_adl_emp_code), tl.adl_name.strip(), tl.adl_center))

        # 2. ACSOs
        for idx, a in enumerate(ACSO_ROWS, 1):
            c.execute("""
            INSERT INTO acsos 
            (region_id, center_name, acso_name, adtv_acso_name, adl_center_display, adtv_center_display, pd_adl_center_key, pd_adtv_center_key, pp_adl_center_key, pp_adtv_center_key, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "thrissur", a.adl_center, a.adl_acso, a.adtv_acso, a.adl_center, a.adtv_center,
                a.pd_adl_center_key, a.pd_adtv_center_key, a.pp_adl_center_key, a.pp_adtv_center_key, idx
            ))

            # Center records
            c.execute("""
            INSERT INTO centers (region_id, center_name, adl_area_key, adtv_amo_key, prepaid_area_key, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "thrissur", a.adl_center, a.pd_adl_center_key, a.pd_adtv_center_key, a.pp_adl_center_key, idx
            ))

        conn.commit()

    # Seed Default Schedule Times if empty
    c.execute("SELECT COUNT(*) FROM schedule_times")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO schedule_times (region_id, run_time, label, is_enabled, created_at)
        VALUES ('thrissur', '08:00', 'Morning Operational Report (08:00 AM)', 1, ?)
        """, (now_str,))
        c.execute("""
        INSERT INTO schedule_times (region_id, run_time, label, is_enabled, created_at)
        VALUES ('thrissur', '15:00', 'Afternoon Operational Report (03:00 PM)', 1, ?)
        """, (now_str,))
        conn.commit()

    # Seed Default Dispatch Rules if empty
    c.execute("SELECT COUNT(*) FROM dispatch_rules")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO dispatch_rules (region_id, rule_name, report_type, target_recipients, is_enabled, created_at, updated_at)
        VALUES ('thrissur', 'ADL Team Leader Reports', 'adl_tl', 'NW Team TCR- REGION, +919633889430', 1, ?, ?)
        """, (now_str, now_str))
        c.execute("""
        INSERT INTO dispatch_rules (region_id, rule_name, report_type, target_recipients, is_enabled, created_at, updated_at)
        VALUES ('thrissur', 'ADTv Team Leader Reports', 'adtv_tl', 'NW Team TCR- REGION, +919633889430', 1, ?, ?)
        """, (now_str, now_str))
        c.execute("""
        INSERT INTO dispatch_rules (region_id, rule_name, report_type, target_recipients, is_enabled, created_at, updated_at)
        VALUES ('thrissur', 'ADL ACSO Centers Report', 'adl_acso', 'NW Team TCR- REGION, +919633889430', 1, ?, ?)
        """, (now_str, now_str))
        c.execute("""
        INSERT INTO dispatch_rules (region_id, rule_name, report_type, target_recipients, is_enabled, created_at, updated_at)
        VALUES ('thrissur', 'ADTv ACSO Centers Report', 'adtv_acso', 'NW Team TCR- REGION, +919633889430', 1, ?, ?)
        """, (now_str, now_str))
        conn.commit()

    # Seed Default Master Setting if empty
    c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('scheduler_enabled', '1')")
    conn.commit()

    conn.close()


# --- Database Operations ---

def get_all_regions() -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT r.*,
           (SELECT COUNT(*) FROM centers WHERE region_id = r.id) as center_count,
           (SELECT COUNT(*) FROM team_leaders WHERE region_id = r.id) as tl_count,
           (SELECT COUNT(*) FROM acsos WHERE region_id = r.id) as acso_count,
           (SELECT COUNT(*) FROM employees WHERE region_id = r.id) as emp_count
    FROM regions r
    ORDER BY CASE WHEN r.id = 'thrissur' THEN 0 ELSE 1 END, r.name ASC
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
    if region_id == "thrissur":
        return False  # Protect master baseline region
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
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO team_leaders 
    (region_id, center_name, name, adtv_center, adtv_name, pd_adl_name_key, pd_adtv_name_key, pp_adl_emp_code, pp_adtv_emp_code, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        int(data.get("sort_order", 0))
    ))
    tl_id = c.lastrowid
    conn.commit()
    conn.close()
    return tl_id


def update_team_leader(tl_id: int, data: Dict[str, Any]) -> bool:
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
        sort_order = ?
    WHERE id = ?
    """, (
        data.get("center_name", "").strip(),
        data.get("name", ""),
        data.get("adtv_center", "").strip(),
        data.get("adtv_name", ""),
        data.get("pd_adl_name_key", ""),
        data.get("pd_adtv_name_key", ""),
        str(data.get("pp_adl_emp_code", "")).strip(),
        str(data.get("pp_adtv_emp_code", "")).strip(),
        int(data.get("sort_order", 0)),
        tl_id
    ))
    conn.commit()
    conn.close()
    return True


def delete_team_leader(tl_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
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
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO acsos 
    (region_id, center_name, acso_name, adtv_acso_name, adl_center_display, adtv_center_display, pd_adl_center_key, pd_adtv_center_key, pp_adl_center_key, pp_adtv_center_key, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        int(data.get("sort_order", 0))
    ))
    acso_id = c.lastrowid
    conn.commit()
    conn.close()
    return acso_id


def update_acso(acso_id: int, data: Dict[str, Any]) -> bool:
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
        sort_order = ?
    WHERE id = ?
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
        int(data.get("sort_order", 0)),
        acso_id
    ))
    conn.commit()
    conn.close()
    return True


def delete_acso(acso_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
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


def add_employee(region_id: str, data: Dict[str, Any]) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO employees (region_id, emp_code, name, role, center_name, phone)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        region_id,
        str(data.get("emp_code", "")).strip(),
        data.get("name", "").strip(),
        data.get("role", "Technician").strip(),
        data.get("center_name", "").strip(),
        data.get("phone", "").strip()
    ))
    eid = c.lastrowid
    conn.commit()
    conn.close()
    return eid


def update_employee(emp_id: int, data: Dict[str, Any]) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE employees SET
        emp_code = ?,
        name = ?,
        role = ?,
        center_name = ?,
        phone = ?
    WHERE id = ?
    """, (
        str(data.get("emp_code", "")).strip(),
        data.get("name", "").strip(),
        data.get("role", "").strip(),
        data.get("center_name", "").strip(),
        data.get("phone", "").strip(),
        emp_id
    ))
    conn.commit()
    conn.close()
    return True


def delete_employee(emp_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
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
        data.get("region_id", "thrissur").strip(),
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

def get_schedule_times(region_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    c = conn.cursor()
    if region_id:
        c.execute("SELECT * FROM schedule_times WHERE region_id = ? ORDER BY run_time ASC", (region_id,))
    else:
        c.execute("SELECT * FROM schedule_times ORDER BY run_time ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def add_schedule_time(region_id: str, run_time: str, label: str = "") -> int:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    c.execute("""
    INSERT INTO schedule_times (region_id, run_time, label, is_enabled, created_at)
    VALUES (?, ?, ?, 1, ?)
    """, (region_id.strip(), run_time.strip(), label.strip(), now_str))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def update_schedule_time(time_id: int, run_time: str, label: str = "", is_enabled: int = 1) -> bool:
    conn = get_connection()
    c = conn.cursor()
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


# Auto-initialize on first import
init_db()
