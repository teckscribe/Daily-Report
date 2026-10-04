"""
logger_setup.py
================
Enterprise-grade Dual Logging, 3-Day Retention, and Diagnostic Analyzer:
1. Running Logs (logs/running_YYYY-MM-DD.log) - Captures all stdout, info, and runtime execution.
2. Error Logs (logs/error_YYYY-MM-DD.log) - Captures all stderr, warnings, errors, and tracebacks.
3. 3-Day Auto-Retention - Automatically purges log files older than 3 days.
4. Issue Analysis Engine - Parses error patterns, generates health scores, and recommends fixes.
"""

import os
import re
import sys
import glob
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import LOGS_DIR, LOG_RETENTION_DAYS

# Thread lock for file writes and rotation
LOG_LOCK = threading.Lock()

_is_initialized = False
_orig_stdout = sys.__stdout__
_orig_stderr = sys.__stderr__


def get_today_log_path(log_type: str = "running") -> Path:
    """Returns the Path for today's running or error log file."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    prefix = "error" if log_type == "error" else "running"
    return LOGS_DIR / f"{prefix}_{date_str}.log"


def cleanup_old_logs(retention_days: int = LOG_RETENTION_DAYS) -> List[str]:
    """
    Scans LOGS_DIR and deletes log files older than retention_days (default 3 days).
    Returns list of deleted file names.
    """
    deleted = []
    cutoff_date = datetime.now().date() - timedelta(days=retention_days)

    with LOG_LOCK:
        if not LOGS_DIR.exists():
            return deleted

        for log_file in LOGS_DIR.glob("*.log"):
            try:
                # Match running_YYYY-MM-DD.log or error_YYYY-MM-DD.log
                m = re.search(r"(\d{4}-\d{2}-\d{2})", log_file.name)
                if m:
                    file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    if file_date < cutoff_date:
                        log_file.unlink(missing_ok=True)
                        deleted.append(log_file.name)
                        print(f"[Log Retention] Deleted expired log (> {retention_days} days): {log_file.name}")
                else:
                    # Fallback to mtime for non-standard files
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if (datetime.now() - mtime).days > retention_days:
                        log_file.unlink(missing_ok=True)
                        deleted.append(log_file.name)
                        print(f"[Log Retention] Deleted expired log by mtime (> {retention_days} days): {log_file.name}")
            except Exception as e:
                print(f"[Log Retention] Warning cleaning up {log_file.name}: {e}")

    return deleted


class DualLogStream:
    """
    Stream interceptor that writes output to original console stream
    and simultaneously appends formatted entries to running and/or error log files.
    """
    def __init__(self, original_stream, is_stderr: bool = False):
        self.original_stream = original_stream
        self.is_stderr = is_stderr
        self._buffer = ""

    def write(self, message: str):
        # 1. Always pass through to console so terminal & systemd journal receive output
        try:
            self.original_stream.write(message)
            self.original_stream.flush()
        except Exception:
            pass

        # 2. Buffer lines and write to daily log files
        if not message:
            return

        self._buffer += message
        if "\n" in self._buffer:
            lines = self._buffer.split("\n")
            self._buffer = lines[-1]  # Keep remainder in buffer

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            running_path = get_today_log_path("running")
            error_path = get_today_log_path("error")

            formatted_running = []
            formatted_error = []

            for line in lines[:-1]:
                if not line.strip():
                    continue

                # Add timestamp and stream prefix if not already structured
                if not re.match(r"^\[\d{4}-\d{2}-\d{2}", line):
                    level_tag = "[ERROR]" if self.is_stderr else "[INFO]"
                    entry = f"[{now_str}] {level_tag} {line}\n"
                else:
                    entry = f"{line}\n"

                formatted_running.append(entry)
                if self.is_stderr or any(err_kw in line.upper() for err_kw in ["[ERROR]", "TRACEBACK", "EXCEPTION", "[CRITICAL]"]):
                    formatted_error.append(entry)

            with LOG_LOCK:
                try:
                    if formatted_running:
                        with open(running_path, "a", encoding="utf-8", errors="replace") as f_run:
                            f_run.writelines(formatted_running)
                except Exception:
                    pass

                try:
                    if formatted_error:
                        with open(error_path, "a", encoding="utf-8", errors="replace") as f_err:
                            f_err.writelines(formatted_error)
                except Exception:
                    pass

    def flush(self):
        try:
            self.original_stream.flush()
        except Exception:
            pass


def init_logging():
    """
    Initializes central logging system:
    - Enforces 3-day log directory retention
    - Redirects stdout and stderr through DualLogStream
    - Configures root logger and standard library logging
    """
    global _is_initialized
    if _is_initialized:
        return

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Clean up logs older than 3 days on startup
    cleanup_old_logs(retention_days=LOG_RETENTION_DAYS)

    # 2. Configure Python standard logging handlers
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Prevent duplicate handlers
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        # Daily Running File Handler
        running_path = get_today_log_path("running")
        run_file_handler = logging.FileHandler(running_path, encoding="utf-8")
        run_file_handler.setLevel(logging.INFO)
        run_file_handler.setFormatter(formatter)
        root_logger.addHandler(run_file_handler)

        # Daily Error File Handler (Warnings & Errors only)
        error_path = get_today_log_path("error")
        err_file_handler = logging.FileHandler(error_path, encoding="utf-8")
        err_file_handler.setLevel(logging.WARNING)
        err_file_handler.setFormatter(formatter)
        root_logger.addHandler(err_file_handler)

    # 3. Intercept stdout and stderr so all prints & tracebacks are logged automatically
    sys.stdout = DualLogStream(_orig_stdout, is_stderr=False)
    sys.stderr = DualLogStream(_orig_stderr, is_stderr=True)

    _is_initialized = True
    print(f"[Logging System] Initialized. Storing 3-day rotating running & error logs in: {LOGS_DIR}")


def get_log_files() -> List[Dict[str, Any]]:
    """Returns list of all available log files in logs/ folder with metadata."""
    cleanup_old_logs(retention_days=LOG_RETENTION_DAYS)
    files = []

    if not LOGS_DIR.exists():
        return files

    for p in sorted(LOGS_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True):
        stat = p.stat()
        log_type = "error" if p.name.startswith("error_") else "running"
        files.append({
            "name": p.name,
            "path": str(p),
            "type": log_type,
            "size_kb": round(stat.st_size / 1024, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })

    return files


def read_log_file(file_name: Optional[str] = None, log_type: str = "running", max_lines: int = 500) -> Dict[str, Any]:
    """
    Reads the most recent lines of a specified log file or today's default log file.
    """
    if not file_name:
        target_path = get_today_log_path(log_type)
        file_name = target_path.name
    else:
        # Sanitize filename to prevent directory traversal
        clean_name = os.path.basename(file_name)
        target_path = LOGS_DIR / clean_name

    if not target_path.exists():
        return {
            "file_name": file_name,
            "log_type": log_type,
            "exists": False,
            "lines": [f"Log file '{file_name}' does not exist yet."],
            "total_lines": 0,
        }

    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        tail_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines
        return {
            "file_name": target_path.name,
            "log_type": "error" if target_path.name.startswith("error_") else "running",
            "exists": True,
            "lines": [l.rstrip("\r\n") for l in tail_lines],
            "total_lines": len(all_lines),
            "returned_lines": len(tail_lines),
            "size_kb": round(target_path.stat().st_size / 1024, 2),
        }
    except Exception as e:
        return {
            "file_name": file_name,
            "log_type": log_type,
            "exists": False,
            "lines": [f"Error reading log file: {e}"],
            "total_lines": 0,
        }


def analyze_system_logs(days: int = LOG_RETENTION_DAYS) -> Dict[str, Any]:
    """
    Scans running and error log files for the last N days (default 3),
    extracts anomalies, classifies issues, and computes a health scorecard.
    """
    cleanup_old_logs(retention_days=days)

    now = datetime.now()
    start_date = now.date() - timedelta(days=days - 1)

    total_entries = 0
    error_count = 0
    warning_count = 0

    categories = {
        "whatsapp": {"name": "WhatsApp Automation", "count": 0, "issues": []},
        "crm": {"name": "CRM Downloader & Portals", "count": 0, "issues": []},
        "database": {"name": "Database & Storage", "count": 0, "issues": []},
        "network": {"name": "Network & HTTP API", "count": 0, "issues": []},
        "system": {"name": "System & Runtime Engine", "count": 0, "issues": []},
    }

    recent_errors: List[Dict[str, str]] = []
    file_summaries: List[Dict[str, Any]] = []

    log_files = sorted(LOGS_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)

    for p in log_files:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        if m:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            if file_date < start_date:
                continue

        file_errors = 0
        file_warnings = 0
        file_lines = 0

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    file_lines += 1
                    total_entries += 1
                    line_upper = line.upper()

                    is_error = "ERROR" in line_upper or "EXCEPTION" in line_upper or "TRACEBACK" in line_upper or "CRITICAL" in line_upper
                    is_warning = "WARNING" in line_upper or "WARN" in line_upper

                    if is_error:
                        file_errors += 1
                        error_count += 1

                        # Classify category
                        cat_key = "system"
                        if any(k in line.lower() for k in ["whatsapp", "qrcode", "canvas", "pairing", "phone"]):
                            cat_key = "whatsapp"
                        elif any(k in line.lower() for k in ["crm", "softcode", "prepaid", "portal", "download"]):
                            cat_key = "crm"
                        elif any(k in line.lower() for k in ["sqlite", "database", "locked", "region_config.db", "sql"]):
                            cat_key = "database"
                        elif any(k in line.lower() for k in ["http", "connection", "timeout", "refused", "500", "404", "ssl"]):
                            cat_key = "network"

                        categories[cat_key]["count"] += 1
                        clean_msg = line.strip()
                        if clean_msg not in categories[cat_key]["issues"] and len(categories[cat_key]["issues"]) < 10:
                            categories[cat_key]["issues"].append(clean_msg)

                        if len(recent_errors) < 20:
                            recent_errors.append({
                                "file": p.name,
                                "timestamp": line[:23] if line.startswith("[") else "",
                                "message": clean_msg[:240],
                            })
                    elif is_warning:
                        file_warnings += 1
                        warning_count += 1

            file_summaries.append({
                "file_name": p.name,
                "type": "error" if p.name.startswith("error_") else "running",
                "size_kb": round(p.stat().st_size / 1024, 2),
                "total_lines": file_lines,
                "error_count": file_errors,
                "warning_count": file_warnings,
            })
        except Exception as e:
            print(f"[Log Analyzer] Error reading {p.name}: {e}")

    # Calculate overall health status and score (0 to 100)
    health_score = max(0, min(100, 100 - (error_count * 5) - (warning_count * 1)))

    if error_count == 0 and warning_count == 0:
        health_status = "HEALTHY"
        status_color = "#16a34a"  # Green
        summary_verdict = "All services, background automation loops, and endpoints are running with 0 errors."
    elif error_count == 0 and warning_count > 0:
        health_status = "STABLE"
        status_color = "#0284c7"  # Blue
        summary_verdict = f"System is operating normally with {warning_count} minor operational warning(s)."
    elif error_count < 10:
        health_status = "ATTENTION NEEDED"
        status_color = "#d97706"  # Amber
        summary_verdict = f"Detected {error_count} isolated error(s) over the last {days} days. Review recent error logs."
    else:
        health_status = "CRITICAL"
        status_color = "#dc2626"  # Red
        summary_verdict = f"Detected {error_count} errors. Action recommended: check component diagnostics below."

    # Generate practical recommendations
    recommendations = []
    if categories["whatsapp"]["count"] > 0:
        recommendations.append("WhatsApp Web has reported errors: Check if your phone is connected in the 'WhatsApp Login' tab.")
    if categories["crm"]["count"] > 0:
        recommendations.append("CRM Downloader errors detected: Verify portal connectivity, login credentials, and session tokens.")
    if categories["database"]["count"] > 0:
        recommendations.append("Database lock or SQLite warning detected: Ensure file permissions on data/region_config.db are read/write.")
    if categories["network"]["count"] > 0:
        recommendations.append("Network timeouts reported: Check server internet access and firewall/proxy settings.")
    if not recommendations:
        recommendations.append("System is functioning within nominal parameters. No corrective actions required.")

    return {
        "analysis_timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "retention_days": days,
        "health_status": health_status,
        "health_score": health_score,
        "status_color": status_color,
        "summary_verdict": summary_verdict,
        "total_lines_analyzed": total_entries,
        "total_errors": error_count,
        "total_warnings": warning_count,
        "categories": categories,
        "recent_errors": recent_errors,
        "recommendations": recommendations,
        "file_summaries": file_summaries,
    }
