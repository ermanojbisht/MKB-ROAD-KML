"""
kml_parser.py — Read and write KML files using lxml.

Coordinate format throughout this module:
    List of (longitude, latitude, altitude) tuples  — KML standard order.

Public API:
    read_linestring(path)           -> list[tuple[float,float,float]]
    detect_geometry_types(path)     -> set[str]  e.g. {"LineString", "Polygon"}
    write_kml(path, coords, placemarks, config)
    KMLParseError                   (raised on malformed or unexpected KML)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from core.logger import get_logger

log = get_logger(__name__)

# KML namespace
_NS = "http://www.opengis.net/kml/2.2"
_NSMAP = {"kml": _NS}

# Geometry tag names we recognise
_GEOMETRY_TAGS = {"LineString", "Polygon", "Point", "MultiGeometry"}


class KMLParseError(Exception):
    """Raised when a KML file cannot be parsed or has unexpected structure."""


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

Coord = tuple[float, float, float]  # (lon, lat, alt)


@dataclass
class ChainagePlacemark:
    """A single chainage marker to be written into a Placemark."""
    name: str          # e.g. "CH 0+100"
    lon: float
    lat: float
    alt: float


# ------------------------------------------------------------------
# Reading
# ------------------------------------------------------------------

def read_linestring(path: str | Path) -> list[Coord]:
    """
    Parse the first LineString found in a KML file.
    Returns a list of (lon, lat, alt) tuples.
    Raises KMLParseError on malformed XML or if no LineString is found.
    """
    path = Path(path)
    log.debug("Reading KML LineString from %s", path)

    root = _parse_xml(path)
    coords_el = root.find(f".//{{{_NS}}}LineString/{{{_NS}}}coordinates")
    if coords_el is None:
        raise KMLParseError(f"No <LineString><coordinates> found in {path}")

    coords = _parse_coord_text(coords_el.text or "", source=str(path))
    log.debug("Read %d coordinates from %s", len(coords), path)
    return coords


def read_kml_meta(path: str | Path) -> dict:
    """
    Read display metadata from a KML file.

    Returns a dict with keys:
        name           str   — Document/Placemark name
        description    str   — Document description
        line_color     str   — LineStyle color (AABBGGRR hex, e.g. "ff0000ff")
        line_width     int   — LineStyle width in pixels
        altitude_mode  str   — LineString altitudeMode
    """
    path = Path(path)
    root = _parse_xml(path)

    def _find_text(xpath: str, default: str) -> str:
        el = root.find(xpath)
        return (el.text or "").strip() if el is not None else default

    return {
        "name":          _find_text(f".//{{{_NS}}}Document/{{{_NS}}}name",        "Road Path"),
        "description":   _find_text(f".//{{{_NS}}}Document/{{{_NS}}}description", ""),
        "line_color":    _find_text(f".//{{{_NS}}}LineStyle/{{{_NS}}}color",       "ff0000ff"),
        "line_width":    int(float(_find_text(f".//{{{_NS}}}LineStyle/{{{_NS}}}width", "4") or "4")),
        "altitude_mode": _find_text(f".//{{{_NS}}}LineString/{{{_NS}}}altitudeMode", "relativeToGround"),
    }


def detect_geometry_types(path: str | Path) -> set[str]:
    """
    Scan a KML file and return the set of geometry type names found.
    E.g. {"LineString"}, {"LineString", "Point"}, {"Polygon"}.
    """
    path = Path(path)
    root = _parse_xml(path)
    found: set[str] = set()
    for tag in _GEOMETRY_TAGS:
        if root.find(f".//{{{_NS}}}{tag}") is not None:
            found.add(tag)
    return found


# ------------------------------------------------------------------
# Writing
# ------------------------------------------------------------------

def write_kml(
    path: str | Path,
    coords: list[Coord],
    placemarks: list[ChainagePlacemark] | None = None,
    *,
    name: str = "Road Path",
    line_color: str = "ff0000ff",
    line_width: int = 4,
    altitude_mode: str = "relativeToGround",
    description: str = "",
) -> None:
    """
    Write a KML file with:
      - A styled LineString Placemark for the road line
      - An optional sub-Folder of chainage Placemarks

    coords: list of (lon, lat, alt) tuples
    placemarks: chainage markers — written into a separate "Chainage" folder
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kml = etree.Element("kml", xmlns=_NS)
    doc = etree.SubElement(kml, "Document")
    etree.SubElement(doc, "name").text = name
    if description:
        etree.SubElement(doc, "description").text = description

    # Road line style
    style = etree.SubElement(doc, "Style", id="roadStyle")
    line_style = etree.SubElement(style, "LineStyle")
    etree.SubElement(line_style, "color").text = line_color
    etree.SubElement(line_style, "width").text = str(line_width)

    # Road LineString Placemark
    pm = etree.SubElement(doc, "Placemark")
    etree.SubElement(pm, "name").text = name
    etree.SubElement(pm, "styleUrl").text = "#roadStyle"
    ls = etree.SubElement(pm, "LineString")
    etree.SubElement(ls, "extrude").text = "1"
    etree.SubElement(ls, "tessellate").text = "1"
    etree.SubElement(ls, "altitudeMode").text = altitude_mode
    etree.SubElement(ls, "coordinates").text = _format_coords(coords)

    # Chainage markers folder (separate, toggleable in Google Earth)
    if placemarks:
        folder = etree.SubElement(doc, "Folder")
        etree.SubElement(folder, "name").text = "Chainage"
        etree.SubElement(folder, "visibility").text = "1"

        # Chainage pin style
        ch_style = etree.SubElement(doc, "Style", id="chainageStyle")
        icon_style = etree.SubElement(ch_style, "IconStyle")
        etree.SubElement(icon_style, "scale").text = "0.7"
        icon = etree.SubElement(icon_style, "Icon")
        etree.SubElement(icon, "href").text = (
            "http://maps.google.com/mapfiles/kml/paddle/wht-blank.png"
        )
        label_style = etree.SubElement(ch_style, "LabelStyle")
        etree.SubElement(label_style, "scale").text = "0.7"

        for cp in placemarks:
            cpm = etree.SubElement(folder, "Placemark")
            etree.SubElement(cpm, "name").text = cp.name
            etree.SubElement(cpm, "styleUrl").text = "#chainageStyle"
            pt = etree.SubElement(cpm, "Point")
            etree.SubElement(pt, "altitudeMode").text = altitude_mode
            etree.SubElement(pt, "coordinates").text = f"{cp.lon},{cp.lat},{cp.alt}"

    tree = etree.ElementTree(kml)
    tree.write(str(path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
    log.info("KML written to %s (%d coords, %d chainage markers)",
             path, len(coords), len(placemarks) if placemarks else 0)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _parse_xml(path: Path) -> etree._Element:
    try:
        tree = etree.parse(str(path))
        return tree.getroot()
    except etree.XMLSyntaxError as exc:
        raise KMLParseError(f"Malformed XML in {path}: {exc}") from exc


def _parse_coord_text(text: str, source: str = "") -> list[Coord]:
    """Parse a KML coordinate string into a list of (lon, lat, alt) tuples."""
    coords: list[Coord] = []
    for token in text.split():
        token = token.strip()
        if not token:
            continue
        parts = token.split(",")
        if len(parts) < 2:
            raise KMLParseError(f"Invalid coordinate token '{token}' in {source}")
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
        except ValueError as exc:
            raise KMLParseError(f"Non-numeric coordinate '{token}' in {source}") from exc
        coords.append((lon, lat, alt))
    if not coords:
        raise KMLParseError(f"Empty coordinates in {source}")
    return coords


def _format_coords(coords: list[Coord]) -> str:
    """Format (lon, lat, alt) list into a KML coordinate string."""
    return " ".join(f"{lon},{lat},{alt}" for lon, lat, alt in coords)
