#!/bin/bash
# SatNTP Installation Script
# Installs the GPS-disciplined NTP server web UI

set -e

INSTALL_DIR="/opt/satntp"
SERVICE_USER="satntp"
DEFAULT_PORT=5000

# Chronyd's control socket (/run/chrony/chronyd.sock) is typically mode 0660,
# owned by the chrony group. On Debian/Ubuntu the group is `_chrony`; on
# RHEL/Fedora/Arch it's `chrony`. The service user must join this group
# otherwise `chronyc tracking` fails silently and the UI shows no sync data.
detect_chrony_group() {
    for g in _chrony chrony; do
        if getent group "$g" >/dev/null 2>&1; then
            echo "$g"
            return
        fi
    done
    echo ""
}

echo "=== SatNTP Installer ==="
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./install.sh)"
    exit 1
fi

# ── Auto-uninstall any previous install ──
# A prior install leaves behind the systemd unit, the install dir, the
# service user, and replaced gpsd/chrony configs. Re-running install on top
# of that state is error-prone (stale service file, drifted chrony config
# backups, etc.), so always invoke ./uninstall.sh first when we detect a
# previous install.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f /etc/systemd/system/satntp.service ] \
   || [ -d "$INSTALL_DIR" ] \
   || id "$SERVICE_USER" &>/dev/null; then
    if [ -x "$SCRIPT_DIR/uninstall.sh" ]; then
        echo "Previous SatNTP install detected — running uninstall.sh first..."
        echo ""
        "$SCRIPT_DIR/uninstall.sh"
        echo ""
        echo "Proceeding with fresh install..."
        echo ""
    else
        echo "WARNING: previous install detected but $SCRIPT_DIR/uninstall.sh"
        echo "         is missing or not executable. Continuing anyway."
        echo ""
    fi
fi

# ── Find available web server port ──
# NOTE: anything this function writes to stdout becomes its return value, so
# status/progress messages must go to stderr — otherwise the "trying next..."
# line gets captured into $SATNTP_PORT and corrupts downstream `sed`/`[ -ne ]`.
find_available_port() {
    local port=$1
    while ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port " || \
          ss -tlnH 2>/dev/null | grep -q ":$port "; do
        echo "  Port $port is in use, trying next..." >&2
        port=$((port + 1))
    done
    echo "$port"
}

SATNTP_PORT=$(find_available_port $DEFAULT_PORT)
if [ "$SATNTP_PORT" -ne "$DEFAULT_PORT" ]; then
    echo "Note: Default port $DEFAULT_PORT was in use."
    echo "      Using port $SATNTP_PORT instead."
    echo ""
fi

# Install system dependencies
echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip gpsd gpsd-clients chrony pps-tools > /dev/null

# Create service user
echo "[2/8] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
fi

# Add the service user to the chrony group so that `chronyc` can reach the
# chronyd control socket. Without this, the Chrony Synchronization panel on
# the dashboard stays empty.
CHRONY_GROUP=$(detect_chrony_group)
if [ -n "$CHRONY_GROUP" ]; then
    usermod -aG "$CHRONY_GROUP" "$SERVICE_USER"
    echo "  Added $SERVICE_USER to group $CHRONY_GROUP (for chronyc access)"
else
    echo "  WARNING: no chrony group found; chronyc may be unable to query chronyd"
fi

# Install application
echo "[3/8] Installing SatNTP to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"
cp -r satntp templates static config requirements.txt "$INSTALL_DIR/"

# Create virtualenv and install Python deps
echo "[4/8] Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# Set permissions
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Install gpsd config
echo "[5/8] Configuring gpsd..."
if [ -f /etc/default/gpsd ]; then
    cp /etc/default/gpsd "/etc/default/gpsd.backup.$(date +%Y%m%d%H%M%S)"
fi
cp "$INSTALL_DIR/config/gpsd.conf" /etc/default/gpsd

# Install chrony config
echo "[6/8] Configuring Chrony..."
CHRONY_CONF="/etc/chrony/chrony.conf"
if [ ! -f "$CHRONY_CONF" ]; then
    CHRONY_CONF="/etc/chrony.conf"
fi
if [ -f "$CHRONY_CONF" ]; then
    cp "$CHRONY_CONF" "${CHRONY_CONF}.backup.$(date +%Y%m%d%H%M%S)"
fi
cp "$INSTALL_DIR/config/chrony.conf" "$CHRONY_CONF"

# Install and enable systemd service with the selected port
echo "[7/8] Installing systemd service..."
sed "s/Environment=SATNTP_PORT=5000/Environment=SATNTP_PORT=${SATNTP_PORT}/" \
    "$INSTALL_DIR/config/satntp.service" > /etc/systemd/system/satntp.service
systemctl daemon-reload
systemctl enable satntp.service

# Start/restart everything so the stack is live at the end of install.
# gpsd and chronyd must be restarted to pick up the new configs; satntp
# needs to start after them so its first chronyc query sees a running daemon.
echo "[8/8] Starting services..."

# chronyd: service unit is `chronyd` on RHEL/Fedora/Arch, `chrony` on Debian/Ubuntu.
CHRONY_UNIT=""
for unit in chronyd chrony; do
    if systemctl list-unit-files "${unit}.service" 2>/dev/null | grep -q "^${unit}.service"; then
        CHRONY_UNIT="$unit"
        break
    fi
done

# gpsd uses a socket-activated unit on Debian/Ubuntu; restart the socket too
# if present so the fresh /etc/default/gpsd is picked up.
if systemctl list-unit-files gpsd.socket 2>/dev/null | grep -q '^gpsd.socket'; then
    systemctl enable gpsd.socket >/dev/null 2>&1 || true
    systemctl restart gpsd.socket || true
fi
systemctl enable gpsd.service >/dev/null 2>&1 || true
systemctl restart gpsd.service || echo "  WARNING: failed to start gpsd.service"

if [ -n "$CHRONY_UNIT" ]; then
    systemctl enable "${CHRONY_UNIT}.service" >/dev/null 2>&1 || true
    systemctl restart "${CHRONY_UNIT}.service" || echo "  WARNING: failed to start ${CHRONY_UNIT}.service"
else
    echo "  WARNING: no chrony/chronyd systemd unit found"
fi

# Give chronyd a moment to open its control socket before satntp connects.
sleep 1
systemctl restart satntp.service || echo "  WARNING: failed to start satntp.service"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Service status:"
for svc in gpsd "${CHRONY_UNIT:-chronyd}" satntp; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "  $svc: active"
    else
        echo "  $svc: NOT active (check: systemctl status $svc)"
    fi
done
echo ""
echo "Web UI: http://$(hostname -I | awk '{print $1}'):${SATNTP_PORT}"
echo ""
