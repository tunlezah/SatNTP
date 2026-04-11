#!/bin/bash
# SatNTP Uninstaller
# Removes the SatNTP service, configuration, and install directory.
# Leaves installed system packages (gpsd, chrony, python3, etc.) in place.

set -e

INSTALL_DIR="/opt/satntp"
SERVICE_USER="satntp"

echo "=== SatNTP Uninstaller ==="
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./uninstall.sh)"
    exit 1
fi

# ── 1. Stop and disable the systemd service ──
echo "[1/5] Stopping and removing systemd service..."
if systemctl is-active --quiet satntp.service 2>/dev/null; then
    systemctl stop satntp.service
    echo "  Stopped satntp.service"
fi
if systemctl is-enabled --quiet satntp.service 2>/dev/null; then
    systemctl disable satntp.service
    echo "  Disabled satntp.service"
fi
if [ -f /etc/systemd/system/satntp.service ]; then
    rm /etc/systemd/system/satntp.service
    systemctl daemon-reload
    echo "  Removed service file"
fi

# ── 2. Restore gpsd configuration ──
echo "[2/5] Restoring gpsd configuration..."
GPSD_BACKUP=$(ls -t /etc/default/gpsd.backup.* 2>/dev/null | head -1)
if [ -n "$GPSD_BACKUP" ]; then
    cp "$GPSD_BACKUP" /etc/default/gpsd
    rm -f /etc/default/gpsd.backup.*
    echo "  Restored from $GPSD_BACKUP"
else
    echo "  No backup found, leaving /etc/default/gpsd as-is"
fi

# ── 3. Restore chrony configuration ──
echo "[3/5] Restoring Chrony configuration..."
CHRONY_CONF="/etc/chrony/chrony.conf"
if [ ! -f "$CHRONY_CONF" ]; then
    CHRONY_CONF="/etc/chrony.conf"
fi
CHRONY_BACKUP=$(ls -t "${CHRONY_CONF}.backup."* 2>/dev/null | head -1)
if [ -n "$CHRONY_BACKUP" ]; then
    cp "$CHRONY_BACKUP" "$CHRONY_CONF"
    rm -f "${CHRONY_CONF}.backup."*
    echo "  Restored from $CHRONY_BACKUP"
else
    echo "  No backup found, leaving $CHRONY_CONF as-is"
fi

# ── 4. Remove the install directory ──
echo "[4/5] Removing ${INSTALL_DIR}..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "  Removed $INSTALL_DIR"
else
    echo "  $INSTALL_DIR not found, skipping"
fi

# ── 5. Remove the service user ──
echo "[5/5] Removing service user..."
if id "$SERVICE_USER" &>/dev/null; then
    userdel "$SERVICE_USER" 2>/dev/null || true
    echo "  Removed user $SERVICE_USER"
else
    echo "  User $SERVICE_USER not found, skipping"
fi

echo ""
echo "=== Uninstall Complete ==="
echo ""
echo "The following were removed:"
echo "  - satntp systemd service"
echo "  - $INSTALL_DIR (application files)"
echo "  - $SERVICE_USER system user"
echo "  - SatNTP gpsd and chrony configs (originals restored from backup)"
echo ""
echo "Installed system packages (gpsd, chrony, python3, etc.) were left in place."
echo "You may want to restart gpsd and chrony to pick up restored configs:"
echo "  sudo systemctl restart gpsd"
echo "  sudo systemctl restart chronyd"
echo ""
