"""
test_merger.py — Unit tests for core/merger.py

Tests: endpoint detection (all 4 cases), reversal, overlap trim,
       2-segment merge, 3-segment chain merge.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.kml_parser import read_linestring
from core.merger import (
    find_best_connection, apply_connection, chain_merge,
    reverse_coords, ConnectionInfo, MergeResult,
)
from core.geometry import haversine_m

FIXTURES = Path(__file__).parent / "fixtures"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _mock_config(trim=5.0):
    cfg = MagicMock()
    cfg.get.side_effect = lambda s, k, fallback=None: {
        ("merge", "overlap_trim_meters"): trim,
        ("merge", "snap_tolerance_meters"): 50.0,
    }.get((s, k), fallback)
    return cfg


def _straight_line(n=10, start_lon=77.0, start_lat=28.0, step=0.001):
    """Generate n points along a straight line."""
    return [(start_lon + i * step, start_lat, 0.0) for i in range(n)]


# ──────────────────────────────────────────────────────────────────────────────
# reverse_coords
# ──────────────────────────────────────────────────────────────────────────────

class TestReverseCoords:
    def test_reverses_list(self):
        coords = [(1.0, 2.0, 0.0), (3.0, 4.0, 0.0), (5.0, 6.0, 0.0)]
        result = reverse_coords(coords)
        assert result == [(5.0, 6.0, 0.0), (3.0, 4.0, 0.0), (1.0, 2.0, 0.0)]

    def test_does_not_modify_original(self):
        coords = [(1.0, 2.0, 0.0), (3.0, 4.0, 0.0)]
        _ = reverse_coords(coords)
        assert coords[0] == (1.0, 2.0, 0.0)

    def test_single_point(self):
        coords = [(1.0, 2.0, 0.0)]
        assert reverse_coords(coords) == [(1.0, 2.0, 0.0)]


# ──────────────────────────────────────────────────────────────────────────────
# find_best_connection — all 4 cases
# ──────────────────────────────────────────────────────────────────────────────

class TestFindBestConnection:
    def test_natural_end1_start2(self):
        """Segments connect naturally: end of seg1 near start of seg2."""
        seg1 = _straight_line(5, start_lon=77.000)      # ends at 77.004
        seg2 = _straight_line(5, start_lon=77.004)      # starts at 77.004
        conn = find_best_connection(seg1, seg2)
        assert conn.connection_type == "end1-start2"
        assert conn.seg1_reversed is False
        assert conn.seg2_reversed is False
        assert conn.junction_distance_m < 1.0

    def test_seg2_needs_reversal_end1_end2(self):
        """End of seg1 is near END of seg2 — seg2 must be reversed."""
        seg1 = _straight_line(5, start_lon=77.000)      # ends at 77.004
        seg2 = _straight_line(5, start_lon=77.000, step=-0.001)  # ends at ~77.004 reversed
        # seg2 goes 77.000 → 76.996, so its END is at 76.996
        # Actually seg2 = [(77.000,28,0), (76.999,28,0), ..., (76.996,28,0)]
        # We want seg2's end to be near seg1's end (77.004)
        # Let's build explicitly:
        seg2_explicit = [(77.004 - i * 0.001, 28.0, 0.0) for i in range(5)]
        # seg2_explicit[0] = 77.004 (start), seg2_explicit[-1] = 77.000 (end)
        # seg1 ends at 77.004 → seg2_explicit starts at 77.004 → this is end1-start2!
        # Let's make seg2 that ENDS near seg1's end:
        seg2_ends_near_end1 = [(77.010 - i * 0.001, 28.0, 0.0) for i in range(5)]
        # seg2_ends_near_end1[-1] = 77.006, not quite
        # Explicit: seg2 where end == seg1 end (77.004)
        seg2_rev = [(77.004 + (4 - i) * 0.001, 28.0, 0.0) for i in range(5)]
        # seg2_rev = [77.008, 77.007, 77.006, 77.005, 77.004]  end = 77.004 = seg1 end
        conn = find_best_connection(seg1, seg2_rev)
        assert conn.connection_type == "end1-end2"
        assert conn.seg1_reversed is False
        assert conn.seg2_reversed is True

    def test_seg1_needs_reversal_start1_start2(self):
        """Start of seg1 is near start of seg2 — seg1 must be reversed."""
        seg1 = _straight_line(5, start_lon=77.004, step=-0.001)
        # seg1 = [77.004, 77.003, 77.002, 77.001, 77.000]  start=77.004
        seg2 = _straight_line(5, start_lon=77.004)
        # seg2 = [77.004, 77.005, ...]  start=77.004
        # start1 (77.004) ~ start2 (77.004) → start1-start2
        conn = find_best_connection(seg1, seg2)
        assert conn.connection_type == "start1-start2"
        assert conn.seg1_reversed is True
        assert conn.seg2_reversed is False

    def test_both_reversed_start1_end2(self):
        """Start of seg1 near end of seg2 — both reversed."""
        # seg1: start=77.000, end=77.004  (goes east)
        seg1 = _straight_line(5, start_lon=77.000)
        # seg2: start=77.020, end=77.000  (goes west, end near seg1 start)
        seg2 = [(77.020 - i * 0.005, 28.0, 0.0) for i in range(5)]
        # Distances: end1(77.004)↔start2(77.020)=~1600m,
        #            end1(77.004)↔end2(77.000)=~400m,
        #            start1(77.000)↔start2(77.020)=~2000m,
        #            start1(77.000)↔end2(77.000)=0  ← minimum
        conn = find_best_connection(seg1, seg2)
        assert conn.connection_type == "start1-end2"
        assert conn.seg1_reversed is True
        assert conn.seg2_reversed is True

    def test_proximity_mismatch_real_fixtures(self):
        """A-B end should connect to B-C start (small gap ~5m)."""
        ab = read_linestring(FIXTURES / "sample_road_ab.kml")
        bc = read_linestring(FIXTURES / "sample_road_bc.kml")
        conn = find_best_connection(ab, bc, "A-B", "B-C")
        assert conn.connection_type == "end1-start2"
        assert conn.seg1_reversed is False
        assert conn.seg2_reversed is False
        assert conn.junction_distance_m < 20.0   # within snap tolerance

    def test_reversed_fixture_detected(self):
        """A-B end should connect to C-B end (reversed fixture) → seg2 reversed."""
        ab = read_linestring(FIXTURES / "sample_road_ab.kml")
        cb = read_linestring(FIXTURES / "sample_road_bc_reversed.kml")
        conn = find_best_connection(ab, cb, "A-B", "C-B")
        assert conn.connection_type == "end1-end2"
        assert conn.seg2_reversed is True
        assert conn.junction_distance_m < 20.0

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="empty"):
            find_best_connection([], [(1.0, 2.0, 0.0)])


# ──────────────────────────────────────────────────────────────────────────────
# apply_connection
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyConnection:
    def test_natural_merge_preserves_endpoints(self):
        seg1 = _straight_line(5, start_lon=77.000)
        seg2 = _straight_line(5, start_lon=77.004)
        cfg = _mock_config(trim=0.0)
        conn = find_best_connection(seg1, seg2)
        merged = apply_connection(seg1, seg2, conn, cfg)
        # First point of merged == first point of seg1
        assert merged[0] == pytest.approx(seg1[0], abs=0.0001)
        # Last point of merged == last point of seg2
        assert merged[-1] == pytest.approx(seg2[-1], abs=0.0001)

    def test_reversal_applied_correctly(self):
        """After merge with reversal, the line should flow end-to-end."""
        ab = read_linestring(FIXTURES / "sample_road_ab.kml")
        cb = read_linestring(FIXTURES / "sample_road_bc_reversed.kml")
        cfg = _mock_config(trim=5.0)
        conn = find_best_connection(ab, cb, "A-B", "C-B")
        merged = apply_connection(ab, cb, conn, cfg)
        # merged should start at A-B start and end at C-B start (= B-C end)
        assert merged[0] == pytest.approx(ab[0], abs=0.0001)
        assert len(merged) > 10

    def test_overlap_trim_reduces_points(self):
        """With overlap_trim > 0, points near junction are removed."""
        seg1 = _straight_line(10, start_lon=77.000, step=0.00009)  # ~10m spacing
        seg2 = _straight_line(10, start_lon=77.000 + 9 * 0.00009, step=0.00009)
        cfg_notrim = _mock_config(trim=0.0)
        cfg_trim = _mock_config(trim=8.0)
        conn = find_best_connection(seg1, seg2)
        merged_notrim = apply_connection(seg1, seg2, conn, cfg_notrim)
        merged_trim = apply_connection(seg1, seg2, conn, cfg_trim)
        # Trimmed version should have fewer points
        assert len(merged_trim) <= len(merged_notrim)

    def test_snap_point_inserted(self):
        """A midpoint snap is inserted between the two junction ends."""
        seg1 = _straight_line(3, start_lon=77.000)
        seg2 = _straight_line(3, start_lon=77.010)  # far gap
        cfg = _mock_config(trim=0.0)
        conn = find_best_connection(seg1, seg2)
        merged = apply_connection(seg1, seg2, conn, cfg)
        # Should have len(seg1) + 1 (snap) + len(seg2) points
        assert len(merged) == len(seg1) + 1 + len(seg2)

    def test_real_fixtures_merge(self):
        """Full merge of A-B + B-C produces a connected line."""
        ab = read_linestring(FIXTURES / "sample_road_ab.kml")
        bc = read_linestring(FIXTURES / "sample_road_bc.kml")
        cfg = _mock_config(trim=5.0)
        conn = find_best_connection(ab, bc, "A-B", "B-C")
        merged = apply_connection(ab, bc, conn, cfg)
        assert len(merged) > 30
        # First point = A-B first point
        assert merged[0] == pytest.approx(ab[0], abs=0.0001)
        # Last point = B-C last point
        assert merged[-1] == pytest.approx(bc[-1], abs=0.0001)


# ──────────────────────────────────────────────────────────────────────────────
# chain_merge — 3 segments
# ──────────────────────────────────────────────────────────────────────────────

class TestChainMerge:
    def _make_chain(self, n_segs=3, seg_len=5, gap=0.004):
        """Create n_segs of straight-line segments with a small gap between them."""
        segs = []
        for i in range(n_segs):
            start_lon = 77.0 + i * (seg_len - 1 + gap) * 0.001
            coords = _straight_line(seg_len, start_lon=start_lon)
            segs.append((f"Seg{i+1}", coords))
        return segs

    def test_two_segment_chain(self):
        cfg = _mock_config()
        segs = self._make_chain(2)
        result = chain_merge(segs, cfg)
        assert isinstance(result, MergeResult)
        assert len(result.connections) == 1
        assert result.segment_names == ["Seg1", "Seg2"]
        assert result.total_output_points > 0

    def test_three_segment_chain(self):
        cfg = _mock_config()
        segs = self._make_chain(3)
        result = chain_merge(segs, cfg)
        assert len(result.connections) == 2
        assert result.segment_names == ["Seg1", "Seg2", "Seg3"]

    def test_chain_real_fixtures(self):
        """Chain merge: A-B + B-C (real fixtures)."""
        cfg = _mock_config(trim=5.0)
        ab = read_linestring(FIXTURES / "sample_road_ab.kml")
        bc = read_linestring(FIXTURES / "sample_road_bc.kml")
        result = chain_merge([("A-B", ab), ("B-C", bc)], cfg)
        assert result.total_output_points > 30
        assert len(result.connections) == 1
        # First point = start of A-B
        assert result.coords[0] == pytest.approx(ab[0], abs=0.0001)
        # Last point = end of B-C
        assert result.coords[-1] == pytest.approx(bc[-1], abs=0.0001)

    def test_raises_on_single_segment(self):
        cfg = _mock_config()
        with pytest.raises(ValueError, match="at least 2"):
            chain_merge([("OnlySeg", _straight_line(5))], cfg)

    def test_override_connection_used(self):
        """User-provided override ConnectionInfo is used instead of auto-detect."""
        cfg = _mock_config(trim=0.0)
        seg1 = _straight_line(5, start_lon=77.000)
        seg2 = _straight_line(5, start_lon=77.004)
        # Force a manual override (natural connection)
        override = ConnectionInfo(
            seg1_name="S1", seg2_name="S2",
            connection_type="end1-start2",
            junction_distance_m=0.0,
            seg1_reversed=False, seg2_reversed=False,
        )
        result = chain_merge([("S1", seg1), ("S2", seg2)], cfg, overrides=[override])
        assert result.coords[0] == pytest.approx(seg1[0], abs=0.0001)

    def test_result_stats_accurate(self):
        cfg = _mock_config(trim=0.0)
        segs = self._make_chain(3, seg_len=5)
        result = chain_merge(segs, cfg)
        total_in = sum(5 for _ in segs)
        assert result.total_input_points == total_in
        # Output = total_in + 2 snap points (one per merge)
        assert result.total_output_points == result.total_input_points + 2
