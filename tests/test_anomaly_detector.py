"""Tests for satntp.anomaly_detector.

Rules are exercised by feeding synthetic samples into the history buffer and
asserting on the events that fire. Hysteresis is set to 1 for most tests so
rules trigger immediately; a dedicated test covers the multi-tick debouncing.
"""

import pytest

from satntp.anomaly_detector import (
    AnomalyDetector,
    DetectorConfig,
    haversine_m,
)
from satntp.history import ConstellationStats, HistoryBuffer, Sample


def _detector(**overrides) -> AnomalyDetector:
    overrides.setdefault('hysteresis_ticks', 1)
    cfg = DetectorConfig(**overrides)
    return AnomalyDetector(HistoryBuffer(max_samples=100), cfg)


def _sample(t, **kw) -> Sample:
    return Sample(t=t, **kw)


def _kinds(events):
    return {e.kind for e in events}


class TestHaversine:
    def test_zero(self):
        assert haversine_m(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0, abs=0.001)

    def test_known_distance(self):
        # 1 degree of latitude ≈ 111_195 m at the equator
        d = haversine_m(0.0, 0.0, 1.0, 0.0)
        assert 110_000 < d < 112_000


class TestPositionJump:
    def test_fires_on_large_jump(self):
        det = _detector(jump_threshold_m=50.0)
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        det.history.append(_sample(1001.0, has_fix=True, lat=0.01, lon=0.0))  # ~1.1 km
        events = det.evaluate()
        assert 'position_jump' in _kinds(events)
        [ev] = [e for e in events if e.kind == 'position_jump']
        assert ev.severity == 'critical'
        assert 'm in' in ev.evidence

    def test_small_drift_not_flagged(self):
        det = _detector(jump_threshold_m=50.0)
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        det.history.append(_sample(1001.0, has_fix=True, lat=0.00001, lon=0.0))
        events = det.evaluate()
        assert 'position_jump' not in _kinds(events)

    def test_requires_fix_on_both(self):
        det = _detector()
        det.history.append(_sample(1000.0, has_fix=False))
        det.history.append(_sample(1001.0, has_fix=True, lat=0.1, lon=0.1))
        events = det.evaluate()
        assert 'position_jump' not in _kinds(events)


class TestUnrealisticSpeed:
    def test_stationary_profile_flags_motion(self):
        det = _detector(
            profile='stationary', jump_threshold_m=9999.0, max_speed_mps=2.0,
        )
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        # 0.0001 deg lon ~= 11.1 m at equator, in 1 s -> 11 m/s, well over 2
        det.history.append(_sample(1001.0, has_fix=True, lat=0.0, lon=0.0001))
        events = det.evaluate()
        assert 'unrealistic_speed' in _kinds(events)

    def test_mobile_profile_tolerates_vehicles(self):
        det = _detector(
            profile='mobile',
            jump_threshold_m=9999.0,
            mobile_max_speed_mps=100.0,
        )
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        # ~11 m/s, well under 100 m/s mobile limit
        det.history.append(_sample(1001.0, has_fix=True, lat=0.0, lon=0.0001))
        events = det.evaluate()
        assert 'unrealistic_speed' not in _kinds(events)


class TestTimeAnomalies:
    def test_time_reverse(self):
        det = _detector()
        det.history.append(_sample(1000.0, utc_epoch=500.0))
        det.history.append(_sample(1001.0, utc_epoch=450.0))
        events = det.evaluate()
        assert 'time_reverse' in _kinds(events)

    def test_time_skew(self):
        det = _detector(time_skew_ms=100.0)
        # system advances 1s, UTC advances 2s -> 1000 ms skew
        det.history.append(_sample(1000.0, utc_epoch=500.0))
        det.history.append(_sample(1001.0, utc_epoch=502.0))
        events = det.evaluate()
        assert 'time_skew' in _kinds(events)

    def test_normal_time_is_silent(self):
        det = _detector(time_skew_ms=100.0)
        det.history.append(_sample(1000.0, utc_epoch=500.0))
        det.history.append(_sample(1001.0, utc_epoch=501.0))
        events = det.evaluate()
        assert 'time_skew' not in _kinds(events)
        assert 'time_reverse' not in _kinds(events)


class TestDOP:
    def test_hdop_spike(self):
        det = _detector(dop_spike=5.0, dop_spike_low=2.0)
        det.history.append(_sample(1000.0, hdop=1.2))
        det.history.append(_sample(1001.0, hdop=8.0))
        events = det.evaluate()
        assert 'dop_spike' in _kinds(events)

    def test_hdop_gradual_not_flagged(self):
        det = _detector(dop_spike=5.0, dop_spike_low=2.0)
        det.history.append(_sample(1000.0, hdop=3.0))
        det.history.append(_sample(1001.0, hdop=8.0))
        events = det.evaluate()
        assert 'dop_spike' not in _kinds(events)


def _consts(**pairs) -> dict:
    """Build constellation stats from kwargs like GP={'avg_snr': 42, 'snr_list': [...]}."""
    out = {}
    for cid, data in pairs.items():
        cs = ConstellationStats()
        for k, v in data.items():
            setattr(cs, k, v)
        out[cid] = cs
    return out


class TestSNRCollapse:
    def test_multi_constellation_collapse_is_critical(self):
        det = _detector(snr_collapse_db=10.0, snr_collapse_window_s=10.0)
        t = 1000.0
        before = _consts(
            GP={'avg_snr': 45.0}, GL={'avg_snr': 42.0}, GA={'avg_snr': 40.0},
        )
        after = _consts(
            GP={'avg_snr': 25.0}, GL={'avg_snr': 20.0}, GA={'avg_snr': 22.0},
        )
        det.history.append(_sample(t, has_fix=True, constellations=before))
        det.history.append(_sample(t + 2, has_fix=True, constellations=after))
        events = det.evaluate()
        assert 'snr_collapse_multi' in _kinds(events)

    def test_single_constellation_collapse_is_warn(self):
        det = _detector(snr_collapse_db=10.0, snr_collapse_window_s=10.0)
        t = 1000.0
        before = _consts(
            GP={'avg_snr': 45.0}, GL={'avg_snr': 42.0},
        )
        after = _consts(
            GP={'avg_snr': 44.0}, GL={'avg_snr': 20.0},  # only GL collapsed
        )
        det.history.append(_sample(t, has_fix=True, constellations=before))
        det.history.append(_sample(t + 2, has_fix=True, constellations=after))
        events = det.evaluate()
        snr_events = [e for e in events if e.kind.startswith('snr_collapse')]
        assert len(snr_events) == 1
        assert snr_events[0].constellation == 'GL'
        assert snr_events[0].severity == 'warn'


class TestSNRUniformity:
    def test_uniform_snr_triggers(self):
        det = _detector(
            snr_uniform_stdev=2.0,
            snr_uniform_min_snr=40.0,
            snr_uniform_min_sats=6,
        )
        # 6 sats all at 45 dB-Hz, stdev = 0
        consts = _consts(GP={'snr_list': [45.0, 45.1, 44.9, 45.0, 44.8, 45.2]})
        det.history.append(_sample(1000.0))
        det.history.append(_sample(1001.0, constellations=consts))
        events = det.evaluate()
        assert 'snr_uniform' in _kinds(events)

    def test_normal_snr_spread_is_silent(self):
        det = _detector(snr_uniform_stdev=2.0, snr_uniform_min_snr=40.0)
        consts = _consts(
            GP={'snr_list': [42.0, 48.0, 35.0, 50.0, 30.0, 45.0]},
        )
        det.history.append(_sample(1000.0))
        det.history.append(_sample(1001.0, constellations=consts))
        events = det.evaluate()
        assert 'snr_uniform' not in _kinds(events)


class TestSatChurn:
    def test_churn_flagged(self):
        det = _detector(churn_ratio=0.5, hysteresis_ticks=1)
        first = _consts(GP={'used_prns': [1, 2, 3, 4]})
        second = _consts(GP={'used_prns': [1, 2, 3, 4]})  # establish baseline
        third = _consts(GP={'used_prns': [10, 11, 12, 13]})  # total churn
        det.history.append(_sample(1000.0, constellations=first))
        det.history.append(_sample(1001.0, constellations=second))
        det.evaluate()  # baseline
        det.history.append(_sample(1002.0, constellations=third))
        events = det.evaluate()
        assert 'used_sat_churn' in _kinds(events)


class TestHysteresis:
    def test_warning_requires_streak(self):
        det = _detector(
            hysteresis_ticks=3,
            snr_uniform_stdev=2.0, snr_uniform_min_sats=6, snr_uniform_min_snr=40.0,
        )
        uniform = _consts(GP={'snr_list': [45.0] * 6})
        det.history.append(_sample(1000.0))
        # First two detections should NOT raise because streak < 3
        for i, t in enumerate([1001.0, 1002.0]):
            det.history.append(_sample(t, constellations=uniform))
            events = det.evaluate()
            assert 'snr_uniform' not in _kinds(events), f'tick {i} raised too early'
        # Third tick crosses threshold
        det.history.append(_sample(1003.0, constellations=uniform))
        events = det.evaluate()
        assert 'snr_uniform' in _kinds(events)

    def test_critical_fires_immediately(self):
        det = _detector(hysteresis_ticks=5, jump_threshold_m=10.0)
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        det.history.append(_sample(1001.0, has_fix=True, lat=0.01, lon=0.0))
        events = det.evaluate()
        assert 'position_jump' in _kinds(events)


class TestSummary:
    def test_empty_summary(self):
        det = _detector()
        s = det.summary()
        assert s['active_count'] == 0
        assert s['worst_severity'] is None
        assert s['enabled'] is True

    def test_worst_severity_is_critical(self):
        det = _detector(jump_threshold_m=10.0, dop_spike=3.0, dop_spike_low=2.0)
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0, hdop=1.0))
        det.history.append(_sample(1001.0, has_fix=True, lat=0.01, lon=0.0, hdop=5.0))
        det.evaluate()
        assert det.summary()['worst_severity'] == 'critical'


class TestDisabled:
    def test_disabled_returns_no_events(self):
        det = AnomalyDetector(
            HistoryBuffer(max_samples=10),
            DetectorConfig(enabled=False),
        )
        det.history.append(_sample(1000.0, has_fix=True, lat=0.0, lon=0.0))
        det.history.append(_sample(1001.0, has_fix=True, lat=10.0, lon=10.0))
        assert det.evaluate() == []
        assert det.summary()['enabled'] is False
