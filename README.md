# Asianet Kerala Network Complaint Tracker & Automated Operations Dispatcher

[![Port: 8201](https://img.shields.io/badge/Port-8201-blue.svg)](http://localhost:8201)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![Playwright](https://img.shields.io/badge/Renderer-Playwright%20Retina-2EAD33.svg)](https://playwright.dev)
[![Ubuntu 24/7](https://img.shields.io/badge/Deployment-Ubuntu%20Systemd%2024%2F7-E95420.svg)](docs/UBUNTU_SERVICE_SETUP.md)

An enterprise automation engine that logs into Softcode CRMS and Prepaid SMS portals, calculates daily complaint aging and totals across all 14 Kerala districts with 100% mathematical parity, renders high-definition Retina JPEG cards, and dispatches them automatically to dedicated WhatsApp groups on custom schedules.

> 📖 **Complete Specification**: For exhaustive formula documentation, sheet wirings, and architectural specifications, see [**PROJECT_BRIEF.md**](PROJECT_BRIEF.md).

---

## ⚡ Core Features

- **Automated CRM Scraping**: Automated ticket downloads for ADL Broadband (`RFCRM014`), ADTv Digital TV (`RFCRM015`), and Prepaid tickets via Playwright.
- **100% Mathematical Parity**: Pure-Python calculation engine matching `Daily Complint Tracker.xls` down to the exact ticket count.
- **High-DPI Retina Cards**: 4 standalone report cards rendered at 2.5x resolution for crystal-clear mobile WhatsApp viewing:
  1. `ADL_Complaint_Pending.jpg` (Broadband Team Leader view)
  2. `ADTv_Complaint_Pending.jpg` (Digital TV Team Leader view)
  3. `ADL_ACSO_Complaint_Pending.jpg` (Broadband ACSO Centers view)
  4. `ADTv_ACSO_Complaint_Pending.jpg` (Digital TV ACSO Centers view)
- **WhatsApp Web Dispatcher**: Sends full-width photo bubbles to groups and mobile numbers with thread-safe locking and automatic modal popup dismissal.
- **Web Operations Portal (Port 8201)**:
  - Add, edit, and delete Centers, Team Leaders, ACSOs, and Employee codes.
  - Multi-region switching across all 14 Kerala districts.
  - Scheduled daily triggers (e.g. 08:00 AM, 03:00 PM) with 24/7 background asyncio scheduler.
  - **"Generate and Send Now"** test button for specific mobile numbers.
  - Report-to-Group routing rules.
- **Ubuntu 24/7 Power Reboot Survival**: Systemd service (`asianet-tracker.service`) with auto-restart on power loss, boot persistence, and BIOS power recovery.

---

## 🚀 Quick Start (Windows)

1. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   ```
2. **Configure Credentials**:
   Copy `.env.example` to `.env` and configure credentials:
   ```ini
   SOFTCODE_USER=your_crm_user
   SOFTCODE_PASS=your_crm_pass
   PREPAID_USER=your_prepaid_user
   PREPAID_PASS=your_prepaid_pass
   WHATSAPP_GROUPS=NW Team TCR- REGION, +919633889430
   WEB_API_TOKEN=generate-a-long-random-token
   PORT=8201
   ```
3. **Start the Web Operations Portal**:
   Double-click `Start_Web_Manager.bat` or run:
   ```powershell
   python -m uvicorn web_server:app --host 127.0.0.1 --port 8201 --reload
   ```
   Open your browser to: **`http://localhost:8201`**

---

## 🐧 Ubuntu 24/7 Server / Desktop Setup

To run permanently on an Ubuntu desktop or server with automatic boot on power recovery:

```bash
chmod +x setup_ubuntu_service.sh
./setup_ubuntu_service.sh
```

### Essential Management Commands:
```bash
sudo systemctl status daily-work-report
sudo journalctl -u daily-work-report -f
sudo systemctl restart daily-work-report
```
For detailed hardware BIOS settings (Restore on AC Power Loss) and systemd configuration, see [**docs/UBUNTU_SERVICE_SETUP.md**](docs/UBUNTU_SERVICE_SETUP.md).

---

## 📁 Repository Structure

```
Daily-Report/
├── PROJECT_BRIEF.md              # Master engineering & formula specification
├── web_server.py                 # FastAPI server, REST API & 24/7 scheduler
├── db_manager.py                 # SQLite database layer (data/region_config.db)
├── report_engine.py              # Mathematical calculation & aging logic
├── report_image_generator.py     # Playwright High-DPI Retina card renderer
├── whatsapp_sender.py            # Thread-safe WhatsApp Web Playwright dispatcher
├── crm_downloader.py             # Softcode CRMS and Prepaid scraper
├── data_processor.py             # Data cleaning & ticket filtering
├── setup_ubuntu_service.sh       # Automated Ubuntu 24/7 service installer
├── daily-work-report.service     # Systemd service unit template
├── templates/
│   └── index.html                # Responsive operations dashboard
├── docs/
│   ├── REPORT_GENERATION_REFERENCE.md
│   └── UBUNTU_SERVICE_SETUP.md
└── requirements.txt              # Python dependencies
```

---

## 🔒 Security & Data Integrity

- `Daily Complint Tracker.xls` is strictly **read-only** reference.
- All dynamic working copies are saved with timestamped filenames under `output/`.
- WhatsApp session credentials (`data/whatsapp_session/`) and login secrets (`.env`) are excluded via `.gitignore`.
