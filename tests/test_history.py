"""Tests for satntp.history."""

import pytest

from satntp.history import HistoryBuffer, Sample, parse_utc_epoch


class TestHistoryBuffer:
    def test_empty(self):
        buf = HistoryBuffer(max_samples=10)
        assert len(buf) == 0
        assert buf.latest() is None
        assert buf.snapshot() == []

    def test_append_and_latest(self):
        buf = HistoryBuffer(max_samples=10)
        s1 = Sample(t=1.0)
        s2 = Sample(t=2.0)
        buf.append(s1)
        buf.append(s2)
        assert len(buf) == 2
        assert buf.latest() is s2

    def test_ring_wraps_at_cap(self):
        buf = HistoryBuffer(max_samples=3)
        for i in range(5):
            buf.append(Sample(t=float(i)))
        assert len(buf) == 3
        assert buf.latest().t == 4.0
        assert [s.t for s in buf.snapshot()] == [2.0, 3.0, 4.0]

    def test_snapshot_window(self):
        buf = HistoryBuffer(max_samples=100)
        for i in range(10):
            buf.append(Sample(t=float(i)))
        assert [s.t for s in buf.snapshot(window=3)] == [7.0, 8.0, 9.0]
        assert len(buf.snapshot(window=1000)) == 10

    def test_clear(self):
        buf = HistoryBuffer(max_samples=10)
        buf.append(Sample(t=1.0))
        buf.clear()
        assert len(buf) == 0


class TestSampleToDict:
    def test_to_dict_shape(self):
        s = Sample(t=1.0, utc='12:00:00', has_fix=True, lat=10.0, lon=20.0)
        d = s.to_dict()
        assert d['t'] == 1.0
        assert d['utc'] == '12:00:00'
        assert d['has_fix'] is True
        assert d['lat'] == 10.0
        assert 'constellations' in d


class TestParseUtcEpoch:
    def test_valid(self):
        ts = parse_utc_epoch('2026-03-28', '21:34:10')
        assert ts is not None
        assert 1.77e9 < ts < 2.0e9  # sanity range, far-future but bounded

    def test_fractional_seconds(self):
        ts1 = parse_utc_epoch('2026-03-28', '21:34:10')
        ts2 = parse_utc_epoch('2026-03-28', '21:34:10.500')
        assert ts1 is not None and ts2 is not None
        assert abs((ts2 - ts1) - 0.5) < 1e-6

    def test_missing_inputs(self):
        assert parse_utc_epoch(None, '12:00:00') is None
        assert parse_utc_epoch('2026-03-28', None) is None
        assert parse_utc_epoch('', '') is None

    def test_invalid_inputs(self):
        assert parse_utc_epoch('not a date', '12:00:00') is None
        assert parse_utc_epoch('2026-03-28', 'nope') is None
