"""
test_excel_reader.py — Unit + integration tests for core/excel_reader.py
"""

import pytest
import pandas as pd
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.excel_reader import (
    get_sheet_names, get_headers, auto_map_columns,
    validate_mapping, validate_data, extract_coordinates,
    ExcelReadError, ValidationIssue,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------
# get_sheet_names
# ------------------------------------------------------------------

class TestGetSheetNames:
    def test_detects_two_sheets(self):
        sheets = get_sheet_names(FIXTURES / "sample.xlsx")
        assert len(sheets) == 2
        assert "RoadSurvey" in sheets
        assert "AltNames" in sheets

    def test_raises_on_missing_file(self):
        with pytest.raises(ExcelReadError):
            get_sheet_names("/nonexistent/file.xlsx")


# ------------------------------------------------------------------
# get_headers
# ------------------------------------------------------------------

class TestGetHeaders:
    def test_standard_headers(self):
        headers = get_headers(FIXTURES / "sample.xlsx", "RoadSurvey")
        assert "StartLatitude" in headers
        assert "StartLongitude" in headers
        assert "StartAltitude" in headers
        assert "EndLatitude" in headers
        assert "EndLongitude" in headers
        assert "EndAltitude" in headers

    def test_alt_headers(self):
        headers = get_headers(FIXTURES / "sample.xlsx", "AltNames")
        assert "Lat_Start" in headers
        assert "Lon_Start" in headers


# ------------------------------------------------------------------
# auto_map_columns
# ------------------------------------------------------------------

class TestAutoMapColumns:
    def test_maps_standard_names(self):
        headers = ["StartLatitude", "StartLongitude", "StartAltitude",
                   "EndLatitude", "EndLongitude", "EndAltitude"]
        mapping = auto_map_columns(headers)
        assert mapping["start_lat"] == "StartLatitude"
        assert mapping["start_lon"] == "StartLongitude"
        assert mapping["start_alt"] == "StartAltitude"
        assert mapping["end_lat"] == "EndLatitude"
        assert mapping["end_lon"] == "EndLongitude"
        assert mapping["end_alt"] == "EndAltitude"

    def test_maps_alt_names(self):
        headers = ["Lat_Start", "Lon_Start", "Alt_Start", "Lat_End", "Lon_End", "Alt_End"]
        mapping = auto_map_columns(headers)
        assert mapping["start_lat"] == "Lat_Start"
        assert mapping["start_lon"] == "Lon_Start"

    def test_unknown_headers_return_empty(self):
        headers = ["Col_A", "Col_B", "Random"]
        mapping = auto_map_columns(headers)
        assert mapping == {}

    def test_partial_match(self):
        headers = ["StartLatitude", "StartLongitude", "SomeOtherCol"]
        mapping = auto_map_columns(headers)
        assert "start_lat" in mapping
        assert "start_lon" in mapping
        assert "start_alt" not in mapping

    def test_case_insensitive(self):
        headers = ["STARTLATITUDE", "startlongitude", "StartAltitude"]
        mapping = auto_map_columns(headers)
        assert "start_lat" in mapping
        assert "start_lon" in mapping


# ------------------------------------------------------------------
# validate_mapping
# ------------------------------------------------------------------

class TestValidateMapping:
    def test_complete_mapping_no_errors(self):
        mapping = {"start_lat": "Lat", "start_lon": "Lon"}
        assert validate_mapping(mapping) == []

    def test_missing_start_lat(self):
        mapping = {"start_lon": "Lon"}
        missing = validate_mapping(mapping)
        assert "start_lat" in missing

    def test_missing_both_required(self):
        missing = validate_mapping({})
        assert "start_lat" in missing
        assert "start_lon" in missing

    def test_optional_fields_not_required(self):
        mapping = {"start_lat": "Lat", "start_lon": "Lon"}
        # No end fields — should still be valid
        assert validate_mapping(mapping) == []


# ------------------------------------------------------------------
# validate_data
# ------------------------------------------------------------------

class TestValidateData:
    def test_valid_file_no_issues(self):
        mapping = auto_map_columns(get_headers(FIXTURES / "sample.xlsx", "RoadSurvey"))
        issues = validate_data(FIXTURES / "sample.xlsx", "RoadSurvey", mapping)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == []

    def test_bad_latitude_flagged(self, tmp_path):
        df = pd.DataFrame({
            "StartLatitude": [28.61, 999.0],   # 999 is invalid
            "StartLongitude": [77.209, 77.210],
            "StartAltitude": [220.0, 221.0],
        })
        bad_file = tmp_path / "bad.xlsx"
        df.to_excel(bad_file, index=False)
        mapping = auto_map_columns(list(df.columns))
        issues = validate_data(bad_file, "Sheet1", mapping)
        lat_errors = [i for i in issues if i.field == "start_lat" and i.severity == "error"]
        assert len(lat_errors) >= 1
        assert "999" in lat_errors[0].message or "out of range" in lat_errors[0].message

    def test_missing_value_flagged(self, tmp_path):
        df = pd.DataFrame({
            "StartLatitude": [28.61, None],
            "StartLongitude": [77.209, 77.210],
            "StartAltitude": [220.0, 221.0],
        })
        bad_file = tmp_path / "missing.xlsx"
        df.to_excel(bad_file, index=False)
        mapping = auto_map_columns(list(df.columns))
        issues = validate_data(bad_file, "Sheet1", mapping)
        missing = [i for i in issues if "Missing" in i.message]
        assert len(missing) >= 1

    def test_non_numeric_flagged(self, tmp_path):
        df = pd.DataFrame({
            "StartLatitude": [28.61, "NOT_A_NUMBER"],
            "StartLongitude": [77.209, 77.210],
            "StartAltitude": [220.0, 221.0],
        })
        bad_file = tmp_path / "nonnumeric.xlsx"
        df.to_excel(bad_file, index=False)
        mapping = auto_map_columns(list(df.columns))
        issues = validate_data(bad_file, "Sheet1", mapping)
        type_errors = [i for i in issues if "Non-numeric" in i.message]
        assert len(type_errors) >= 1


# ------------------------------------------------------------------
# extract_coordinates — integration tests
# ------------------------------------------------------------------

class TestExtractCoordinates:
    def test_extracts_correct_count(self):
        mapping = auto_map_columns(get_headers(FIXTURES / "sample.xlsx", "RoadSurvey"))
        coords = extract_coordinates(FIXTURES / "sample.xlsx", "RoadSurvey", mapping)
        # 10 start points + 1 end point from last row = 11
        assert len(coords) == 11

    def test_first_coord_correct(self):
        mapping = auto_map_columns(get_headers(FIXTURES / "sample.xlsx", "RoadSurvey"))
        coords = extract_coordinates(FIXTURES / "sample.xlsx", "RoadSurvey", mapping)
        # First coord: lon=77.209, lat=28.61, alt=220.0
        assert coords[0] == pytest.approx((77.209, 28.61, 220.0), abs=0.0001)

    def test_kml_order_lon_lat_alt(self):
        """Ensure output is (lon, lat, alt) — KML standard, not (lat, lon)."""
        mapping = auto_map_columns(get_headers(FIXTURES / "sample.xlsx", "RoadSurvey"))
        coords = extract_coordinates(FIXTURES / "sample.xlsx", "RoadSurvey", mapping)
        for lon, lat, alt in coords:
            assert 60.0 < lon < 100.0    # India longitude range
            assert 8.0 < lat < 40.0      # India latitude range

    def test_alt_names_sheet_works(self):
        mapping = auto_map_columns(get_headers(FIXTURES / "sample.xlsx", "AltNames"))
        coords = extract_coordinates(FIXTURES / "sample.xlsx", "AltNames", mapping)
        assert len(coords) >= 10

    def test_raises_if_required_fields_missing(self):
        with pytest.raises(ExcelReadError, match="Required fields"):
            extract_coordinates(FIXTURES / "sample.xlsx", "RoadSurvey", {})

    def test_skips_rows_with_missing_lat_lon(self, tmp_path):
        df = pd.DataFrame({
            "StartLatitude": [28.61, None, 28.62],
            "StartLongitude": [77.209, 77.210, 77.211],
            "StartAltitude": [220.0, 221.0, 222.0],
        })
        f = tmp_path / "partial.xlsx"
        df.to_excel(f, index=False)
        mapping = auto_map_columns(list(df.columns))
        coords = extract_coordinates(f, "Sheet1", mapping)
        assert len(coords) == 2   # skipped the None row
