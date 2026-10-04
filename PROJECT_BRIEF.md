# Asianet Kerala Network Complaint Tracker & Automated Operations Dispatcher
## Master Project Architecture & Engineering Specification

> **Repository**: [https://github.com/teckscribe/Daily-Report](https://github.com/teckscribe/Daily-Report)  
> **Active Port**: `8201` (`http://localhost:8201`)  
> **Master Reference Spreadsheet**: `Daily Complint Tracker.xls` (Strictly **READ-ONLY**; dated working copies saved to `output/`)

---

## 1. Executive Overview & System Purpose

This enterprise system provides 24/7 end-to-end automation for monitoring, calculating, rendering, and delivering **Daily Complaint Pending Reports** for Asianet Kerala Network Operations across all 14 districts of Kerala.

### Core Capabilities:
1. **Automated Data Ingestion**:
   - Direct web-scraping and ticket extraction from Softcode CRMS (`RFCRM014`, `RFCRM015`) and Prepaid SMS portals.
2. **Pure-Python Mathematical Engine**:
   - Replaces manual Excel spreadsheet computation with 100% mathematical parity.
   - Computes aging breakdown (`< 1day`, `1 day`, `2 day`, `3 day`) and total pending complaints.
   - Computes both **Team Leader (TL)** operational center views and **ACSO Officer** administrative views.
3. **High-DPI Retina Graphic Rendering**:
   - Playwright renders standalone, ultra-sharp JPEG report cards at `device_scale_factor=2.5`.
   - Distinctive typography, conditional color bands, and crisp mobile viewing on WhatsApp.
4. **WhatsApp Web Dispatch Routing**:
   - Headless/persistent Playwright automation delivering standalone full-width photo bubbles (no album compression).
   - Thread-safe serialization (`DISPATCH_LOCK`), stale lock cleanup, and modal popup handling.
5. **Multi-Region Management Portal (Port 8201)**:
   - FastAPI + Vanilla JS responsive operations manager.
   - Dynamic configuration for centers, Team Leaders, ACSOs, employee codes, and dispatch rules.
   - Scheduled daily triggers (e.g. 08:00 AM, 03:00 PM) with 24/7 background scheduler.
   - Instant "Generate & Send Now" test utility for custom phone numbers.
6. **Ubuntu 24/7 Power Reboot Survival**:
   - Systemd background service (`asianet-tracker.service`) with auto-restart and boot persistence.
   - BIOS power-loss recovery enabling fully unattended hardware reboot after power cuts.

---

## 2. Operational Hierarchy & Report Structure

The system calculates and renders **4 distinct report cards** per operational cycle:

| Report Code | Report Title | Entity Key | Dimension |
| :--- | :--- | :--- | :--- |
| `adl_tl` | **ADL Complaint Pending** | Team Leader | Operational Centers (Broadband) |
| `adtv_tl` | **ADTv Complaint Pending** | Team Leader | Operational Centers (Digital TV) |
| `adl_acso` | **ADL ACSO Centers Report** | ACSO Officer | Administrative Center Hubs (Broadband) |
| `adtv_acso` | **ADTv ACSO Centers Report** | ACSO Officer | Administrative Center Hubs (Digital TV) |

### Aging Buckets:
- `< 1day`: Logged within the last 24 hours.
- `1 day`: Pending between 24 and 48 hours.
- `2 day`: Pending between 48 and 72 hours.
- `3 day` (or `3+ day`): Pending over 72 hours.
- **Grand Total**: Sum of all pending tickets across all aging categories.

---

## 3. Mathematical Formulas & Sheet Wirings

### 3.1 Strict Spreadsheet Invariant
- **`Daily Complint Tracker.xls` is strictly READ-ONLY**. It serves solely as the gold-standard equation reference.
- Any manual or automated output copy is written to:
  ```
  output/Daily Complint Tracker_YYYYMMDD_HHMMSS.xls
  ```

### 3.2 Postpaid Broadband (`ADL P`)
- **Source**: Softcode CRMS Report `RFCRM014`.
- **Team Leader Mapping**: Column `AU` (`TEAMLEADERNAME`). Matches the Team Leader key in `team_leaders` table.
- **ACSO Area Mapping**: Column `AE` (`AREA`). Matches the Area key in `acsos` table.
- **Aging Determination**: Calculated from ticket registration timestamp versus current run timestamp.

### 3.3 Postpaid Digital TV (`ADTv P`)
- **Source**: Softcode CRMS Report `RFCRM015`.
- **Team Leader Mapping**: Column `AC` (`TEAMLEADERNAME`). Matches the Team Leader key in `team_leaders` table.
- **ACSO AMO Mapping**: Column `S` (`SERVICEAMO`). Matches the AMO key in `acsos` table.

### 3.4 Prepaid Combined Broadband & TV (`Prepaid`)
- **Source**: Prepaid SMS Portal Export (`Pending_tickets_Report.aspx`).
- **Service Differentiation**: Column `M` (`Service`):
  - If contains `"Broadband"` &rarr; Assigned to **ADL Broadband**.
  - If contains `"Digital"` or `"Cable"` &rarr; Assigned to **ADTv Digital TV**.
- **Team Leader Matching**: Column `T` (`Alloted To`) contains the employee code of the supervisor/technician (e.g. `980` matches Shyamkumar).
- **ACSO Matching**: Column `Z` (`Area`) matches the Center / ACSO Area key.

### 3.5 Grand Total Aggregations
For every entity row:
$$\text{Total Complaints} = \text{Postpaid Total} + \text{Prepaid Total}$$
$$\text{Overall Total} = \sum_{\text{entities}} \text{Total Complaints}$$

100% mathematical parity has been verified against CRM production data (e.g. Thrissur baseline: ADL Broadband = 47 [34 postpaid + 13 prepaid], ADTv Digital TV = 425 [359 postpaid + 66 prepaid]).

---

## 4. Web Management Portal (`web_server.py`) - Port 8201

The portal runs on **`http://localhost:8201`** (or `http://<IP>:8201` over local network).

### Dashboard Navigation Tabs:
1. **Team Leaders** (`#tab-tls`):
   - Configure operational center, report display name, ADL match key (`Col AU`), ADTv match key (`Col AC`), and Prepaid employee code (`Col T`).
2. **Centers & ACSOs** (`#tab-centers`):
   - Configure administrative hub center name, ACSO Officer name, Postpaid ADL Area key (`Col AE`), Postpaid ADTv AMO key (`Col S`), Prepaid ADL Area (`Col Z`), and Prepaid ADTv Area (`Col Z`).
3. **Employee Directory** (`#tab-employees`):
   - Maintain technician & supervisor employee codes, names, roles, and mobile numbers.
4. **Report Preview & Dispatch** (`#tab-reports`):
   - Mathematical Verification Engine test button (`/api/regions/{id}/test-engine`).
   - High-DPI Report Card Generator (`/api/regions/{id}/generate-reports`).
   - **Test Delivery Box**: Custom mobile number input (`+919633889430`), report type selector (`All 4`, `ADL TL`, `ADTv TL`, `ADL ACSO`, `ADTv ACSO`), and **"🚀 Generate and Send Now"** button.
5. **Auto Schedule & Routing** (`#tab-automation`):
   - Master 24/7 scheduler toggle (Pause / Resume) and **"🚀 Run Full Cycle Now"** button.
   - **Daily Trigger Times Grid**: Add, edit, pause, or delete 24-hour daily run times (e.g. `08:00`, `15:00`).
   - **Report-to-Group Dispatch Rules Table**: Configure which report card routes to which WhatsApp group name or phone number, with individual **"⚡ Send"** test triggers.
6. **Active Region Selector** (Header):
   - Dynamic switching across all 14 Kerala regions (`thrissur`, `ernakulam`, `calicut`, `trivandrum`, etc.) with instant database synchronization.

---

## 5. WhatsApp Web Dispatch Architecture (`whatsapp_sender.py`)

WhatsApp delivery utilizes a persistent Playwright Chromium browser profile stored in `data/whatsapp_session/`.

### Robustness & Safety Guards:
1. **Thread-Safe Dispatch Lock**:
   - `DISPATCH_LOCK = threading.Lock()` guarantees only one browser session accesses the user data profile at any time, preventing `Opening in existing browser session` crashes.
2. **Stale Lock Cleanup**:
   - Automatically removes any orphaned `SingletonLock`, `SingletonCookie`, or `SingletonSocket` files if a previous process was abruptly killed.
3. **Modern WhatsApp Web Selectors**:
   - Search input uses `#side input, #side div[contenteditable='true'], div[aria-label*='Search']`.
   - Dispatches `Escape` key events to dismiss any modal banners ("Turn on notifications", "Broadcast announcement").
   - Types target group name and presses `Enter` to open top matching chat.
4. **Standalone Full-Width Photos**:
   - Uses file-chooser on `Attach -> Photos & videos` button.
   - Sends each report as an independent photo message with maximum bubble width.
   - Monitors clock icon (`msg-time`) and upload progress bars until confirmed.
   - Enforces an 8-second delivery buffer between photos to ensure complete WebSocket transmission.

---

## 6. Ubuntu 24/7 Reboot Survival & Hardware Setup

To ensure the bot survives electricity cuts, sudden power trips, and system reboots:

### 6.1 Systemd Service Unit (`/etc/systemd/system/asianet-tracker.service`)
```ini
[Unit]
Description=Asianet Kerala Regional Operations Manager & Automated Dispatcher (Port 8201)
After=network.target network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=anoop
WorkingDirectory=/path/to/Daily-Report
ExecStart=/path/to/Daily-Report/venv/bin/python -m uvicorn web_server:app --host 0.0.0.0 --port 8201
Restart=always
RestartSec=10
TimeoutStartSec=60
Environment="PYTHONUNBUFFERED=1"
Environment="PORT=8201"

LimitNOFILE=65535
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 6.2 Automated Linux Installer
Run the included installer:
```bash
chmod +x setup_ubuntu_service.sh
./setup_ubuntu_service.sh
```
This installs OS libraries for Chromium, sets up Python `venv`, configures Playwright, enables systemd autostart on boot, and masks Ubuntu desktop sleep/suspend.

### 6.3 Hardware BIOS Setting (Physical Auto-Power On)
1. Reboot PC and enter BIOS setup (`Del` or `F2`).
2. Go to **Power Management** / **APM Configuration**.
3. Set **"Restore on AC Power Loss"** to **`Power On`**.
4. Save and exit (`F10`).
*When electricity returns after a power outage, the PC automatically boots up, connects to Wi-Fi/LAN, starts the server on port 8201, and resumes the WhatsApp schedule!*

---

## 7. Repository File Manifest & Module Directory

| File / Folder | Role & Description |
| :--- | :--- |
| `web_server.py` | FastAPI application serving REST endpoints, background scheduler, and HTML UI on port 8201. |
| `db_manager.py` | SQLite database manager (`data/region_config.db`) for regions, centers, TLs, ACSOs, rules, and times. |
| `report_engine.py` | Mathematical aggregation engine computing aging days, counts, and grand totals with 100% parity. |
| `report_layout.py` | Data normalization and table structure builder for Team Leader and ACSO reports. |
| `report_image_generator.py` | Playwright-based High-DPI Retina card renderer generating ultra-sharp JPEG report images. |
| `whatsapp_sender.py` | Thread-safe WhatsApp Web Playwright dispatcher with group search, photo uploads, and buffers. |
| `crm_downloader.py` | Playwright web scraper downloading raw ticket exports from Softcode CRMS and Prepaid SMS portals. |
| `data_processor.py` | Dataframe cleaning, header normalization, and regex filtering for ADL, ADTv, and Prepaid tickets. |
| `config.py` | Global environment configuration, directory paths, credentials loading, and defaults. |
| `main.py` | CLI execution entrypoint supporting `--run-now`, `--schedule`, and `--dry-run`. |
| `run_latest_cycle.py` | One-click script to pull fresh tickets, compute equations, render images, and dispatch. |
| `setup_ubuntu_service.sh` | Automated Linux setup script creating the systemd reboot survival service. |
| `asianet-tracker.service` | Systemd service unit template for Linux deployments. |
| `templates/index.html` | Dashboard UI containing the 5 operational tabs, modal dialogs, and responsive CSS styling. |
| `data/region_config.db` | Pre-seeded SQLite database containing all Kerala regions, Thrissur mappings, rules, and times. |
| `docs/REPORT_GENERATION_REFERENCE.md` | In-depth formula reference, column wirings, and reconciliation documentation. |
| `docs/UBUNTU_SERVICE_SETUP.md` | Guide for Ubuntu systemd deployment, BIOS auto-power settings, and maintenance. |
| `Start_Web_Manager.bat` | Windows batch launcher starting the FastAPI server on port 8201. |
| `Run_Complaint_Report_Now.bat` | Windows batch launcher executing a single full report cycle immediately. |
| `Start_247_Scheduler.bat` | Windows batch launcher starting the 24/7 background scheduler loop. |
| `requirements.txt` | Python package dependencies (FastAPI, uvicorn, playwright, pandas, openpyxl, xlrd, etc.). |
| `.gitignore` | Protects sensitive credentials (`.env`), session tokens (`whatsapp_session/`), and temporary files. |

---

## 8. Quickstart Guide for New Engineers & Chats

1. **Clone Repository**:
   ```bash
   git clone https://github.com/teckscribe/Daily-Report.git
   cd Daily-Report
   ```
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. **Configure Environment (`.env`)**:
   ```env
   SOFTCODE_USER=your_username
   SOFTCODE_PASS=your_password
   PREPAID_USER=your_prepaid_user
   PREPAID_PASS=your_prepaid_password
   WHATSAPP_GROUPS=NW Team TCR- REGION, +919633889430
   PORT=8201
   ```
4. **Launch Web Operations Manager**:
   ```bash
   python -m uvicorn web_server:app --host 0.0.0.0 --port 8201 --reload
   ```
5. **Access Dashboard**:
   Open **`http://localhost:8201`** in any web browser.
