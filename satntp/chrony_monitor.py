"""
Chrony status monitor.

Parses output from chronyc commands to extract NTP synchronization status.
Designed against real chronyc output from the target system.
"""

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ChronySource:
    """A single Chrony time source."""
    mode: str = ''          # ^ (server), = (peer), # (local/refclock)
    state: str = ''         # * (selected), + (combined), - (not combined),
                            # x (error), ~ (too variable), ? (unusable)
    name: str = ''
    stratum: int = 0
    poll: int = 0
    reach: int = 0          # octal reachability register
    last_rx: str = ''       # last receive time
    offset: str = ''        # adjusted offset
    measured_offset: str = ''
    error: str = ''         # estimated error

    @property
    def is_selected(self) -> bool:
        return self.state == '*'

    @property
    def is_reachable(self) -> bool:
        return self.reach > 0

    @property
    def source_type(self) -> str:
        types = {'^': 'server', '=': 'peer', '#': 'refclock'}
        return types.get(self.mode, 'unknown')

    @property
    def state_description(self) -> str:
        states = {
            '*': 'selected',
            '+': 'combined',
            '-': 'not combined',
            'x': 'may be in error',
            '~': 'too variable',
            '?': 'unusable',
        }
        return states.get(self.state, 'unknown')


@dataclass
class ChronyTracking:
    """Chrony tracking (synchronization) status."""
    reference_id: str = ''
    reference_name: str = ''
    stratum: int = 0
    ref_time: str = ''
    system_time_offset: str = ''
    last_offset: str = ''
    rms_offset: str = ''
    frequency: str = ''
    residual_freq: str = ''
    skew: str = ''
    root_delay: str = ''
    root_dispersion: str = ''
    update_interval: str = ''
    leap_status: str = ''

    @property
    def is_synchronized(self) -> bool:
        return self.stratum > 0 and self.leap_status == 'Normal'


@dataclass
class ChronyStatus:
    """Complete Chrony status."""
    tracking: ChronyTracking = field(default_factory=ChronyTracking)
    sources: list = field(default_factory=list)
    last_update: float = 0.0
    error: Optional[str] = None


class ChronyMonitor:
    """Monitors Chrony status by periodically running chronyc."""

    def __init__(self, poll_interval: float = 10.0):
        self.poll_interval = poll_interval
        self._status = ChronyStatus()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def get_status(self) -> dict:
        """Get current Chrony status as a dictionary (thread-safe)."""
        with self._lock:
            return self._status_to_dict()

    def start(self):
        """Start background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("ChronyMonitor started")

    def stop(self):
        """Stop background polling."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        """Periodically poll chronyc for status."""
        while not self._stop_event.is_set():
            try:
                self._update_status()
            except Exception as e:
                logger.error(f"Chrony poll error: {e}")
                with self._lock:
                    self._status.error = str(e)

            self._stop_event.wait(self.poll_interval)

    def _update_status(self):
        """Run chronyc commands and parse output."""
        tracking = self._run_chronyc_tracking()
        sources = self._run_chronyc_sources()

        with self._lock:
            self._status.tracking = tracking
            self._status.sources = sources
            self._status.last_update = time.time()
            self._status.error = None

    def _run_chronyc_tracking(self) -> ChronyTracking:
        """Run 'chronyc tracking' and parse the output.

        Expected output format (from real system):
        Reference ID    : 47505300 (GPS)
        Stratum         : 1
        Ref time (UTC)  : Sat Mar 28 19:33:05 2026
        System time     : 0.000000054 seconds slow of NTP time
        Last offset     : +0.000420814 seconds
        RMS offset      : 0.038350694 seconds
        Frequency       : 37.652 ppm slow
        Residual freq   : -9.141 ppm
        Skew            : 0.267 ppm
        Root delay      : 0.200000003 seconds
        Root dispersion : 0.177588522 seconds
        Update interval : 32.0 seconds
        Leap status     : Normal
        """
        tracking = ChronyTracking()

        try:
            result = subprocess.run(
                ['chronyc', 'tracking'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.warning(f"chronyc tracking failed: {result.stderr}")
                return tracking
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning(f"chronyc not available: {e}")
            return tracking

        for line in result.stdout.splitlines():
            line = line.strip()
            if ':' not in line:
                continue

            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()

            if key == 'Reference ID':
                # Format: "47505300 (GPS)"
                tracking.reference_id = value
                match = re.search(r'\((.+)\)', value)
                if match:
                    tracking.reference_name = match.group(1)
            elif key == 'Stratum':
                try:
                    tracking.stratum = int(value)
                except ValueError:
                    pass
            elif key == 'Ref time (UTC)':
                tracking.ref_time = value
            elif key == 'System time':
                tracking.system_time_offset = value
            elif key == 'Last offset':
                tracking.last_offset = value
            elif key == 'RMS offset':
                tracking.rms_offset = value
            elif key == 'Frequency':
                tracking.frequency = value
            elif key == 'Residual freq':
                tracking.residual_freq = value
            elif key == 'Skew':
                tracking.skew = value
            elif key == 'Root delay':
                tracking.root_delay = value
            elif key == 'Root dispersion':
                tracking.root_dispersion = value
            elif key == 'Update interval':
                tracking.update_interval = value
            elif key == 'Leap status':
                tracking.leap_status = value

        return tracking

    def _run_chronyc_sources(self) -> list:
        """Run 'chronyc sources -v' and parse the output.

        Expected output format (from real system):
        MS Name/IP address         Stratum Poll Reach LastRx Last sample
        ===============================================================================
        #* GPS                           0   4     0  123m   +877us[+1298us] +/-  200ms
        #? PPS                           0   4     0     -     +0ns[   +0ns] +/-    0ns
        ^- ap-southeast-2.clearnet.>     2   9   377    85   +141ms[ +141ms] +/-   23ms
        """
        sources = []

        try:
            result = subprocess.run(
                ['chronyc', 'sources'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return sources
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return sources

        in_data = False
        for line in result.stdout.splitlines():
            line = line.rstrip()

            # Skip until after the separator line
            if line.startswith('==='):
                in_data = True
                continue

            if not in_data or not line or len(line) < 3:
                continue

            source = self._parse_source_line(line)
            if source:
                sources.append(source)

        return sources

    def _parse_source_line(self, line: str) -> Optional[ChronySource]:
        """Parse a single chronyc sources output line.

        Format: MS Name/IP  Stratum Poll Reach LastRx Last sample
        Example: #* GPS                           0   4     0  123m   +877us[+1298us] +/-  200ms

        M (mode): first character
        S (state): second character
        """
        if len(line) < 3:
            return None

        source = ChronySource()
        source.mode = line[0]
        source.state = line[1]

        # Rest is space-separated but name can be truncated with >
        rest = line[2:].strip()
        if not rest:
            return None

        # Split into fields - the last sample field is complex, so we parse carefully
        # Name  Stratum Poll Reach LastRx Last_sample
        parts = rest.split()
        if len(parts) < 5:
            return None

        source.name = parts[0]

        try:
            source.stratum = int(parts[1])
        except (ValueError, IndexError):
            pass

        try:
            source.poll = int(parts[2])
        except (ValueError, IndexError):
            pass

        try:
            source.reach = int(parts[3], 8)  # octal
        except (ValueError, IndexError):
            pass

        source.last_rx = parts[4] if len(parts) > 4 else ''

        # Everything after LastRx is the "Last sample" field
        # Format: +877us[+1298us] +/- 200ms
        if len(parts) > 5:
            sample_str = ' '.join(parts[5:])
            # Parse offset[measured] +/- error
            match = re.match(
                r'([+-]?\S+)\[([^\]]+)\]\s*\+/-\s*(\S+)',
                sample_str,
            )
            if match:
                source.offset = match.group(1)
                source.measured_offset = match.group(2)
                source.error = match.group(3)
            else:
                source.offset = sample_str

        return source

    def _status_to_dict(self) -> dict:
        """Convert status to JSON-serializable dict."""
        t = self._status.tracking
        return {
            'tracking': {
                'reference_id': t.reference_id,
                'reference_name': t.reference_name,
                'stratum': t.stratum,
                'ref_time': t.ref_time,
                'system_time_offset': t.system_time_offset,
                'last_offset': t.last_offset,
                'rms_offset': t.rms_offset,
                'frequency': t.frequency,
                'residual_freq': t.residual_freq,
                'skew': t.skew,
                'root_delay': t.root_delay,
                'root_dispersion': t.root_dispersion,
                'update_interval': t.update_interval,
                'leap_status': t.leap_status,
                'is_synchronized': t.is_synchronized,
            },
            'sources': [
                {
                    'mode': s.mode,
                    'state': s.state,
                    'source_type': s.source_type,
                    'state_description': s.state_description,
                    'name': s.name,
                    'stratum': s.stratum,
                    'poll': s.poll,
                    'reach': s.reach,
                    'is_reachable': s.is_reachable,
                    'is_selected': s.is_selected,
                    'last_rx': s.last_rx,
                    'offset': s.offset,
                    'measured_offset': s.measured_offset,
                    'error': s.error,
                }
                for s in self._status.sources
            ],
            'last_update': self._status.last_update,
            'error': self._status.error,
        }
