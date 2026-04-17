"""
excel_reader.py — Excel → coordinate data pipeline for MKB-ROAD-KML.

Responsibilities:
  1. Detect sheets in a workbook
  2. Read column headers from a chosen sheet
  3. Auto-map headers to required logical fields (or accept a manual mapping)
  4. Validate rows: coordinate range, type, missing values
  5. Extract a list of (lon, lat, alt) coordinate tuples

Required logical fields:
  start_lat, start_lon, start_alt  (Start point of each segment)
  end_lat,   end_lon,   end_alt    (End point — last row only used for final point)

Altitude is optional — defaults to 0.0 if not mapped.

Public API:
    get_sheet_names(path)                    -> list[str]
    get_headers(path, sheet)                 -> list[str]
    auto_map_columns(headers)                -> dict[str, str]   field→column
    validate_mapping(mapping)                -> list[str]        missing required fields
    validate_data(df, mapping)               -> list[ValidationIssue]
    extract_coordinates(path, sheet, mapping) -> list[Coord]
    ExcelReadError                            (raised on unreadable file)
    ValidationIssue                           (dataclass: row, field, message)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from core.logger import get_logger
from core.kml_parser import Coord

log = get_logger(__name__)

# ------------------------------------------------------------------
# Required + optional logical fields
# ------------------------------------------------------------------

REQUIRED_FIELDS = ["start_lat", "start_lon"]
OPTIONAL_FIELDS = ["start_alt", "end_lat", "end_lon", "end_alt"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# Known column name aliases for auto-mapping (lowercase, stripped)
_ALIASES: dict[str, list[str]] = {
    "start_lat": ["startlatitude", "start_lat", "lat_start", "slat", "latitude_start",
                  "from_lat", "fromlat", "y_start", "lat1"],
    "start_lon": ["startlongitude", "start_lon", "lon_start", "slon", "longitude_start",
                  "from_lon", "fromlon", "x_start", "lon1", "lng_start"],
    "start_alt": ["startaltitude", "start_alt", "alt_start", "salt", "altitude_start",
                  "from_alt", "fromalt", "z_start", "elev_start", "elevation_start"],
    "end_lat":   ["endlatitude", "end_lat", "lat_end", "elat", "latitude_end",
                  "to_lat", "tolat", "y_end", "lat2"],
    "end_lon":   ["endlongitude", "end_lon", "lon_end", "elon", "longitude_end",
                  "to_lon", "tolon", "x_end", "lon2", "lng_end"],
    "end_alt":   ["endaltitude", "end_alt", "alt_end", "ealt", "altitude_end",
                  "to_alt", "toalt", "z_end", "elev_end", "elevation_end"],
}

# Coordinate validation bounds
_LAT_MIN, _LAT_MAX = -90.0, 90.0
_LON_MIN, _LON_MAX = -180.0, 180.0
_ALT_MIN, _ALT_MAX = -500.0, 9000.0  # below Dead Sea to above Everest


# ------------------------------------------------------------------
# Errors and data types
# ------------------------------------------------------------------

class ExcelReadError(Exception):
    """Raised when the Excel file cannot be read."""


@dataclass
class ValidationIssue:
    row: int          # 1-based Excel row number (header = row 1, data starts at row 2)
    field: str        # logical field name e.g. "start_lat"
    column: str       # Excel column name
    message: str      # human-readable description
    severity: str = "error"   # "error" | "warning"


# ------------------------------------------------------------------
# Sheet and header introspection
# ------------------------------------------------------------------

def get_sheet_names(path: str | Path) -> list[str]:
    """Return list of sheet names in the workbook."""
    path = Path(path)
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        return xl.sheet_names
    except Exception as exc:
        raise ExcelReadError(f"Cannot open Excel file '{path}': {exc}") from exc


def get_headers(path: str | Path, sheet: str) -> list[str]:
    """Return column header names from the first row of the given sheet."""
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name=sheet, nrows=0, engine="openpyxl")
        return list(df.columns)
    except Exception as exc:
        raise ExcelReadError(f"Cannot read headers from sheet '{sheet}': {exc}") from exc


# ------------------------------------------------------------------
# Column mapping
# ------------------------------------------------------------------

def auto_map_columns(headers: list[str]) -> dict[str, str]:
    """
    Attempt to map logical field names to actual Excel column names.
    Returns a dict: {field_name: column_name} for matched fields only.
    Unmatched fields are absent from the result.
    """
    mapping: dict[str, str] = {}
    normalised = {_normalise(h): h for h in headers}

    for field_name, aliases in _ALIASES.items():
        for alias in aliases:
            norm_alias = _normalise(alias)
            if norm_alias in normalised:
                mapping[field_name] = normalised[norm_alias]
                break

    matched = list(mapping.keys())
    missing = [f for f in ALL_FIELDS if f not in mapping]
    log.debug("Auto-map: matched=%s  missing=%s", matched, missing)
    return mapping


def validate_mapping(mapping: dict[str, str]) -> list[str]:
    """
    Check that all REQUIRED_FIELDS are present in the mapping.
    Returns list of missing required field names (empty = OK).
    """
    return [f for f in REQUIRED_FIELDS if f not in mapping]


# ------------------------------------------------------------------
# Data validation
# ------------------------------------------------------------------

def validate_data(
    path: str | Path,
    sheet: str,
    mapping: dict[str, str],
) -> list[ValidationIssue]:
    """
    Load the sheet and validate every row against the mapping.
    Returns a list of ValidationIssue (empty = all OK).
    """
    df = _load_sheet(path, sheet)
    issues: list[ValidationIssue] = []

    for field_name in ALL_FIELDS:
        if field_name not in mapping:
            continue
        col = mapping[field_name]
        if col not in df.columns:
            issues.append(ValidationIssue(
                row=0, field=field_name, column=col,
                message=f"Column '{col}' not found in sheet",
            ))
            continue

        is_optional = field_name in OPTIONAL_FIELDS
        is_alt = field_name.endswith("_alt")
        is_lat = field_name.endswith("_lat")
        is_lon = field_name.endswith("_lon")

        for idx, value in df[col].items():
            excel_row = idx + 2  # +1 for header, +1 for 1-based

            # Missing value check
            if pd.isna(value):
                severity = "warning" if is_optional else "error"
                issues.append(ValidationIssue(
                    row=excel_row, field=field_name, column=col,
                    message=f"Missing value in row {excel_row}",
                    severity=severity,
                ))
                continue

            # Type check
            try:
                fval = float(value)
            except (TypeError, ValueError):
                issues.append(ValidationIssue(
                    row=excel_row, field=field_name, column=col,
                    message=f"Non-numeric value '{value}' in row {excel_row}",
                ))
                continue

            # Range check
            if is_lat and not (_LAT_MIN <= fval <= _LAT_MAX):
                issues.append(ValidationIssue(
                    row=excel_row, field=field_name, column=col,
                    message=f"Latitude {fval} out of range [{_LAT_MIN}, {_LAT_MAX}] in row {excel_row}",
                ))
            elif is_lon and not (_LON_MIN <= fval <= _LON_MAX):
                issues.append(ValidationIssue(
                    row=excel_row, field=field_name, column=col,
                    message=f"Longitude {fval} out of range [{_LON_MIN}, {_LON_MAX}] in row {excel_row}",
                ))
            elif is_alt and not (_ALT_MIN <= fval <= _ALT_MAX):
                issues.append(ValidationIssue(
                    row=excel_row, field=field_name, column=col,
                    message=f"Altitude {fval} out of range [{_ALT_MIN}, {_ALT_MAX}] in row {excel_row}",
                    severity="warning",
                ))

    error_count = sum(1 for i in issues if i.severity == "error")
    warn_count = sum(1 for i in issues if i.severity == "warning")
    log.debug("Validation: %d errors, %d warnings across %d rows", error_count, warn_count, len(df))
    return issues


# ------------------------------------------------------------------
# Coordinate extraction
# ------------------------------------------------------------------

def extract_coordinates(
    path: str | Path,
    sheet: str,
    mapping: dict[str, str],
) -> list[Coord]:
    """
    Extract (lon, lat, alt) tuples from the mapped columns.

    Strategy:
      - Takes all Start points from every row
      - Appends the End point of the last row (for segment-based data)
      - If no end columns mapped, uses only Start points
      - Altitude defaults to 0.0 if not mapped

    Raises ExcelReadError if required columns are missing or unreadable.
    """
    missing = validate_mapping(mapping)
    if missing:
        raise ExcelReadError(f"Required fields not mapped: {missing}")

    df = _load_sheet(path, sheet)
    coords: list[Coord] = []

    lat_col = mapping["start_lat"]
    lon_col = mapping["start_lon"]
    alt_col = mapping.get("start_alt")

    for idx, row in df.iterrows():
        lat = _get_float(row, lat_col)
        lon = _get_float(row, lon_col)
        alt = _get_float(row, alt_col) if alt_col else 0.0
        if lat is None or lon is None:
            log.warning("Skipping row %d — missing lat/lon", idx + 2)
            continue
        coords.append((lon, lat, alt))

    # Append end point of last row if end columns are mapped
    end_lat_col = mapping.get("end_lat")
    end_lon_col = mapping.get("end_lon")
    end_alt_col = mapping.get("end_alt")

    if end_lat_col and end_lon_col and not df.empty:
        last_row = df.iloc[-1]
        elat = _get_float(last_row, end_lat_col)
        elon = _get_float(last_row, end_lon_col)
        ealt = _get_float(last_row, end_alt_col) if end_alt_col else 0.0
        if elat is not None and elon is not None:
            coords.append((elon, elat, ealt))

    log.info("Extracted %d coordinates from '%s' sheet '%s'", len(coords), path, sheet)
    return coords


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _normalise(s: str) -> str:
    """Lowercase and remove non-alphanumeric characters for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _load_sheet(path: str | Path, sheet: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    except Exception as exc:
        raise ExcelReadError(f"Cannot read sheet '{sheet}' from '{path}': {exc}") from exc


def _get_float(row: Any, col: str) -> float | None:
    """Safely extract a float from a DataFrame row. Returns None if missing/invalid."""
    val = row.get(col) if hasattr(row, "get") else row[col]
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
