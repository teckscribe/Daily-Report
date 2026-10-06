#!/usr/bin/env bash
# ==============================================================================
# Daily Work Report & 24/7 Automated Operations Dispatcher
# Ubuntu Desktop & Server - Systemd Power Reboot Survival Setup Script
# ==============================================================================

set -eo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="daily-work-report"
ACTUAL_USER="${SUDO_USER:-$USER}"
ACTUAL_HOME="$(eval echo "~$ACTUAL_USER")"

echo "========================================================================="
echo "   Daily Work Report - 24/7 Reboot Survival Service Setup                "
echo "========================================================================="
echo "  Deploy Directory : $APP_DIR"
echo "  Service User     : $ACTUAL_USER"
echo "  Web Manager Port : 8201"
echo "========================================================================="

# 1. System packages for Python and SQLite
echo ""
echo "[1/6] Installing Linux system packages for Python 3..."
sudo apt-get update -qq

# Detect Ubuntu 24.04+ (Noble) 64-bit time package naming
ASOUND_PKG="libasound2"
if apt-cache show libasound2t64 >/dev/null 2>&1; then
    ASOUND_PKG="libasound2t64"
fi

sudo apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    "$ASOUND_PKG"

# 2. Virtual Environment
echo ""
echo "[2/6] Configuring Python virtual environment..."
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

# 3. Python Dependencies
echo ""
echo "[3/6] Installing Python packages and Playwright browser engines..."
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
"$APP_DIR/venv/bin/playwright" install chromium
"$APP_DIR/venv/bin/playwright" install-deps chromium || true

# 4. Prepare data directory and permissions
echo ""
echo "[4/6] Setting permissions for database and WhatsApp session cache..."
mkdir -p "$APP_DIR/data" "$APP_DIR/output"
sudo chown -R "$ACTUAL_USER":"$ACTUAL_USER" "$APP_DIR"

# 5. Systemd Service Creation (Survives Power Outage & Reboot)
echo ""
echo "[5/6] Creating systemd service files in /etc/systemd/system/..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TG_SERVICE_FILE="/etc/systemd/system/daily-work-telegram.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Daily Work Report & Regional Operations Manager (Port 8201)
Documentation=https://github.com/teckscribe/Daily-Report
After=network.target network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$ACTUAL_HOME
ExecStart=/bin/bash -c "cd '$APP_DIR' && exec ./venv/bin/python -m uvicorn web_server:app --host 0.0.0.0 --port 8201"
Restart=always
RestartSec=10
TimeoutStartSec=60
Environment="PYTHONUNBUFFERED=1"
Environment="PORT=8201"
Environment="HOME=$ACTUAL_HOME"
Environment="PATH=$APP_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Sandbox & File Descriptors
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo bash -c "cat > $TG_SERVICE_FILE" <<EOF
[Unit]
Description=Daily QOS Tracker — Telegram Operations Control Daemon
Documentation=https://github.com/teckscribe/Daily-Report
After=network.target network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$ACTUAL_HOME
ExecStart=/bin/bash -c "cd '$APP_DIR' && exec ./venv/bin/python telegram_bot.py"
Restart=always
RestartSec=10
TimeoutStartSec=30
Environment="PYTHONUNBUFFERED=1"
Environment="HOME=$ACTUAL_HOME"
Environment="PATH=$APP_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Sandbox & File Descriptors
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable and Start Services
echo ""
echo "[6/6] Reloading systemd, enabling auto-boot on power restore, and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"
sudo systemctl enable "daily-work-telegram.service"
sudo systemctl restart "daily-work-telegram.service"

# Prevent Ubuntu Desktop from sleeping/suspending when idle
if command -v systemctl >/dev/null 2>&1; then
    echo "Configuring desktop power settings to prevent automatic sleep/suspend..."
    sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
fi

echo ""
echo "========================================================================="
echo " [SUCCESS] 24/7 Power Reboot Survival Services are Active!"
echo "========================================================================="
echo "  Web Management UI : http://localhost:8201  (or http://<IP>:8201)"
echo "  Web Service Status: sudo systemctl status ${SERVICE_NAME}"
echo "  Telegram Bot Status: sudo systemctl status daily-work-telegram"
echo "  Web Live Logs     : sudo journalctl -u ${SERVICE_NAME} -f"
echo "  Telegram Logs     : sudo journalctl -u daily-work-telegram -f"
echo "  Restart All       : sudo systemctl restart ${SERVICE_NAME} daily-work-telegram"
echo "========================================================================="
