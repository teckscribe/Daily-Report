# Ubuntu 24/7 Power Reboot Survival & Systemd Service Guide

This document explains how to set up the **Asianet Kerala Complaint Tracker & Web Manager** to run permanently on an **Ubuntu Desktop** machine, surviving power cuts, accidental reboots, and network reconnects without requiring manual intervention.

---

## 1. Why Systemd Survives Power Reboots

When an Ubuntu Desktop machine experiences a sudden power outage and turns back on:
1. The Linux kernel initializes and executes `systemd` as process ID 1 (`PID 1`).
2. Systemd loads all services enabled under `multi-user.target`.
3. The `daily-work-report.service` has:
   - `Restart=always`: If the process crashes or gets killed, systemd automatically restarts it within 10 seconds.
   - `RestartSec=10`: Grace period between crash and resurrection.
   - `After=network-online.target`: Waits until the network interfaces (LAN/Wi-Fi) have acquired an IP address and internet route.
   - `WantedBy=multi-user.target`: Starts on every system boot automatically before user login.
4. The service runs:
   ```bash
   python -m uvicorn web_server:app --host 0.0.0.0 --port 8201
   ```
   This launches both the **FastAPI Web UI on port 8201** and the **24/7 background asyncio scheduler loop** (`background_scheduler_loop`).

---

## 2. One-Step Automated Installation

On your Ubuntu desktop machine, open a terminal inside the project repository directory and run:

```bash
chmod +x setup_ubuntu_service.sh
./setup_ubuntu_service.sh
```

### What this script does automatically:
1. Installs all required Linux shared libraries for Python 3, venv, SQLite, and Chromium.
2. Creates and configures the Python virtual environment (`venv/`).
3. Installs dependencies from `requirements.txt` and downloads Playwright Chromium binaries.
4. Generates `/etc/systemd/system/daily-work-report.service` bound to the current directory and user.
5. Enables the service (`sudo systemctl enable daily-work-report.service`) so it starts upon every boot.
6. Masks desktop sleep/suspend so Ubuntu Desktop does not go to sleep when left unattended on AC power.
7. Starts the service immediately.

---

## 3. Essential Systemd Commands

| Action | Command |
| :--- | :--- |
| **Check Live Status** | `sudo systemctl status daily-work-report` |
| **View Live Real-Time Logs** | `sudo journalctl -u daily-work-report -f` |
| **Restart Service Manually** | `sudo systemctl restart daily-work-report` |
| **Stop Service** | `sudo systemctl stop daily-work-report` |
| **Start Service** | `sudo systemctl start daily-work-report` |
| **Disable Boot Autostart** | `sudo systemctl disable daily-work-report` |
| **Re-enable Boot Autostart** | `sudo systemctl enable daily-work-report` |

---

## 4. WhatsApp Web Session Persistence on Linux

- The Playwright WhatsApp dispatcher stores all cookies, local storage, and IndexedDB tokens inside:
  ```
  data/whatsapp_session/
  ```
- Once you scan the QR code **once**, the session remains authenticated across reboots.
- On Linux, Playwright runs with `headless=True` and sandbox flags (`--no-sandbox`, `--disable-dev-shm-usage`), meaning it does **not** need an active X11/Wayland desktop display to capture and send reports.

---

## 5. BIOS Power Settings (Important for Physical Desktop Reboot)

To make an Ubuntu desktop machine physically power back on after an electricity outage:
1. Reboot the PC and press `Del`, `F2`, or `F12` to enter the motherboard **BIOS / UEFI Settings**.
2. Navigate to the **Power Management** (or **APM Configuration**) tab.
3. Look for the setting named:
   - **"Restore on AC/Power Loss"** or **"After Power Loss"** or **"AC Back"**
4. Change the setting from `Stay Off` or `Previous State` to **`Power On`** (or `Always On`).
5. Save and exit (usually `F10`).

> With **AC Back = Power On** in BIOS and **systemd enable** in Ubuntu, your computer will physically boot up when electricity returns, connect to network, start the web server on port `8201`, and resume the scheduled WhatsApp report deliveries automatically!

---

## 6. Accessing the Web Dashboard

Once started, open your web browser to:
- Locally on the machine: `http://localhost:8201`
- From any PC or phone on the same office Wi-Fi / LAN: `http://<UBUNTU_IP_ADDRESS>:8201`
  *(Find IP with `hostname -I` or `ip a`)*
