"""
GPS integrity / anomaly detector.

Consumes a HistoryBuffer and runs a handful of lightweight rules against the
latest samples. Rules are conservative by default: critical events fire
immediately, warning events require a short streak (hysteresis) so that
transient glitches do not flap the UI.

All state is in-memory; the detector is completely optional and can be
disabled via config without affecting anything else.
"""

from __future__ import annotations

import math
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from satntp.history import HistoryBuffer, Sample


_EARTH_R = 6_371_000.0  # metres

SEVERITY_RANK = {'info': 1, 'warn': 2, 'critical': 3}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


@dataclass
class Anomaly:
    """A single detected anomaly event."""
    kind: str
    severity: str                       # info | warn | critical
    constellation: Optional[str]        # cid if attributable, else None
    started_at: float                   # unix seconds
    evidence: str

    def to_dict(self) -> dict:
        return {
            'kind': self.kind,
            'severity': self.severity,
            'constellation': self.constellation,
            'started_at': self.started_at,
            'evidence': self.evidence,
        }


@dataclass
class DetectorConfig:
    enabled: bool = True
    profile: str = 'stationary'                 # stationary | mobile
    jump_threshold_m: float = 50.0
    max_speed_mps: float = 2.0                  # stationary: effectively 0
    mobile_max_speed_mps: float = 95.0          # road-vehicle-ish default
    time_skew_ms: float = 250.0
    dop_spike: float = 5.0
    dop_spike_low: float = 2.0
    snr_collapse_db: float = 10.0
    snr_collapse_window_s: float = 5.0
    snr_uniform_stdev: float = 2.0
    snr_uniform_min_snr: float = 40.0
    snr_uniform_min_sats: int = 6
    churn_ratio: float = 0.5
    hysteresis_ticks: int = 3
    keep_recent: int = 200

    @classmethod
    def from_env(cls) -> 'DetectorConfig':
        """Build a config from SATNTP_* env vars, with safe defaults."""
        def _f(name: str, default: float) -> float:
            try:
                return float(os.environ[name])
            except (KeyError, ValueError):
                return default

        def _i(name: str, default: int) -> int:
            try:
                return int(os.environ[name])
            except (KeyError, ValueError):
                return default

        enabled = os.environ.get('SATNTP_ANOMALY', '1').lower() not in ('0', 'false', 'no')
        profile = os.environ.get('SATNTP_ANOMALY_PROFILE', 'stationary').lower()
        if profile not in ('stationary', 'mobile'):
            profile = 'stationary'
        return cls(
            enabled=enabled,
            profile=profile,
            jump_threshold_m=_f('SATNTP_JUMP_M', 50.0),
            max_speed_mps=_f('SATNTP_MAX_SPEED_MPS', 2.0),
            mobile_max_speed_mps=_f('SATNTP_MOBILE_MAX_SPEED_MPS', 95.0),
            time_skew_ms=_f('SATNTP_TIME_SKEW_MS', 250.0),
            hysteresis_ticks=_i('SATNTP_HYSTERESIS_TICKS', 3),
        )


class AnomalyDetector:
    """Evaluates rules against a shared HistoryBuffer."""

    def __init__(self, history: HistoryBuffer, config: Optional[DetectorConfig] = None):
        self.history = history
        self.cfg = config or DetectorConfig()
        self._active: dict = {}             # kind -> Anomaly
        self._recent: deque = deque(maxlen=self.cfg.keep_recent)
        self._streaks: dict = {}            # kind -> consecutive detection count
        self._last_used_prns: Optional[set] = None
        self._lock = threading.Lock()

    # ──────────────────────────────────────────────────────────
    # Evaluation
    # ──────────────────────────────────────────────────────────
    def evaluate(self) -> List[Anomaly]:
        """Run all rules against the latest history. Idempotent per sample."""
        if not self.cfg.enabled:
            return []

        samples = self.history.snapshot(window=120)
        if len(samples) < 2:
            return []

        curr = samples[-1]
        prev = samples[-2]
        events: List[Anomaly] = []

        self._rule_position_and_speed(prev, curr, events)
        self._rule_time(prev, curr, events)
        self._rule_dop(prev, curr, events)
        self._rule_snr_collapse(samples, curr, events)
        self._rule_snr_uniform(curr, events)
        self._rule_sat_churn(curr, events)

        return self._apply_hysteresis(events)

    # ──────────────────────────────────────────────────────────
    # Rules
    # ──────────────────────────────────────────────────────────
    def _rule_position_and_speed(self, prev: Sample, curr: Sample, out: List[Anomaly]) -> None:
        if not (curr.has_fix and prev.has_fix):
            return
        if None in (curr.lat, curr.lon, prev.lat, prev.lon):
            return
        d = haversine_m(prev.lat, prev.lon, curr.lat, curr.lon)
        dt = max(curr.t - prev.t, 1e-3)

        if d > self.cfg.jump_threshold_m:
            out.append(Anomaly(
                kind='position_jump',
                severity='critical',
                constellation=None,
                started_at=curr.t,
                evidence=f'Jumped {d:.0f} m in {dt:.1f} s',
            ))

        speed = d / dt
        speed_limit = (
            self.cfg.max_speed_mps
            if self.cfg.profile == 'stationary'
            else self.cfg.mobile_max_speed_mps
        )
        if speed > speed_limit:
            out.append(Anomaly(
                kind='unrealistic_speed',
                severity='warn',
                constellation=None,
                started_at=curr.t,
                evidence=f'Derived speed {speed:.1f} m/s exceeds {speed_limit:.0f} m/s ({self.cfg.profile})',
            ))

    def _rule_time(self, prev: Sample, curr: Sample, out: List[Anomaly]) -> None:
        if curr.utc_epoch is None or prev.utc_epoch is None:
            return
        d_utc = curr.utc_epoch - prev.utc_epoch
        d_sys = curr.t - prev.t
        if d_utc < -0.5:
            out.append(Anomaly(
                kind='time_reverse',
                severity='critical',
                constellation=None,
                started_at=curr.t,
                evidence=f'UTC moved backward by {-d_utc:.3f} s',
            ))
            return
        skew_ms = abs(d_utc - d_sys) * 1000.0
        if skew_ms > self.cfg.time_skew_ms:
            out.append(Anomaly(
                kind='time_skew',
                severity='warn',
                constellation=None,
                started_at=curr.t,
                evidence=f'UTC/system drift {skew_ms:.0f} ms over one tick',
            ))

    def _rule_dop(self, prev: Sample, curr: Sample, out: List[Anomaly]) -> None:
        if curr.hdop is None or prev.hdop is None:
            return
        if curr.hdop > self.cfg.dop_spike and prev.hdop < self.cfg.dop_spike_low:
            out.append(Anomaly(
                kind='dop_spike',
                severity='warn',
                constellation=None,
                started_at=curr.t,
                evidence=f'HDOP spiked {prev.hdop:.1f} to {curr.hdop:.1f}',
            ))

    def _rule_snr_collapse(self, samples: list, curr: Sample, out: List[Anomaly]) -> None:
        window = self.cfg.snr_collapse_window_s
        window_samples = [s for s in samples if s.t >= curr.t - window]
        if len(window_samples) < 2:
            return
        baseline = window_samples[0]
        collapsed = []
        for cid, stats in curr.constellations.items():
            prev_stats = baseline.constellations.get(cid)
            if not prev_stats:
                continue
            before = prev_stats.avg_snr if hasattr(prev_stats, 'avg_snr') else prev_stats.get('avg_snr', 0)
            after = stats.avg_snr if hasattr(stats, 'avg_snr') else stats.get('avg_snr', 0)
            if before - after >= self.cfg.snr_collapse_db and before > 0:
                collapsed.append((cid, before, after))

        if len(collapsed) >= 3:
            names = ', '.join(c for c, _, _ in collapsed)
            out.append(Anomaly(
                kind='snr_collapse_multi',
                severity='critical',
                constellation=None,
                started_at=curr.t,
                evidence=f'SNR collapse across {names} — possible jamming',
            ))
        else:
            for cid, before, after in collapsed:
                out.append(Anomaly(
                    kind=f'snr_collapse_{cid}',
                    severity='warn',
                    constellation=cid,
                    started_at=curr.t,
                    evidence=f'Avg SNR on {cid} dropped {before:.0f} to {after:.0f} dB-Hz in {window:.0f} s',
                ))

    def _rule_snr_uniform(self, curr: Sample, out: List[Anomaly]) -> None:
        snrs: list = []
        for stats in curr.constellations.values():
            sl = stats.snr_list if hasattr(stats, 'snr_list') else stats.get('snr_list', [])
            snrs.extend([s for s in sl if s >= self.cfg.snr_uniform_min_snr])
        if len(snrs) < self.cfg.snr_uniform_min_sats:
            return
        mean = sum(snrs) / len(snrs)
        var = sum((x - mean) ** 2 for x in snrs) / len(snrs)
        stdev = math.sqrt(var)
        if stdev < self.cfg.snr_uniform_stdev:
            out.append(Anomaly(
                kind='snr_uniform',
                severity='warn',
                constellation=None,
                started_at=curr.t,
                evidence=f'{len(snrs)} sats uniformly strong (mu={mean:.1f}, sigma={stdev:.1f}) — possible spoofing',
            ))

    def _rule_sat_churn(self, curr: Sample, out: List[Anomaly]) -> None:
        curr_used: set = set()
        for cid, stats in curr.constellations.items():
            prns = stats.used_prns if hasattr(stats, 'used_prns') else stats.get('used_prns', [])
            for p in prns:
                curr_used.add((cid, p))
        if self._last_used_prns and curr_used:
            overlap = curr_used & self._last_used_prns
            denom = max(len(curr_used), len(self._last_used_prns))
            churn = 1.0 - len(overlap) / denom if denom else 0.0
            if churn > self.cfg.churn_ratio:
                out.append(Anomaly(
                    kind='used_sat_churn',
                    severity='info',
                    constellation=None,
                    started_at=curr.t,
                    evidence=f'Used satellite set turned over {churn * 100:.0f}%',
                ))
        if curr_used:
            self._last_used_prns = curr_used

    # ──────────────────────────────────────────────────────────
    # Hysteresis + bookkeeping
    # ──────────────────────────────────────────────────────────
    def _apply_hysteresis(self, events: List[Anomaly]) -> List[Anomaly]:
        seen_kinds = {e.kind for e in events}

        # Decay streaks for kinds that did not fire this tick
        for kind in list(self._streaks.keys()):
            if kind not in seen_kinds:
                self._streaks[kind] = 0

        raised: List[Anomaly] = []
        with self._lock:
            new_active: dict = {}
            for ev in events:
                self._streaks[ev.kind] = self._streaks.get(ev.kind, 0) + 1
                threshold = 1 if ev.severity == 'critical' else self.cfg.hysteresis_ticks
                if self._streaks[ev.kind] >= threshold:
                    # preserve started_at if already active
                    existing = self._active.get(ev.kind)
                    if existing:
                        ev.started_at = existing.started_at
                    else:
                        self._recent.append(ev)
                    new_active[ev.kind] = ev
                    raised.append(ev)
            self._active = new_active
        return raised

    # ──────────────────────────────────────────────────────────
    # Public views
    # ──────────────────────────────────────────────────────────
    def active(self) -> List[Anomaly]:
        with self._lock:
            return list(self._active.values())

    def recent(self, limit: int = 20) -> List[Anomaly]:
        with self._lock:
            items = list(self._recent)
        return items[-limit:]

    def summary(self) -> dict:
        with self._lock:
            worst: Optional[str] = None
            worst_rank = 0
            for a in self._active.values():
                r = SEVERITY_RANK.get(a.severity, 0)
                if r > worst_rank:
                    worst_rank = r
                    worst = a.severity
            return {
                'active_count': len(self._active),
                'worst_severity': worst,
                'enabled': self.cfg.enabled,
                'profile': self.cfg.profile,
            }
