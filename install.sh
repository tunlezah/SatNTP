#!/bin/bash
# SatNTP Installation Script
# Installs the GPS-disciplined NTP server web UI

set -e

INSTALL_DIR="/opt/satntp"
SERVICE_USER="satntp"

echo "=== SatNTP Installer ==="
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./install.sh)"
    exit 1
fi

# Install system dependencies
echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip gpsd gpsd-clients chrony pps-tools > /dev/null

# Create service user
echo "[2/7] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
fi

# Install application
echo "[3/7] Installing SatNTP to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"
cp -r satntp templates static config requirements.txt "$INSTALL_DIR/"

# Create virtualenv and install Python deps
echo "[4/7] Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# Set permissions
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Install gpsd config
echo "[5/7] Configuring gpsd..."
if [ -f /etc/default/gpsd ]; then
    cp /etc/default/gpsd /etc/default/gpsd.backup.$(date +%Y%m%d%H%M%S)
fi
cp "$INSTALL_DIR/config/gpsd.conf" /etc/default/gpsd

# Install chrony config
echo "[6/7] Configuring Chrony..."
CHRONY_CONF="/etc/chrony/chrony.conf"
if [ ! -f "$CHRONY_CONF" ]; then
    CHRONY_CONF="/etc/chrony.conf"
fi
if [ -f "$CHRONY_CONF" ]; then
    cp "$CHRONY_CONF" "${CHRONY_CONF}.backup.$(date +%Y%m%d%H%M%S)"
fi
cp "$INSTALL_DIR/config/chrony.conf" "$CHRONY_CONF"

# Install and enable systemd service
echo "[7/7] Installing systemd service..."
cp "$INSTALL_DIR/config/satntp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable satntp.service

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Start services:"
echo "  sudo systemctl restart gpsd"
echo "  sudo systemctl restart chronyd"
echo "  sudo systemctl start satntp"
echo ""
echo "Web UI: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
