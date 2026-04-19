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

from flask import Flask, jsonify, render_template, request

from satntp.anomaly_detector import AnomalyDetector, DetectorConfig
from satntp.chrony_monitor import ChronyMonitor
from satntp.gpsd_client import GPSDClient
from satntp.history import HistoryBuffer

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
chrony_monitor = ChronyMonitor(
    poll_interval=float(os.environ.get('CHRONY_POLL_INTERVAL', '10')),
)

# Integrity monitoring (optional, additive — disables cleanly via config).
history_buffer = HistoryBuffer(
    max_samples=int(os.environ.get('SATNTP_HISTORY_SIZE', '600')),
)
anomaly_config = DetectorConfig.from_env()
anomaly_detector = AnomalyDetector(history_buffer, anomaly_config)


def _latest_chrony_offset_s():
    """Return chrony's current system-time offset in seconds, if parseable."""
    try:
        status = chrony_monitor.get_status()
        raw = (status.get('tracking') or {}).get('last_offset') or ''
        return _parse_offset_seconds(raw)
    except Exception:
        return None


def _on_sample(_sample):
    if anomaly_config.enabled:
        try:
            anomaly_detector.evaluate()
        except Exception as e:
            logger.debug(f"anomaly evaluate error: {e}")


gpsd_client = GPSDClient(
    host=os.environ.get('GPSD_HOST', '127.0.0.1'),
    port=int(os.environ.get('GPSD_PORT', '2947')),
    history=history_buffer if anomaly_config.enabled else None,
    on_sample=_on_sample if anomaly_config.enabled else None,
    chrony_offset_cb=_latest_chrony_offset_s if anomaly_config.enabled else None,
)


def _parse_offset_seconds(raw: str):
    """Parse chrony offset strings like "+0.000420814 seconds" or "+877us"."""
    if not raw or not isinstance(raw, str):
        return None
    import re
    m = re.match(
        r'\s*([+-]?)(\d+(?:\.\d+)?)\s*(ns|us|µs|ms|s|seconds?)?',
        raw.strip(),
    )
    if not m:
        return None
    sign = -1.0 if m.group(1) == '-' else 1.0
    try:
        magnitude = float(m.group(2))
    except ValueError:
        return None
    unit = (m.group(3) or 's').lower()
    scale = {
        'ns': 1e-9,
        'us': 1e-6, 'µs': 1e-6,
        'ms': 1e-3,
        's': 1.0, 'second': 1.0, 'seconds': 1.0,
    }.get(unit, 1.0)
    return sign * magnitude * scale


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

    payload = {
        'gps': gps_state,
        'chrony': chrony_status,
        'gpsd': {
            'connected': gpsd_client.connected,
            'version': gpsd_client.gpsd_version,
            'devices': gpsd_client.devices,
        },
    }
    if anomaly_config.enabled:
        payload['anomaly_summary'] = anomaly_detector.summary()
    return jsonify(payload)


@app.route('/api/anomalies')
def api_anomalies():
    """Current and recent anomaly events. Empty payload if disabled."""
    if not anomaly_config.enabled:
        return jsonify({
            'enabled': False,
            'active': [],
            'recent': [],
            'summary': {'active_count': 0, 'worst_severity': None, 'enabled': False},
        })
    try:
        limit = max(1, min(int(request.args.get('limit', '50')), 500))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({
        'enabled': True,
        'active': [a.to_dict() for a in anomaly_detector.active()],
        'recent': [a.to_dict() for a in anomaly_detector.recent(limit=limit)],
        'summary': anomaly_detector.summary(),
    })


@app.route('/api/history')
def api_history():
    """Rolling history buffer used by the integrity UI. Empty if disabled."""
    if not anomaly_config.enabled:
        return jsonify({'enabled': False, 'samples': []})
    try:
        window = int(request.args.get('window', '600'))
    except (TypeError, ValueError):
        window = 600
    window = max(1, min(window, history_buffer.max_samples))
    samples = history_buffer.snapshot(window=window)
    return jsonify({
        'enabled': True,
        'samples': [s.to_dict() for s in samples],
        'size': len(samples),
        'max_samples': history_buffer.max_samples,
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
    port = int(os.environ.get('SATNTP_PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
