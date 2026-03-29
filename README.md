# SatNTP - GPS-Disciplined NTP Server

A production-grade GPS-disciplined NTP server with real-time web dashboard.

## Features

- **NMEA Parser**: Handles GPRMC, GPGSA, GPGSV sentences with fault tolerance
- **Mixed GNSS**: GPS, SBAS, QZSS constellation support
- **Real-world tolerant**: Handles negative elevations, NO FIX conditions, zero SNR
- **Chrony Integration**: GPS + PPS refclock configuration with NTP pool fallback
- **Web Dashboard**: Modern dark-themed UI with sky view, signal bars, satellite table
- **gpsd Integration**: Connects via gpspipe (NMEA) or gps3 (JSON) fallback

## Quick Start

```bash
# Install
sudo ./install.sh

# Or run directly for development
pip install -r requirements.txt
python -m satntp.app
```

Web UI: http://localhost:5000

## Architecture

```
satntp/
  nmea_parser.py    - NMEA sentence parser (GPRMC, GPGSA, GPGSV)
  gpsd_client.py    - gpsd connection via gpspipe/gps3
  chrony_monitor.py - Chrony status via chronyc
  app.py            - Flask web server + REST API
config/
  chrony.conf       - Chrony config for GPS+PPS refclocks
  gpsd.conf         - gpsd default config
  satntp.service    - systemd unit file
templates/
  dashboard.html    - Web UI template
static/
  css/dashboard.css - Dark theme styles
  js/skyview.js     - Polar sky plot
  js/signal.js      - SNR bar chart
  js/dashboard.js   - Dashboard controller
tests/
  test_nmea_parser.py - 66 tests against real GPS data
```

## API Endpoints

- `GET /api/status` - Combined GPS + Chrony status
- `GET /api/gps` - GPS state only
- `GET /api/chrony` - Chrony tracking + sources
- `GET /api/gpsd` - gpsd daemon info
- `GET /api/system` - System info

## Testing

```bash
python -m pytest tests/ -v
```
