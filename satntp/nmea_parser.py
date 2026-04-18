"""
NMEA sentence parser for GPS-disciplined NTP server.

Handles real-world NMEA data including:
- GPRMC: Position, velocity, time, fix validity
- GPGSA: DOP values and satellite fix mode
- GPGSV: Satellites in view with signal strength

Designed against actual u-blox 7/M9N output with mixed constellations
(GPS, SBAS, QZSS) and NO FIX conditions.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Satellite:
    """A single satellite observation."""
    prn: int
    elevation: float  # degrees, can be negative (below horizon)
    azimuth: float    # degrees
    snr: float        # dB-Hz, 0 means not tracked
    constellation: str = "GP"  # GP, GL, GA, GB, GQ, SB, etc.
    used: bool = False

    @property
    def tracked(self) -> bool:
        return self.snr > 0

    @property
    def display_id(self) -> str:
        return f"{self.constellation}{self.prn}"


@dataclass
class GPSFix:
    """Current GPS fix state."""
    mode: int = 1           # 1=no fix, 2=2D, 3=3D
    valid: bool = False     # from GPRMC status field
    utc_time: Optional[str] = None  # HH:MM:SS.ss
    utc_date: Optional[str] = None  # YYYY-MM-DD
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed_knots: Optional[float] = None
    course: Optional[float] = None
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    satellites_used: list = field(default_factory=list)  # PRNs of used sats
    timestamp: float = 0.0  # system time of last update

    @property
    def has_fix(self) -> bool:
        """A fix requires BOTH mode >= 2 AND GPRMC status 'A' (active)."""
        return self.mode >= 2 and self.valid

    @property
    def fix_description(self) -> str:
        if self.mode == 1 or not self.valid:
            return "NO FIX"
        elif self.mode == 2:
            return "2D FIX"
        elif self.mode == 3:
            return "3D FIX"
        return "UNKNOWN"

    @property
    def time_available(self) -> bool:
        """Time may be present in NMEA even without a fix."""
        return self.utc_time is not None


@dataclass
class GPSState:
    """Complete GPS receiver state."""
    fix: GPSFix = field(default_factory=GPSFix)
    satellites: dict = field(default_factory=dict)  # keyed by (constellation, prn)
    last_update: float = 0.0
    sentences_parsed: int = 0
    parse_errors: int = 0

    @property
    def satellites_visible(self) -> int:
        return len(self.satellites)

    @property
    def satellites_used_count(self) -> int:
        return sum(1 for s in self.satellites.values() if s.used)

    @property
    def satellites_tracked(self) -> int:
        return sum(1 for s in self.satellites.values() if s.tracked)

    def get_satellite_list(self) -> list:
        """Return satellites sorted by constellation then PRN."""
        return sorted(self.satellites.values(),
                      key=lambda s: (s.constellation, s.prn))


def verify_checksum(sentence: str) -> bool:
    """Verify NMEA checksum. Returns True if valid or no checksum present."""
    if '*' not in sentence:
        return True
    try:
        body, checksum_str = sentence.rsplit('*', 1)
        # Remove leading $ if present
        if body.startswith('$'):
            body = body[1:]
        expected = int(checksum_str[:2], 16)
        computed = 0
        for ch in body:
            computed ^= ord(ch)
        return computed == expected
    except (ValueError, IndexError):
        return False


def _parse_float(value: str) -> Optional[float]:
    """Safely parse a float, returning None for empty or invalid."""
    if not value or value.strip() == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str) -> Optional[int]:
    """Safely parse an int, returning None for empty or invalid."""
    if not value or value.strip() == '':
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _nmea_to_decimal(coord: str, direction: str) -> Optional[float]:
    """Convert NMEA coordinate (DDDMM.MMMM) to decimal degrees."""
    if not coord or not direction:
        return None
    try:
        # Find the decimal point, degrees are everything before last 2 digits of integer part
        dot_pos = coord.index('.')
        deg_len = dot_pos - 2
        if deg_len < 1:
            return None
        degrees = int(coord[:deg_len])
        minutes = float(coord[deg_len:])
        result = degrees + minutes / 60.0
        if direction in ('S', 'W'):
            result = -result
        return result
    except (ValueError, IndexError):
        return None


def _talker_to_constellation(talker: str) -> str:
    """Map NMEA talker ID to constellation abbreviation.

    From real data we see:
    - GP = GPS
    - GL = GLONASS
    - GA = Galileo
    - GB/BD = BeiDou
    - GQ/QZ = QZSS
    - GI = NavIC (IRNSS)
    - GN = multi-GNSS combined
    """
    mapping = {
        'GP': 'GP',
        'GL': 'GL',
        'GA': 'GA',
        'GB': 'GB',
        'BD': 'GB',
        'GQ': 'QZ',
        'QZ': 'QZ',
        'GI': 'GI',
        'GN': 'GN',
    }
    return mapping.get(talker, talker)


def _prn_to_constellation(prn: int, talker: str) -> tuple:
    """Determine constellation and normalize PRN from GSV data.

    U-blox GNSS receivers report satellites using these NMEA PRN ranges
    in GPGSV sentences (mixed constellations):
    - 1-32: GPS
    - 33-64: SBAS (add 87 for actual PRN: 120-151)
    - 65-96: GLONASS (subtract 64 for slot number 1-32)
    - 120-158: SBAS (WAAS/EGNOS/MSAS direct numbering)
    - 193-199: QZSS (subtract 192 for SVID 1-7)
    - 201-264: BeiDou (subtract 200 for SVID 1-64)
    - 301-336: Galileo (subtract 300 for SVID 1-36)
    - 401-437: NavIC / IRNSS (subtract 400 for SVID 1-37)

    System-specific talkers (GA, GL, GB, GQ, GI) typically use direct SVIDs
    but some receivers may use the offset PRN numbers above.
    """
    constellation = _talker_to_constellation(talker)

    if talker == 'GP':
        if 1 <= prn <= 32:
            return ('GP', prn)
        elif 33 <= prn <= 64:
            # SBAS reported with offset in some receivers
            return ('SB', prn + 87)
        elif 65 <= prn <= 96:
            # GLONASS reported in GPGSV
            return ('GL', prn - 64)
        elif 120 <= prn <= 158:
            # SBAS direct numbering
            return ('SB', prn)
        elif 193 <= prn <= 199:
            # QZSS
            return ('QZ', prn - 192)
        elif 201 <= prn <= 264:
            # BeiDou
            return ('GB', prn - 200)
        elif 301 <= prn <= 336:
            # Galileo
            return ('GA', prn - 300)
        elif 401 <= prn <= 437:
            # NavIC / IRNSS
            return ('GI', prn - 400)
        elif prn > 100:
            # Other high PRNs from GP talker - unknown system
            return ('??', prn)
    elif talker == 'GL':
        # GLONASS: PRN 65-96 maps to slot 1-32
        if prn >= 65:
            return ('GL', prn - 64)
        return ('GL', prn)
    elif talker == 'GA':
        # Galileo: PRN 301-336 maps to SVID 1-36
        if prn >= 301:
            return ('GA', prn - 300)
        return ('GA', prn)
    elif talker in ('GB', 'BD'):
        # BeiDou: PRN 201-264 maps to SVID 1-64
        if prn >= 201:
            return ('GB', prn - 200)
        return ('GB', prn)
    elif talker in ('GQ', 'QZ'):
        # QZSS: PRN 193-199 maps to SVID 1-7
        if prn >= 193:
            return ('QZ', prn - 192)
        return ('QZ', prn)
    elif talker == 'GI':
        # NavIC/IRNSS: PRN 401-437 maps to SVID 1-37
        if prn >= 401:
            return ('GI', prn - 400)
        return ('GI', prn)

    return (constellation, prn)


class NMEAParser:
    """Stateful NMEA parser that builds up GPS state from sentence stream."""

    def __init__(self):
        self.state = GPSState()
        self._gsv_buffer = {}  # talker -> {msg_num: [satellites]}
        self._gsv_total = {}   # talker -> total messages expected
        self._used_prns = set()

    def parse_sentence(self, raw: str) -> bool:
        """Parse a single NMEA sentence. Returns True if parsed successfully."""
        raw = raw.strip()
        if not raw or not raw.startswith('$'):
            return False

        if not verify_checksum(raw):
            self.state.parse_errors += 1
            return False

        # Strip checksum for field parsing
        if '*' in raw:
            raw = raw[:raw.rindex('*')]

        # Remove leading $
        raw = raw[1:]
        fields = raw.split(',')

        if len(fields) < 1:
            return False

        sentence_id = fields[0]
        # Extract talker (first 2 chars) and sentence type (remaining)
        if len(sentence_id) < 4:
            return False

        talker = sentence_id[:2]
        sentence_type = sentence_id[2:]

        try:
            if sentence_type == 'RMC':
                self._parse_rmc(fields)
            elif sentence_type == 'GSA':
                self._parse_gsa(fields)
            elif sentence_type == 'GSV':
                self._parse_gsv(fields, talker)
            else:
                return False  # Not a sentence we handle

            self.state.sentences_parsed += 1
            self.state.last_update = time.time()
            return True
        except Exception:
            self.state.parse_errors += 1
            return False

    def _parse_rmc(self, fields: list):
        """Parse RMC - Recommended Minimum Navigation Information.

        From real data:
        $GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*73

        Fields: talker+RMC, time, status, lat, N/S, lon, E/W, speed, course,
                date, mag_var, mag_var_dir [, mode_indicator]

        Key observation: status='V' means data NOT valid (void).
        Time and position are still present but MUST NOT be trusted for navigation.
        """
        fix = self.state.fix

        # Field 1: UTC time (HHMMSS.ss)
        utc_raw = fields[1] if len(fields) > 1 else ''
        if utc_raw and len(utc_raw) >= 6:
            hh = utc_raw[0:2]
            mm = utc_raw[2:4]
            ss = utc_raw[4:]
            fix.utc_time = f"{hh}:{mm}:{ss}"

        # Field 2: Status - A=active/valid, V=void/invalid
        status = fields[2] if len(fields) > 2 else 'V'
        fix.valid = (status == 'A')

        # Fields 3-6: Position (present even when invalid!)
        if fix.valid:
            lat_raw = fields[3] if len(fields) > 3 else ''
            lat_dir = fields[4] if len(fields) > 4 else ''
            lon_raw = fields[5] if len(fields) > 5 else ''
            lon_dir = fields[6] if len(fields) > 6 else ''
            fix.latitude = _nmea_to_decimal(lat_raw, lat_dir)
            fix.longitude = _nmea_to_decimal(lon_raw, lon_dir)
        else:
            fix.latitude = None
            fix.longitude = None

        # Field 7: Speed over ground in knots
        fix.speed_knots = _parse_float(fields[7]) if len(fields) > 7 else None

        # Field 8: Course over ground
        fix.course = _parse_float(fields[8]) if len(fields) > 8 else None

        # Field 9: Date (DDMMYY)
        date_raw = fields[9] if len(fields) > 9 else ''
        if date_raw and len(date_raw) == 6:
            dd = date_raw[0:2]
            mo = date_raw[2:4]
            yy = date_raw[4:6]
            # Y2K handling: assume 20xx for yy < 80, 19xx otherwise
            century = '20' if int(yy) < 80 else '19'
            fix.utc_date = f"{century}{yy}-{mo}-{dd}"

        fix.timestamp = time.time()

    def _parse_gsa(self, fields: list):
        """Parse GSA - GPS DOP and Active Satellites.

        From real data:
        $GPGSA,A,1,,,,,,,,,,,,,,,,*32

        Fields: talker+GSA, sel_mode, fix_mode, sv1..sv12, PDOP, HDOP, VDOP
        Note: Real data shows 15 empty SV fields (not standard 12) - u-blox extension.

        fix_mode: 1=no fix, 2=2D, 3=3D
        """
        fix = self.state.fix

        # Field 2: Fix mode (1=no fix, 2=2D, 3=3D)
        mode = _parse_int(fields[2]) if len(fields) > 2 else None
        if mode is not None:
            fix.mode = mode

        # SV fields: variable number, find PRNs of used satellites
        # Standard is fields[3:15], but u-blox may have more
        # DOP values are always the last 3 fields before checksum
        self._used_prns.clear()
        fix.satellites_used = []

        # Parse satellite PRNs - everything between field 3 and the last 3 fields
        # which are PDOP, HDOP, VDOP
        if len(fields) > 5:
            # Last 3 data fields are DOPs
            sv_end = len(fields) - 3
            for i in range(3, sv_end):
                prn = _parse_int(fields[i])
                if prn is not None and prn > 0:
                    self._used_prns.add(prn)
                    fix.satellites_used.append(prn)

            # DOP values
            fix.pdop = _parse_float(fields[-3]) if fields[-3] else None
            fix.hdop = _parse_float(fields[-2]) if fields[-2] else None
            fix.vdop = _parse_float(fields[-1]) if fields[-1] else None

        # Update used status on all satellites
        for key, sat in self.state.satellites.items():
            sat.used = sat.prn in self._used_prns

    def _parse_gsv(self, fields: list, talker: str):
        """Parse GSV - Satellites in View.

        From real data:
        $GPGSV,6,1,22,01,01,229,21,02,28,224,20,08,35,264,21,09,-55,316,23*56

        Fields: talker+GSV, total_msgs, msg_num, total_sats,
                [prn, elev, azim, snr] * 1-4 per message

        Key observations from real data:
        - Negative elevations (e.g., -55, -37) indicating satellites below horizon
        - SNR of 00 meaning not tracked
        - PRNs > 32 in GPGSV: 42,48,50 are SBAS; 194,195,196 are QZSS
        - 6 messages needed for 22 satellites
        """
        if len(fields) < 4:
            return

        total_msgs = _parse_int(fields[1])
        msg_num = _parse_int(fields[2])
        total_sats = _parse_int(fields[3])

        if total_msgs is None or msg_num is None:
            return

        # Initialize buffer for this talker if new sequence
        if msg_num == 1:
            self._gsv_buffer[talker] = {}
            self._gsv_total[talker] = total_msgs

        if talker not in self._gsv_buffer:
            self._gsv_buffer[talker] = {}
            self._gsv_total[talker] = total_msgs

        # Parse satellite groups (4 fields each, starting at field 4)
        sats_in_msg = []
        idx = 4
        while idx + 3 < len(fields):
            prn_raw = _parse_int(fields[idx])
            elev = _parse_float(fields[idx + 1])
            azim = _parse_float(fields[idx + 2])
            snr = _parse_float(fields[idx + 3])

            if prn_raw is not None:
                constellation, normalized_prn = _prn_to_constellation(prn_raw, talker)
                sat = Satellite(
                    prn=normalized_prn,
                    elevation=elev if elev is not None else 0.0,
                    azimuth=azim if azim is not None else 0.0,
                    snr=snr if snr is not None else 0.0,
                    constellation=constellation,
                    used=(prn_raw in self._used_prns),
                )
                sats_in_msg.append(((constellation, normalized_prn), sat))

            idx += 4

        # Also handle case where last group has fewer than 4 fields
        # (the last satellite in the last message may have trailing empty fields)
        if idx < len(fields) and idx + 2 < len(fields):
            prn_raw = _parse_int(fields[idx])
            elev = _parse_float(fields[idx + 1]) if idx + 1 < len(fields) else None
            azim = _parse_float(fields[idx + 2]) if idx + 2 < len(fields) else None
            snr = _parse_float(fields[idx + 3]) if idx + 3 < len(fields) else None

            if prn_raw is not None:
                constellation, normalized_prn = _prn_to_constellation(prn_raw, talker)
                sat = Satellite(
                    prn=normalized_prn,
                    elevation=elev if elev is not None else 0.0,
                    azimuth=azim if azim is not None else 0.0,
                    snr=snr if snr is not None else 0.0,
                    constellation=constellation,
                    used=(prn_raw in self._used_prns),
                )
                sats_in_msg.append(((constellation, normalized_prn), sat))

        self._gsv_buffer[talker][msg_num] = sats_in_msg

        # When we have all messages for this talker, update state
        if len(self._gsv_buffer[talker]) >= self._gsv_total.get(talker, 0):
            # Remove old satellites from this talker
            keys_to_remove = [
                k for k in self.state.satellites
                if k[0] == _talker_to_constellation(talker)
                or (talker == 'GP' and k[0] in ('GP', 'SB', 'QZ', 'GL', 'GA', 'GB', 'GI', '??'))
            ]
            for k in keys_to_remove:
                del self.state.satellites[k]

            # Add new satellites
            for msg_sats in self._gsv_buffer[talker].values():
                for key, sat in msg_sats:
                    self.state.satellites[key] = sat

            # Clean up buffer
            del self._gsv_buffer[talker]
            if talker in self._gsv_total:
                del self._gsv_total[talker]

    def parse_stream(self, data: str):
        """Parse multiple NMEA sentences from a data stream."""
        for line in data.split('\n'):
            line = line.strip()
            if line.startswith('$'):
                self.parse_sentence(line)

    def get_state_dict(self) -> dict:
        """Return full state as a JSON-serializable dictionary."""
        fix = self.state.fix
        sats = self.state.get_satellite_list()

        return {
            'fix': {
                'mode': fix.mode,
                'valid': fix.valid,
                'has_fix': fix.has_fix,
                'description': fix.fix_description,
                'utc_time': fix.utc_time,
                'utc_date': fix.utc_date,
                'time_available': fix.time_available,
                'latitude': fix.latitude,
                'longitude': fix.longitude,
                'speed_knots': fix.speed_knots,
                'course': fix.course,
                'pdop': fix.pdop,
                'hdop': fix.hdop,
                'vdop': fix.vdop,
                'satellites_used': fix.satellites_used,
            },
            'satellites': [
                {
                    'prn': s.prn,
                    'constellation': s.constellation,
                    'display_id': s.display_id,
                    'elevation': s.elevation,
                    'azimuth': s.azimuth,
                    'snr': s.snr,
                    'tracked': s.tracked,
                    'used': s.used,
                }
                for s in sats
            ],
            'summary': {
                'visible': self.state.satellites_visible,
                'tracked': self.state.satellites_tracked,
                'used': self.state.satellites_used_count,
            },
            'meta': {
                'sentences_parsed': self.state.sentences_parsed,
                'parse_errors': self.state.parse_errors,
                'last_update': self.state.last_update,
            },
        }
