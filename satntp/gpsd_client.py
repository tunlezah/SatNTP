"""
gpsd client that connects to the gpsd daemon and streams GPS data.

Uses the gps3 library to connect to gpsd's JSON interface, then feeds
the underlying NMEA data through our parser for consistent handling.

Also supports direct NMEA parsing from gpspipe for environments where
the JSON interface may not expose all satellite details.
"""

import json
import logging
import subprocess
import threading
import time
from typing import Optional

from satntp.nmea_parser import NMEAParser

logger = logging.getLogger(__name__)


class GPSDClient:
    """Client that connects to gpsd and maintains current GPS state."""

    def __init__(self, host: str = '127.0.0.1', port: int = 2947):
        self.host = host
        self.port = port
        self.parser = NMEAParser()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._connected = False
        self._gpsd_version: Optional[str] = None
        self._devices: list = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def gpsd_version(self) -> Optional[str]:
        return self._gpsd_version

    @property
    def devices(self) -> list:
        return list(self._devices)

    def get_state(self) -> dict:
        """Get current GPS state as a dictionary (thread-safe)."""
        with self._lock:
            return self.parser.get_state_dict()

    def start(self):
        """Start the background GPS data collection thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("GPSDClient started")

    def stop(self):
        """Stop the background thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("GPSDClient stopped")

    def _run(self):
        """Main loop: connect to gpsd via gpspipe and parse NMEA."""
        while not self._stop_event.is_set():
            try:
                self._stream_nmea()
            except Exception as e:
                logger.error(f"gpspipe error: {e}")
            self._connected = False
            # Always wait before reconnecting to prevent a tight retry loop
            if self._stop_event.wait(5):
                break

    def _stream_nmea(self):
        """Stream NMEA data from gpspipe subprocess."""
        logger.info(f"Starting gpspipe connection to {self.host}:{self.port}")
        cmd = ['gpspipe', '--nmea', self.host + ':' + str(self.port)]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            logger.warning("gpspipe not found, falling back to gps3 JSON mode")
            self._stream_json()
            return

        self._connected = True
        logger.info("gpspipe connected, streaming NMEA")

        try:
            while not self._stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    break

                line = line.strip()

                # gpspipe also outputs JSON lines (VERSION, DEVICES, etc.)
                if line.startswith('{'):
                    self._handle_json_line(line)
                elif line.startswith('$'):
                    with self._lock:
                        self.parser.parse_sentence(line)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._connected = False

    def _stream_json(self):
        """Fallback: stream JSON data from gpsd using gps3."""
        try:
            from gps3 import gps3
        except ImportError:
            logger.error("gps3 not available and gpspipe not found")
            self._stop_event.wait(30)
            return

        gps_socket = gps3.GPSDSocket()
        data_stream = gps3.DataStream()

        try:
            gps_socket.connect(host=self.host, port=self.port)
            gps_socket.watch()
            self._connected = True
            logger.info("gps3 JSON connection established")

            for new_data in gps_socket:
                if self._stop_event.is_set():
                    break
                if new_data:
                    data_stream.unpack(new_data)
                    self._process_json_data(data_stream)
        except Exception as e:
            logger.error(f"gps3 connection error: {e}")
        finally:
            gps_socket.close()
            self._connected = False

    def _handle_json_line(self, line: str):
        """Handle JSON output from gpspipe (VERSION, DEVICES, etc.)."""
        try:
            data = json.loads(line)
            cls = data.get('class', '')

            if cls == 'VERSION':
                self._gpsd_version = data.get('release')
                logger.info(f"gpsd version: {self._gpsd_version}")
            elif cls == 'DEVICES':
                self._devices = data.get('devices', [])
                logger.info(f"Devices: {[d.get('path') for d in self._devices]}")
        except json.JSONDecodeError:
            pass

    def _process_json_data(self, data_stream):
        """Process JSON data from gps3 DataStream.

        This is a fallback that synthesizes NMEA-equivalent state from
        gpsd's JSON output.
        """
        with self._lock:
            fix = self.parser.state.fix

            # TPV class - time/position/velocity
            tpv = data_stream.TPV
            if isinstance(tpv, dict):
                mode = tpv.get('mode')
                if isinstance(mode, int):
                    fix.mode = mode

                time_str = tpv.get('time')
                if isinstance(time_str, str) and 'T' in time_str:
                    # ISO format: 2026-03-28T21:34:10.000Z
                    parts = time_str.split('T')
                    fix.utc_date = parts[0]
                    fix.utc_time = parts[1].rstrip('Z')

                fix.valid = (mode is not None and mode >= 2)
                if fix.valid:
                    fix.latitude = tpv.get('lat') if isinstance(tpv.get('lat'), (int, float)) else None
                    fix.longitude = tpv.get('lon') if isinstance(tpv.get('lon'), (int, float)) else None
                else:
                    fix.latitude = None
                    fix.longitude = None

                fix.timestamp = time.time()

            # SKY class - satellite data
            sky = data_stream.SKY
            if isinstance(sky, dict):
                sats = sky.get('satellites', [])
                if isinstance(sats, list):
                    self.parser.state.satellites.clear()
                    for s in sats:
                        if not isinstance(s, dict):
                            continue
                        prn = s.get('PRN')
                        if prn is None:
                            continue
                        # Determine constellation from GNSS ID or PRN range
                        gnss_id = s.get('gnssid', 0)
                        constellation_map = {
                            0: 'GP', 1: 'SB', 2: 'GA',
                            3: 'GB', 5: 'QZ', 6: 'GL',
                        }
                        const = constellation_map.get(gnss_id, 'GP')
                        from satntp.nmea_parser import Satellite
                        sat = Satellite(
                            prn=prn,
                            elevation=s.get('el', 0.0) or 0.0,
                            azimuth=s.get('az', 0.0) or 0.0,
                            snr=s.get('ss', 0.0) or 0.0,
                            constellation=const,
                            used=bool(s.get('used', False)),
                        )
                        self.parser.state.satellites[(const, prn)] = sat

            self.parser.state.last_update = time.time()
            self.parser.state.sentences_parsed += 1
