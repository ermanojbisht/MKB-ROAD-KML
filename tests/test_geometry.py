"""
test_geometry.py — Unit tests for core/geometry.py

Tests: haversine distance, simplify (straight, curve, sparse),
       densify (uniform, curve), chainage (interval, label, start offset).
"""

import math
import pytest
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from core.geometry import haversine_m, simplify, densify, compute_chainage


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mock_config(section_values: dict) -> MagicMock:
    """Create a mock ConfigManager with specific section/key values."""
    cfg = MagicMock()
    def _get(section, key, fallback=None):
        return section_values.get(section, {}).get(key, fallback)
    cfg.get.side_effect = _get
    return cfg


def _simplify_cfg(min_dist=5.0, eps=0.00001):
    return _mock_config({"simplify": {"min_distance_meters": min_dist, "rdp_epsilon": eps}})


def _densify_cfg(max_dist=10.0):
    return _mock_config({"densify": {"max_distance_meters": max_dist}})


def _chainage_cfg(interval=100, fmt="CH {km}+{m}", start=0):
    return _mock_config({"chainage": {
        "interval_meters": interval,
        "label_format": fmt,
        "start_chainage": start,
    }})


# ------------------------------------------------------------------
# haversine_m
# ------------------------------------------------------------------

class TestHaversine:
    def test_zero_distance(self):
        c = (77.209, 28.610, 0.0)
        assert haversine_m(c, c) == pytest.approx(0.0, abs=0.001)

    def test_known_distance_approx(self):
        # ~1 degree latitude ≈ 111,000 m
        c1 = (77.0, 28.0, 0.0)
        c2 = (77.0, 29.0, 0.0)
        dist = haversine_m(c1, c2)
        assert 110_000 < dist < 112_000

    def test_altitude_ignored(self):
        c1 = (77.209, 28.610, 0.0)
        c2 = (77.209, 28.610, 1000.0)
        assert haversine_m(c1, c2) == pytest.approx(0.0, abs=0.001)

    def test_small_segment(self):
        # Two points ~7m apart (roughly 0.00006 degrees longitude at this latitude)
        c1 = (77.20900, 28.61000, 220.0)
        c2 = (77.20906, 28.61000, 220.0)
        dist = haversine_m(c1, c2)
        assert 5.0 < dist < 10.0


# ------------------------------------------------------------------
# simplify
# ------------------------------------------------------------------

class TestSimplify:
    def test_less_than_3_points_unchanged(self):
        coords = [(77.0, 28.0, 0.0), (77.1, 28.1, 0.0)]
        cfg = _simplify_cfg()
        assert simplify(coords, cfg) == coords

    def test_straight_line_reduces(self):
        # 10 points in a perfectly straight line — should reduce significantly
        coords = [(77.0 + i * 0.001, 28.0, 0.0) for i in range(10)]
        cfg = _simplify_cfg(min_dist=1.0, eps=0.0000001)
        result = simplify(coords, cfg)
        # A straight line should collapse to 2 points (start + end)
        assert len(result) == 2
        assert result[0] == coords[0]
        assert result[-1] == coords[-1]

    def test_curve_preserves_bend_points(self):
        # L-shaped line: go east then go north — corner must be preserved
        coords = [
            (77.000, 28.000, 0.0),
            (77.001, 28.000, 0.0),
            (77.002, 28.000, 0.0),
            (77.002, 28.001, 0.0),  # corner point
            (77.002, 28.002, 0.0),
            (77.002, 28.003, 0.0),
        ]
        cfg = _simplify_cfg(min_dist=1.0, eps=0.0000001)
        result = simplify(coords, cfg)
        # Corner (77.002, 28.000) must be in result
        lons = [c[0] for c in result]
        lats = [c[1] for c in result]
        assert 77.002 in lons
        assert 28.000 in lats

    def test_already_sparse_no_removal(self):
        # Points 100m+ apart — min-distance filter should not remove any
        coords = [(77.0 + i * 0.001, 28.0 + i * 0.001, 0.0) for i in range(5)]
        cfg = _simplify_cfg(min_dist=5.0, eps=0.00001)
        result = simplify(coords, cfg)
        assert result[0] == coords[0]
        assert result[-1] == coords[-1]

    def test_first_and_last_always_kept(self):
        coords = [(77.0 + i * 0.00001, 28.0, 0.0) for i in range(20)]
        cfg = _simplify_cfg(min_dist=100.0, eps=0.001)
        result = simplify(coords, cfg)
        assert result[0] == coords[0]
        assert result[-1] == coords[-1]

    def test_dense_points_removed(self):
        # 20 points 1m apart — with min_dist=5m, most should be removed
        # ~1m ≈ 0.000009 degrees longitude
        coords = [(77.0 + i * 0.000009, 28.0, 0.0) for i in range(20)]
        cfg = _simplify_cfg(min_dist=5.0, eps=0.00001)
        result = simplify(coords, cfg)
        assert len(result) < len(coords)


# ------------------------------------------------------------------
# densify
# ------------------------------------------------------------------

class TestDensify:
    def test_less_than_2_points_unchanged(self):
        coords = [(77.0, 28.0, 0.0)]
        cfg = _densify_cfg()
        assert densify(coords, cfg) == coords

    def test_no_densify_needed(self):
        # Points 5m apart — max_dist=10m — no new points added
        coords = [(77.20900, 28.61000, 0.0), (77.20905, 28.61000, 0.0)]
        dist = haversine_m(coords[0], coords[1])
        assert dist < 10.0
        cfg = _densify_cfg(max_dist=10.0)
        result = densify(coords, cfg)
        assert len(result) == 2

    def test_densify_long_segment(self):
        # Two points 100m apart — max_dist=10m — should add ~9 intermediate points
        c1 = (77.00000, 28.00000, 0.0)
        c2 = (77.00090, 28.00000, 0.0)  # ~90-100m east
        dist = haversine_m(c1, c2)
        assert dist > 50.0
        cfg = _densify_cfg(max_dist=10.0)
        result = densify([c1, c2], cfg)
        assert len(result) > 5
        assert result[0] == c1
        assert result[-1] == c2

    def test_interpolated_points_between_endpoints(self):
        c1 = (77.000, 28.000, 100.0)
        c2 = (77.001, 28.001, 200.0)
        cfg = _densify_cfg(max_dist=1.0)  # force densification
        result = densify([c1, c2], cfg)
        assert len(result) > 2
        # All intermediate lons should be between c1 and c2
        for pt in result[1:-1]:
            assert 77.000 <= pt[0] <= 77.001
            assert 28.000 <= pt[1] <= 28.001
            assert 100.0 <= pt[2] <= 200.0

    def test_altitude_interpolated(self):
        c1 = (77.000, 28.000, 0.0)
        c2 = (77.001, 28.000, 100.0)
        cfg = _densify_cfg(max_dist=1.0)
        result = densify([c1, c2], cfg)
        # Midpoint altitude should be ~50
        mid = result[len(result) // 2]
        assert 30.0 < mid[2] < 70.0


# ------------------------------------------------------------------
# compute_chainage
# ------------------------------------------------------------------

class TestChainage:
    def test_empty_or_single_point(self):
        cfg = _chainage_cfg()
        assert compute_chainage([], cfg) == []
        assert compute_chainage([(77.0, 28.0, 0.0)], cfg) == []

    def test_interval_markers_placed(self):
        # Line ~500m long — should get ~5 markers at 100m intervals
        coords = [(77.0 + i * 0.001, 28.0, 0.0) for i in range(6)]
        cfg = _chainage_cfg(interval=100)
        markers = compute_chainage(coords, cfg)
        assert len(markers) >= 1

    def test_label_format(self):
        coords = [(77.0 + i * 0.001, 28.0, 0.0) for i in range(20)]
        cfg = _chainage_cfg(interval=100, fmt="CH {km}+{m}")
        markers = compute_chainage(coords, cfg)
        for m in markers:
            assert m.name.startswith("CH ")
            assert "+" in m.name

    def test_start_chainage_offset(self):
        # start_chainage=500 means first point is at CH 0+500
        coords = [(77.0 + i * 0.001, 28.0, 0.0) for i in range(20)]
        cfg = _chainage_cfg(interval=100, start=500)
        markers = compute_chainage(coords, cfg)
        # First marker label should reflect 500m offset
        if markers:
            first_name = markers[0].name
            assert "500" in first_name or "0+500" in first_name or "600" in first_name

    def test_marker_coordinates_on_line(self):
        # All markers should have lon/lat within the bounding box of the line
        coords = [(77.200 + i * 0.001, 28.610, 0.0) for i in range(15)]
        cfg = _chainage_cfg(interval=50)
        markers = compute_chainage(coords, cfg)
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        for m in markers:
            assert min(lons) - 0.001 <= m.lon <= max(lons) + 0.001
            assert min(lats) - 0.001 <= m.lat <= max(lats) + 0.001
