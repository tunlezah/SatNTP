"""
Rolling in-memory history buffer for GPS receiver snapshots.

The buffer is capped (default 600 samples ~= 10 min at 1 Hz) and is the
single source of truth for both the anomaly detector and the /api/history
endpoint. It is additive: nothing in the existing code path depends on it.
"""

from __future__ import annotations

import datetime as _dt
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class ConstellationStats:
    """Per-constellation counters captured at a single sample."""
    tracked: int = 0
    used: int = 0
    avg_snr: float = 0.0
    used_prns: list = field(default_factory=list)
    snr_list: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'tracked': self.tracked,
            'used': self.used,
            'avg_snr': round(self.avg_snr, 2),
            'used_prns': list(self.used_prns),
        }


@dataclass
class Sample:
    """One point-in-time snapshot of the receiver state."""
    t: float                                # system time (unix seconds)
    utc: Optional[str] = None               # HH:MM:SS.ss from NMEA
    utc_epoch: Optional[float] = None       # UTC parsed to unix seconds
    has_fix: bool = False
    mode: int = 1
    lat: Optional[float] = None
    lon: Optional[float] = None
    hdop: Optional[float] = None
    pdop: Optional[float] = None
    vdop: Optional[float] = None
    speed_knots: Optional[float] = None
    constellations: dict = field(default_factory=dict)  # cid -> ConstellationStats
    chrony_offset_s: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            't': self.t,
            'utc': self.utc,
            'utc_epoch': self.utc_epoch,
            'has_fix': self.has_fix,
            'mode': self.mode,
            'lat': self.lat,
            'lon': self.lon,
            'hdop': self.hdop,
            'pdop': self.pdop,
            'vdop': self.vdop,
            'speed_knots': self.speed_knots,
            'constellations': {
                k: v.to_dict() for k, v in self.constellations.items()
            },
            'chrony_offset_s': self.chrony_offset_s,
        }


def parse_utc_epoch(utc_date: Optional[str], utc_time: Optional[str]) -> Optional[float]:
    """Combine NMEA utc_date (YYYY-MM-DD) and utc_time (HH:MM:SS[.ss]) to unix seconds."""
    if not utc_date or not utc_time:
        return None
    try:
        hms, _, frac = utc_time.partition('.')
        d = _dt.datetime.strptime(f'{utc_date} {hms}', '%Y-%m-%d %H:%M:%S')
        ts = d.replace(tzinfo=_dt.timezone.utc).timestamp()
        if frac:
            ts += float('0.' + frac)
        return ts
    except (ValueError, TypeError):
        return None


class HistoryBuffer:
    """Thread-safe ring buffer of receiver snapshots."""

    def __init__(self, max_samples: int = 600):
        self.max_samples = max_samples
        self._samples: Deque[Sample] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def append(self, sample: Sample) -> None:
        with self._lock:
            self._samples.append(sample)

    def latest(self) -> Optional[Sample]:
        with self._lock:
            return self._samples[-1] if self._samples else None

    def snapshot(self, window: Optional[int] = None) -> list:
        """Return a list copy of recent samples (newest last)."""
        with self._lock:
            if window is None or window >= len(self._samples):
                return list(self._samples)
            return list(self._samples)[-window:]

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._samples)
