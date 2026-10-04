#!/usr/bin/env bash
# ==============================================================================
# Asianet Kerala Regional Complaint Tracker & 24/7 Automated Dispatcher
# Ubuntu Desktop & Server - Systemd Power Reboot Survival Setup Script
# ==============================================================================

set -eo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="asianet-tracker"
ACTUAL_USER="${SUDO_USER:-$USER}"
ACTUAL_HOME="$(eval echo "~$ACTUAL_USER")"

echo "========================================================================="
echo "   Asianet Complaint Tracker - 24/7 Reboot Survival Service Setup        "
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
echo "[5/6] Creating systemd service file: /etc/systemd/system/${SERVICE_NAME}.service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Asianet Kerala Regional Operations Manager & Automated Dispatcher (Port 8201)
Documentation=https://github.com/teckscribe/Daily-Report
After=network.target network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory="$APP_DIR"
ExecStart="$APP_DIR/venv/bin/python" -m uvicorn web_server:app --host 0.0.0.0 --port 8201
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

# 6. Enable and Start Service
echo ""
echo "[6/6] Reloading systemd, enabling auto-boot on power restore, and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

# Prevent Ubuntu Desktop from sleeping/suspending when idle
if command -v systemctl >/dev/null 2>&1; then
    echo "Configuring desktop power settings to prevent automatic sleep/suspend..."
    sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
fi

echo ""
echo "========================================================================="
echo " [SUCCESS] 24/7 Power Reboot Survival Service is Active!"
echo "========================================================================="
echo "  Web Management UI : http://localhost:8201  (or http://<IP>:8201)"
echo "  Check Status      : sudo systemctl status ${SERVICE_NAME}"
echo "  Live Logs         : sudo journalctl -u ${SERVICE_NAME} -f"
echo "  Restart Service   : sudo systemctl restart ${SERVICE_NAME}"
echo "  Stop Service      : sudo systemctl stop ${SERVICE_NAME}"
echo "========================================================================="
