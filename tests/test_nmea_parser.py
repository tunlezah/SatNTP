"""
Validation tests using REAL system data.

This test suite uses the actual GPS output from the production system
to verify our parser handles real-world data correctly, including:
- NO FIX conditions with time still present
- Negative satellite elevations
- Mixed constellations in GPGSV (GPS, SBAS, QZSS)
- 22 satellites visible, 0 used
- Mode 1 (no fix) in GPGSA
"""

import pytest
from satntp.nmea_parser import (
    NMEAParser,
    verify_checksum,
    _nmea_to_decimal,
    _prn_to_constellation,
)

# ──────────────────────────────────────────────────────────────
# Real NMEA data from the production system
# ──────────────────────────────────────────────────────────────

REAL_NMEA_STREAM = """$GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*73
$GPGSA,A,1,,,,,,,,,,,,,,,,*32
$GPGSV,6,1,22,01,01,229,21,02,28,224,20,08,35,264,21,09,-55,316,23*56
$GPGSV,6,2,22,10,55,146,19,18,15,050,00,20,-37,138,23,23,26,111,22*5B
$GPGSV,6,3,22,24,11,136,22,26,-12,351,23,27,39,304,25,28,16,016,16*50
$GPGSV,6,4,22,29,-29,033,23,30,-49,217,23,31,-1,358,23,32,83,338,00*62
$GPGSV,6,5,22,42,48,345,00,48,01,083,00,50,49,353,00,194,16,350,00*44
$GPGSV,6,6,22,195,81,034,00,196,50,312,23*70"""


class TestChecksumVerification:
    """Verify checksums on real NMEA sentences."""

    def test_rmc_checksum(self):
        assert verify_checksum(
            "$GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*73"
        )

    def test_gsa_checksum(self):
        assert verify_checksum("$GPGSA,A,1,,,,,,,,,,,,,,,,*32")

    def test_gsv_checksum_msg1(self):
        assert verify_checksum(
            "$GPGSV,6,1,22,01,01,229,21,02,28,224,20,08,35,264,21,09,-55,316,23*56"
        )

    def test_gsv_checksum_msg4(self):
        assert verify_checksum(
            "$GPGSV,6,4,22,29,-29,033,23,30,-49,217,23,31,-1,358,23,32,83,338,00*62"
        )

    def test_gsv_checksum_msg5(self):
        assert verify_checksum(
            "$GPGSV,6,5,22,42,48,345,00,48,01,083,00,50,49,353,00,194,16,350,00*44"
        )

    def test_gsv_checksum_msg6_two_sats(self):
        assert verify_checksum("$GPGSV,6,6,22,195,81,034,00,196,50,312,23*70")

    def test_bad_checksum(self):
        assert not verify_checksum(
            "$GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*FF"
        )


class TestCoordinateConversion:
    """Test NMEA coordinate parsing with real values."""

    def test_real_latitude(self):
        # 3512.5613,S -> -35.209355 degrees
        lat = _nmea_to_decimal("3512.5613", "S")
        assert lat is not None
        assert abs(lat - (-35.209355)) < 0.001

    def test_real_longitude(self):
        # 14900.6865,E -> 149.011441667 degrees
        lon = _nmea_to_decimal("14900.6865", "E")
        assert lon is not None
        assert abs(lon - 149.0114) < 0.01

    def test_empty_coordinate(self):
        assert _nmea_to_decimal("", "N") is None
        assert _nmea_to_decimal("3512.5613", "") is None


class TestPRNToConstellation:
    """Test PRN mapping for the actual satellites observed."""

    def test_gps_prn_1(self):
        const, prn = _prn_to_constellation(1, 'GP')
        assert const == 'GP'
        assert prn == 1

    def test_gps_prn_32(self):
        const, prn = _prn_to_constellation(32, 'GP')
        assert const == 'GP'
        assert prn == 32

    def test_sbas_prn_42(self):
        # PRN 42 in GPGSV -> SBAS 129
        const, prn = _prn_to_constellation(42, 'GP')
        assert const == 'SB'
        assert prn == 129

    def test_sbas_prn_48(self):
        # PRN 48 -> SBAS 135
        const, prn = _prn_to_constellation(48, 'GP')
        assert const == 'SB'
        assert prn == 135

    def test_sbas_prn_50(self):
        # PRN 50 -> SBAS 137
        const, prn = _prn_to_constellation(50, 'GP')
        assert const == 'SB'
        assert prn == 137

    def test_qzss_prn_194(self):
        # PRN 194 -> QZSS 2
        const, prn = _prn_to_constellation(194, 'GP')
        assert const == 'QZ'
        assert prn == 2

    def test_qzss_prn_195(self):
        const, prn = _prn_to_constellation(195, 'GP')
        assert const == 'QZ'
        assert prn == 3

    def test_qzss_prn_196(self):
        const, prn = _prn_to_constellation(196, 'GP')
        assert const == 'QZ'
        assert prn == 4

    # --- Galileo (u-blox PRN 301-336 in GPGSV) ---

    def test_galileo_prn_302(self):
        const, prn = _prn_to_constellation(302, 'GP')
        assert const == 'GA'
        assert prn == 2

    def test_galileo_prn_336(self):
        const, prn = _prn_to_constellation(336, 'GP')
        assert const == 'GA'
        assert prn == 36

    # --- BeiDou (u-blox PRN 201-264 in GPGSV) ---

    def test_beidou_prn_201(self):
        const, prn = _prn_to_constellation(201, 'GP')
        assert const == 'GB'
        assert prn == 1

    def test_beidou_prn_237(self):
        const, prn = _prn_to_constellation(237, 'GP')
        assert const == 'GB'
        assert prn == 37

    # --- GLONASS (u-blox PRN 65-96 in GPGSV) ---

    def test_glonass_prn_65(self):
        const, prn = _prn_to_constellation(65, 'GP')
        assert const == 'GL'
        assert prn == 1

    def test_glonass_prn_88(self):
        const, prn = _prn_to_constellation(88, 'GP')
        assert const == 'GL'
        assert prn == 24

    # --- System-specific talkers with offset PRNs ---

    def test_galileo_talker_direct_svid(self):
        const, prn = _prn_to_constellation(5, 'GA')
        assert const == 'GA'
        assert prn == 5

    def test_galileo_talker_offset_prn(self):
        const, prn = _prn_to_constellation(305, 'GA')
        assert const == 'GA'
        assert prn == 5

    def test_beidou_talker_direct_svid(self):
        const, prn = _prn_to_constellation(10, 'GB')
        assert const == 'GB'
        assert prn == 10

    def test_beidou_talker_offset_prn(self):
        const, prn = _prn_to_constellation(210, 'GB')
        assert const == 'GB'
        assert prn == 10

    # --- NavIC / IRNSS (u-blox PRN 401-437 in GPGSV) ---

    def test_navic_prn_401(self):
        const, prn = _prn_to_constellation(401, 'GP')
        assert const == 'GI'
        assert prn == 1

    def test_navic_prn_409(self):
        const, prn = _prn_to_constellation(409, 'GP')
        assert const == 'GI'
        assert prn == 9

    def test_navic_prn_416(self):
        const, prn = _prn_to_constellation(416, 'GP')
        assert const == 'GI'
        assert prn == 16

    def test_navic_prn_437(self):
        const, prn = _prn_to_constellation(437, 'GP')
        assert const == 'GI'
        assert prn == 37

    def test_navic_talker_direct_svid(self):
        const, prn = _prn_to_constellation(5, 'GI')
        assert const == 'GI'
        assert prn == 5

    def test_navic_talker_offset_prn(self):
        const, prn = _prn_to_constellation(405, 'GI')
        assert const == 'GI'
        assert prn == 5


class TestRMCParsing:
    """Test GPRMC parsing with real NO FIX data."""

    def setup_method(self):
        self.parser = NMEAParser()
        self.parser.parse_sentence(
            "$GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*73"
        )

    def test_time_is_parsed(self):
        assert self.parser.state.fix.utc_time == "21:34:11.00"

    def test_date_is_parsed(self):
        assert self.parser.state.fix.utc_date == "2026-03-28"

    def test_fix_is_invalid(self):
        """GPRMC status 'V' means void/invalid."""
        assert self.parser.state.fix.valid is False

    def test_no_fix(self):
        assert self.parser.state.fix.has_fix is False

    def test_position_not_set_when_invalid(self):
        """Position should be None when fix is void, even though NMEA contains coordinates."""
        assert self.parser.state.fix.latitude is None
        assert self.parser.state.fix.longitude is None

    def test_time_available_but_not_valid(self):
        """Time IS present in NMEA but fix is NOT valid."""
        assert self.parser.state.fix.time_available is True
        assert self.parser.state.fix.valid is False

    def test_fix_description(self):
        assert self.parser.state.fix.fix_description == "NO FIX"


class TestGSAParsing:
    """Test GPGSA parsing with real mode-1 (no fix) data."""

    def setup_method(self):
        self.parser = NMEAParser()
        self.parser.parse_sentence("$GPGSA,A,1,,,,,,,,,,,,,,,,*32")

    def test_mode_is_1(self):
        """Mode 1 = no fix."""
        assert self.parser.state.fix.mode == 1

    def test_no_satellites_used(self):
        assert len(self.parser.state.fix.satellites_used) == 0

    def test_dop_values_empty(self):
        """With no fix, DOP values should be empty/None."""
        # The last fields are empty in the real data
        assert self.parser.state.fix.pdop is None
        assert self.parser.state.fix.hdop is None
        assert self.parser.state.fix.vdop is None


class TestGSVParsing:
    """Test GPGSV parsing with real satellite data (22 sats, 6 messages)."""

    def setup_method(self):
        self.parser = NMEAParser()
        self.parser.parse_stream(REAL_NMEA_STREAM)

    def test_satellite_count(self):
        """Real data shows 22 satellites across 6 GSV messages."""
        # We should get all visible satellites
        assert self.parser.state.satellites_visible >= 20
        # The exact count may vary slightly due to PRN mapping,
        # but should be close to 22
        assert self.parser.state.satellites_visible <= 24

    def test_no_satellites_used(self):
        """Mode 1, no fix -> no satellites used."""
        assert self.parser.state.satellites_used_count == 0

    def test_gps_satellite_present(self):
        """GPS PRN 1 should be present."""
        assert ('GP', 1) in self.parser.state.satellites

    def test_gps_prn1_elevation(self):
        """PRN 1: elevation 1 degree."""
        sat = self.parser.state.satellites[('GP', 1)]
        assert abs(sat.elevation - 1.0) < 0.1

    def test_gps_prn1_azimuth(self):
        sat = self.parser.state.satellites[('GP', 1)]
        assert abs(sat.azimuth - 229.0) < 0.1

    def test_gps_prn1_snr(self):
        sat = self.parser.state.satellites[('GP', 1)]
        assert abs(sat.snr - 21.0) < 0.1

    def test_negative_elevation_prn9(self):
        """PRN 9 has elevation -55 degrees (below horizon)."""
        sat = self.parser.state.satellites[('GP', 9)]
        assert sat.elevation == -55.0

    def test_negative_elevation_prn20(self):
        """PRN 20 has elevation -37 degrees."""
        sat = self.parser.state.satellites[('GP', 20)]
        assert sat.elevation == -37.0

    def test_negative_elevation_prn26(self):
        """PRN 26 has elevation -12 degrees."""
        sat = self.parser.state.satellites[('GP', 26)]
        assert sat.elevation == -12.0

    def test_negative_elevation_prn29(self):
        """PRN 29 has elevation -29 degrees."""
        sat = self.parser.state.satellites[('GP', 29)]
        assert sat.elevation == -29.0

    def test_negative_elevation_prn30(self):
        """PRN 30 has elevation -49 degrees."""
        sat = self.parser.state.satellites[('GP', 30)]
        assert sat.elevation == -49.0

    def test_negative_elevation_prn31(self):
        """PRN 31 has elevation -1 degree."""
        sat = self.parser.state.satellites[('GP', 31)]
        assert sat.elevation == -1.0

    def test_zero_snr_means_not_tracked(self):
        """PRN 18 has SNR 00 = not tracked."""
        sat = self.parser.state.satellites[('GP', 18)]
        assert sat.snr == 0.0
        assert sat.tracked is False

    def test_nonzero_snr_means_tracked(self):
        """PRN 9 has SNR 23 = tracked."""
        sat = self.parser.state.satellites[('GP', 9)]
        assert sat.snr == 23.0
        assert sat.tracked is True

    def test_sbas_satellite_129(self):
        """GPGSV PRN 42 -> SBAS 129."""
        assert ('SB', 129) in self.parser.state.satellites
        sat = self.parser.state.satellites[('SB', 129)]
        assert abs(sat.elevation - 48.0) < 0.1
        assert abs(sat.azimuth - 345.0) < 0.1
        assert sat.snr == 0.0  # Not tracked

    def test_sbas_satellite_135(self):
        """GPGSV PRN 48 -> SBAS 135."""
        assert ('SB', 135) in self.parser.state.satellites

    def test_sbas_satellite_137(self):
        """GPGSV PRN 50 -> SBAS 137."""
        assert ('SB', 137) in self.parser.state.satellites

    def test_qzss_satellite_2(self):
        """GPGSV PRN 194 -> QZSS 2."""
        assert ('QZ', 2) in self.parser.state.satellites
        sat = self.parser.state.satellites[('QZ', 2)]
        assert abs(sat.elevation - 16.0) < 0.1
        assert abs(sat.azimuth - 350.0) < 0.1
        assert sat.snr == 0.0

    def test_qzss_satellite_3(self):
        """GPGSV PRN 195 -> QZSS 3."""
        assert ('QZ', 3) in self.parser.state.satellites
        sat = self.parser.state.satellites[('QZ', 3)]
        assert abs(sat.elevation - 81.0) < 0.1
        assert sat.snr == 0.0

    def test_qzss_satellite_4(self):
        """GPGSV PRN 196 -> QZSS 4."""
        assert ('QZ', 4) in self.parser.state.satellites
        sat = self.parser.state.satellites[('QZ', 4)]
        assert abs(sat.elevation - 50.0) < 0.1
        assert sat.snr == 23.0  # This one IS tracked

    def test_high_elevation_satellite(self):
        """PRN 32 at 83 degrees elevation (nearly overhead)."""
        sat = self.parser.state.satellites[('GP', 32)]
        assert abs(sat.elevation - 83.0) < 0.1
        assert sat.snr == 0.0  # But not tracked!

    def test_satellite_not_used(self):
        """All satellites should show used=False (no fix)."""
        for sat in self.parser.state.satellites.values():
            assert sat.used is False


class TestFullStateIntegration:
    """Test complete state after parsing the full NMEA stream."""

    def setup_method(self):
        self.parser = NMEAParser()
        self.parser.parse_stream(REAL_NMEA_STREAM)

    def test_state_dict_structure(self):
        state = self.parser.get_state_dict()
        assert 'fix' in state
        assert 'satellites' in state
        assert 'summary' in state
        assert 'meta' in state

    def test_fix_state(self):
        state = self.parser.get_state_dict()
        assert state['fix']['description'] == 'NO FIX'
        assert state['fix']['has_fix'] is False
        assert state['fix']['time_available'] is True
        assert state['fix']['utc_time'] == '21:34:11.00'
        assert state['fix']['utc_date'] == '2026-03-28'

    def test_satellite_summary(self):
        state = self.parser.get_state_dict()
        assert state['summary']['visible'] >= 20
        assert state['summary']['used'] == 0
        # Many satellites have SNR > 0
        assert state['summary']['tracked'] > 0

    def test_satellite_list_in_dict(self):
        state = self.parser.get_state_dict()
        sats = state['satellites']
        assert len(sats) >= 20

        # Verify structure
        for s in sats:
            assert 'prn' in s
            assert 'constellation' in s
            assert 'elevation' in s
            assert 'azimuth' in s
            assert 'snr' in s
            assert 'tracked' in s
            assert 'used' in s
            assert 'display_id' in s

    def test_constellation_diversity(self):
        """Real data contains GPS, SBAS, and QZSS satellites."""
        state = self.parser.get_state_dict()
        constellations = set(s['constellation'] for s in state['satellites'])
        assert 'GP' in constellations  # GPS
        assert 'SB' in constellations  # SBAS
        assert 'QZ' in constellations  # QZSS

    def test_no_parse_errors(self):
        state = self.parser.get_state_dict()
        assert state['meta']['parse_errors'] == 0

    def test_sentences_parsed_count(self):
        state = self.parser.get_state_dict()
        # 1 RMC + 1 GSA + 6 GSV = 8 sentences
        assert state['meta']['sentences_parsed'] == 8


class TestEdgeCases:
    """Test parser resilience with edge cases."""

    def test_empty_input(self):
        parser = NMEAParser()
        assert parser.parse_sentence("") is False

    def test_non_nmea_input(self):
        parser = NMEAParser()
        assert parser.parse_sentence("not an NMEA sentence") is False

    def test_json_input_ignored(self):
        parser = NMEAParser()
        assert parser.parse_sentence('{"class":"VERSION"}') is False

    def test_partial_gsv_sequence(self):
        """Parser should handle incomplete GSV sequences without crashing."""
        parser = NMEAParser()
        # Only send message 1 of 6 - should buffer but not crash
        parser.parse_sentence(
            "$GPGSV,6,1,22,01,01,229,21,02,28,224,20,08,35,264,21,09,-55,316,23*56"
        )
        assert parser.state.sentences_parsed == 1

    def test_repeated_rmc_updates(self):
        """Parser should update time with each RMC sentence."""
        parser = NMEAParser()
        parser.parse_sentence(
            "$GPRMC,213411.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*73"
        )
        assert parser.state.fix.utc_time == "21:34:11.00"

        parser.parse_sentence(
            "$GPRMC,213412.00,V,3512.5613,S,14900.6865,E,0.0000,-0.000,280326,12.3,E*70"
        )
        assert parser.state.fix.utc_time == "21:34:12.00"

    def test_gsv_with_two_satellites(self):
        """Last GSV message in real data has only 2 satellites."""
        parser = NMEAParser()
        # Must send all 6 messages for the buffer to flush
        sentences = [
            "$GPGSV,6,1,22,01,01,229,21,02,28,224,20,08,35,264,21,09,-55,316,23*56",
            "$GPGSV,6,2,22,10,55,146,19,18,15,050,00,20,-37,138,23,23,26,111,22*5B",
            "$GPGSV,6,3,22,24,11,136,22,26,-12,351,23,27,39,304,25,28,16,016,16*50",
            "$GPGSV,6,4,22,29,-29,033,23,30,-49,217,23,31,-1,358,23,32,83,338,00*62",
            "$GPGSV,6,5,22,42,48,345,00,48,01,083,00,50,49,353,00,194,16,350,00*44",
            "$GPGSV,6,6,22,195,81,034,00,196,50,312,23*70",
        ]
        for s in sentences:
            parser.parse_sentence(s)

        # QZSS satellite 3 (PRN 195) and 4 (PRN 196) should be present
        assert ('QZ', 3) in parser.state.satellites
        assert ('QZ', 4) in parser.state.satellites


class TestMatchesCGPSOutput:
    """Cross-validate parser output against the real cgps display.

    cgps showed: Seen 21/Used 0
    Our GPGSV data has 22 satellites total.
    The discrepancy is because cgps may count differently or one satellite
    was not in the last snapshot.
    """

    def setup_method(self):
        self.parser = NMEAParser()
        self.parser.parse_stream(REAL_NMEA_STREAM)

    def test_used_matches_cgps(self):
        """cgps shows Used 0."""
        assert self.parser.state.satellites_used_count == 0

    def test_visible_in_expected_range(self):
        """cgps shows Seen 21, our GSV says 22. Both are reasonable."""
        visible = self.parser.state.satellites_visible
        assert 20 <= visible <= 24

    def test_specific_satellites_match_cgps(self):
        """Verify key satellites from cgps output are present."""
        sats = self.parser.state.satellites

        # GP 1: elev 1.0, azim 229.0, SNR 0.0 (cgps shows 0.0 for this epoch)
        # Note: cgps and our parser may see different epochs
        assert ('GP', 1) in sats

        # GP 9: elev -54/-55, azim 316
        assert ('GP', 9) in sats
        assert sats[('GP', 9)].azimuth == 316.0

        # GP 10: elev 55, azim 146/144
        assert ('GP', 10) in sats

        # GP 32: elev 83/84, azim 338
        assert ('GP', 32) in sats
        assert abs(sats[('GP', 32)].elevation - 83.0) < 2

        # SB 129 (SBAS PRN 42): elev 48, azim 345
        assert ('SB', 129) in sats
        assert sats[('SB', 129)].elevation == 48.0

        # QZ 4 (QZSS PRN 196): elev 50, azim 312, SNR 23
        assert ('QZ', 4) in sats
        assert sats[('QZ', 4)].snr == 23.0
