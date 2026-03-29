"""
Flask application for the GPS-disciplined NTP server web UI.

Provides:
- Web dashboard at /
- REST API at /api/status for real-time GPS and Chrony data
- /api/gps for GPS-only state
- /api/chrony for Chrony-only state
"""

import json
import logging
import os
import subprocess

from flask import Flask, jsonify, render_template

from satntp.gpsd_client import GPSDClient
from satntp.chrony_monitor import ChronyMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Resolve paths relative to this file's parent directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
)

# Initialize services
gpsd_client = GPSDClient(
    host=os.environ.get('GPSD_HOST', '127.0.0.1'),
    port=int(os.environ.get('GPSD_PORT', '2947')),
)
chrony_monitor = ChronyMonitor(
    poll_interval=float(os.environ.get('CHRONY_POLL_INTERVAL', '10')),
)


@app.before_request
def ensure_services_started():
    """Start background services on first request."""
    if not gpsd_client.connected and not getattr(app, '_services_started', False):
        app._services_started = True
        gpsd_client.start()
        chrony_monitor.start()


@app.route('/')
def dashboard():
    """Serve the main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    """Combined GPS + Chrony status endpoint."""
    gps_state = gpsd_client.get_state()
    chrony_status = chrony_monitor.get_status()

    return jsonify({
        'gps': gps_state,
        'chrony': chrony_status,
        'gpsd': {
            'connected': gpsd_client.connected,
            'version': gpsd_client.gpsd_version,
            'devices': gpsd_client.devices,
        },
    })


@app.route('/api/gps')
def api_gps():
    """GPS-only status endpoint."""
    return jsonify(gpsd_client.get_state())


@app.route('/api/chrony')
def api_chrony():
    """Chrony-only status endpoint."""
    return jsonify(chrony_monitor.get_status())


@app.route('/api/gpsd')
def api_gpsd():
    """gpsd daemon info endpoint."""
    return jsonify({
        'connected': gpsd_client.connected,
        'version': gpsd_client.gpsd_version,
        'devices': gpsd_client.devices,
    })


@app.route('/api/system')
def api_system():
    """System information endpoint."""
    info = {
        'hostname': _safe_cmd(['hostname']),
        'uptime': _safe_cmd(['uptime', '-p']),
        'gpsd_active': _service_active('gpsd'),
        'chronyd_active': _service_active('chronyd') or _service_active('chrony'),
    }
    return jsonify(info)


def _safe_cmd(cmd: list) -> str:
    """Run a command safely, returning output or empty string."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return ''


def _service_active(name: str) -> bool:
    """Check if a systemd service is active."""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', name],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == 'active'
    except Exception:
        return False


def create_app():
    """Application factory."""
    return app


if __name__ == '__main__':
    gpsd_client.start()
    chrony_monitor.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
