"""
test_kml_parser.py — Unit tests for core/kml_parser.py

Tests: read coords, round-trip, Placemark folder write,
       malformed XML error, polygon detection.
"""

import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.kml_parser import (
    read_linestring, detect_geometry_types, write_kml,
    KMLParseError, ChainagePlacemark,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestReadLinestring:
    def test_reads_sample_ab(self):
        coords = read_linestring(FIXTURES / "sample_road_ab.kml")
        assert len(coords) == 20
        # First point
        assert coords[0] == pytest.approx((77.209, 28.61, 220.0), abs=0.0001)

    def test_reads_sample_bc(self):
        coords = read_linestring(FIXTURES / "sample_road_bc.kml")
        assert len(coords) == 20

    def test_raises_on_polygon_kml(self):
        with pytest.raises(KMLParseError, match="No <LineString>"):
            read_linestring(FIXTURES / "sample_polygon.kml")

    def test_raises_on_malformed_xml(self):
        with tempfile.NamedTemporaryFile(suffix=".kml", mode="w", delete=False) as f:
            f.write("<kml><broken")
            bad_path = f.name
        with pytest.raises(KMLParseError, match="Malformed XML"):
            read_linestring(bad_path)

    def test_raises_on_missing_file(self):
        with pytest.raises(Exception):
            read_linestring("/nonexistent/path/road.kml")


class TestDetectGeometryTypes:
    def test_linestring_detected(self):
        types = detect_geometry_types(FIXTURES / "sample_road_ab.kml")
        assert "LineString" in types
        assert "Polygon" not in types

    def test_polygon_detected(self):
        types = detect_geometry_types(FIXTURES / "sample_polygon.kml")
        assert "Polygon" in types
        assert "LineString" not in types


class TestWriteKml:
    def test_write_and_read_back(self, tmp_path):
        coords = [
            (77.209, 28.610, 220.0),
            (77.210, 28.615, 221.0),
            (77.211, 28.620, 222.0),
        ]
        out = tmp_path / "test_out.kml"
        write_kml(out, coords)
        result = read_linestring(out)
        assert len(result) == 3
        assert result[0] == pytest.approx(coords[0], abs=0.00001)
        assert result[-1] == pytest.approx(coords[-1], abs=0.00001)

    def test_write_with_chainage_placemarks(self, tmp_path):
        coords = [(77.209, 28.610, 220.0), (77.215, 28.615, 225.0)]
        placemarks = [
            ChainagePlacemark(name="CH 0+100", lon=77.211, lat=28.612, alt=221.0),
            ChainagePlacemark(name="CH 0+200", lon=77.213, lat=28.613, alt=222.0),
        ]
        out = tmp_path / "with_chainage.kml"
        write_kml(out, coords, placemarks=placemarks)
        content = out.read_text()
        assert "Chainage" in content
        assert "CH 0+100" in content
        assert "CH 0+200" in content

    def test_output_is_valid_xml(self, tmp_path):
        from lxml import etree
        coords = [(77.0, 28.0, 0.0), (77.1, 28.1, 0.0)]
        out = tmp_path / "valid.kml"
        write_kml(out, coords)
        tree = etree.parse(str(out))
        assert tree is not None

    def test_creates_parent_directories(self, tmp_path):
        coords = [(77.0, 28.0, 0.0), (77.1, 28.1, 0.0)]
        out = tmp_path / "subdir" / "deep" / "out.kml"
        write_kml(out, coords)
        assert out.exists()

    def test_line_color_in_output(self, tmp_path):
        coords = [(77.0, 28.0, 0.0), (77.1, 28.1, 0.0)]
        out = tmp_path / "color.kml"
        write_kml(out, coords, line_color="ff00ff00")
        assert "ff00ff00" in out.read_text()
