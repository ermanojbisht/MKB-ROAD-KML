"""
geometry.py — Core geometry engine for MKB-ROAD-KML.

All functions work with coordinates as (lon, lat, alt) tuples — KML standard.
All distance computations use the Haversine formula (geodesic, metres).

Public API:
    haversine_m(c1, c2)             -> float  (metres)
    simplify(coords, config)        -> list[Coord]
    densify(coords, config)         -> list[Coord]
    compute_chainage(coords, config) -> list[ChainagePlacemark]
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from core.logger import get_logger
from core.kml_parser import ChainagePlacemark, Coord

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

log = get_logger(__name__)

_EARTH_RADIUS_M = 6_371_000.0


# ------------------------------------------------------------------
# Geodesic distance
# ------------------------------------------------------------------

def haversine_m(c1: Coord, c2: Coord) -> float:
    """
    Return the geodesic distance in metres between two (lon, lat, alt) coords.
    Altitude is ignored — horizontal distance only.
    """
    lon1, lat1, _ = c1
    lon2, lat2, _ = c2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ------------------------------------------------------------------
# Simplify — Ramer-Douglas-Peucker + min-distance pre-filter
# ------------------------------------------------------------------

def simplify(coords: list[Coord], config: "ConfigManager") -> list[Coord]:
    """
    Simplify a LineString.

    Steps:
      1. Min-distance pre-filter: remove consecutive points closer than
         min_distance_meters, keeping the first and last point always.
      2. RDP: further reduce redundant collinear points using the
         Ramer-Douglas-Peucker algorithm with rdp_epsilon (in degrees,
         angular tolerance — avoids coordinate-unit conversions in RDP).

    Returns simplified list of (lon, lat, alt) coords.
    """
    if len(coords) < 3:
        return list(coords)

    min_dist = config.get("simplify", "min_distance_meters", 5.0)
    rdp_eps = config.get("simplify", "rdp_epsilon", 0.00001)

    # Step 1: min-distance filter
    filtered = _min_distance_filter(coords, min_dist)
    log.debug("Simplify: %d → %d points after min-distance filter (%.1fm)",
              len(coords), len(filtered), min_dist)

    if len(filtered) < 3:
        return filtered

    # Step 2: RDP
    result = _rdp(filtered, rdp_eps)
    log.debug("Simplify: %d → %d points after RDP (eps=%.6f)",
              len(filtered), len(result), rdp_eps)
    return result


def _min_distance_filter(coords: list[Coord], min_dist_m: float) -> list[Coord]:
    """Keep a point only if it is >= min_dist_m from the last kept point."""
    if not coords:
        return []
    kept = [coords[0]]
    for pt in coords[1:-1]:
        if haversine_m(kept[-1], pt) >= min_dist_m:
            kept.append(pt)
    kept.append(coords[-1])  # always keep last point
    return kept


def _rdp(coords: list[Coord], epsilon: float) -> list[Coord]:
    """
    Ramer-Douglas-Peucker algorithm.
    epsilon is the perpendicular distance tolerance in degrees
    (works in lon/lat space — acceptable for road-scale data).
    """
    if len(coords) < 3:
        return list(coords)

    # Find the point with the maximum perpendicular distance from the line
    # between the first and last point
    start, end = coords[0], coords[-1]
    max_dist = 0.0
    max_idx = 0

    for i in range(1, len(coords) - 1):
        dist = _perp_distance_deg(coords[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > epsilon:
        # Recursively simplify both halves
        left = _rdp(coords[: max_idx + 1], epsilon)
        right = _rdp(coords[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [start, end]


def _perp_distance_deg(point: Coord, line_start: Coord, line_end: Coord) -> float:
    """
    Perpendicular distance from point to line (start→end) in degree-space.
    Sufficient for RDP on road-scale geographic data.
    """
    x0, y0 = point[0], point[1]
    x1, y1 = line_start[0], line_start[1]
    x2, y2 = line_end[0], line_end[1]

    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x0 - x1, y0 - y1)

    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return math.hypot(x0 - px, y0 - py)


# ------------------------------------------------------------------
# Densify — geodesic interpolation
# ------------------------------------------------------------------

def densify(coords: list[Coord], config: "ConfigManager") -> list[Coord]:
    """
    Add interpolated points between consecutive coordinates where the gap
    exceeds max_distance_meters. Interpolation is linear in lon/lat/alt space
    (acceptable for road-scale segments).

    Returns densified list of (lon, lat, alt) coords.
    """
    if len(coords) < 2:
        return list(coords)

    max_dist = config.get("densify", "max_distance_meters", 10.0)
    result: list[Coord] = [coords[0]]

    for i in range(1, len(coords)):
        p1, p2 = coords[i - 1], coords[i]
        gap = haversine_m(p1, p2)

        if gap > max_dist:
            n_segments = math.ceil(gap / max_dist)
            for j in range(1, n_segments):
                t = j / n_segments
                interp = _lerp(p1, p2, t)
                result.append(interp)

        result.append(p2)

    original_count = len(coords)
    log.debug("Densify: %d → %d points (max gap %.1fm)",
              original_count, len(result), max_dist)
    return result


def _lerp(p1: Coord, p2: Coord, t: float) -> Coord:
    """Linear interpolation between two coords at parameter t ∈ [0, 1]."""
    return (
        p1[0] + t * (p2[0] - p1[0]),
        p1[1] + t * (p2[1] - p1[1]),
        p1[2] + t * (p2[2] - p1[2]),
    )


# ------------------------------------------------------------------
# Chainage — cumulative distance markers
# ------------------------------------------------------------------

def compute_chainage(
    coords: list[Coord],
    config: "ConfigManager",
) -> list[ChainagePlacemark]:
    """
    Compute chainage markers along the line.

    Places a ChainagePlacemark:
      - At every interval_meters (default 100m) along the cumulative distance
      - At detected bend points (bearing change > bend_threshold_deg, default 15°)

    Label format: CH {km}+{m:03d}  e.g. "CH 1+050"
    start_chainage offsets the zero point (e.g. start_chainage=500 means the
    first point is already at CH 0+500).

    Returns a list of ChainagePlacemark objects.
    """
    if len(coords) < 2:
        return []

    interval = config.get("chainage", "interval_meters", 100)
    label_fmt = config.get("chainage", "label_format", "CH {km}+{m}")
    start_ch = config.get("chainage", "start_chainage", 0)
    bend_threshold = config.get("chainage", "bend_threshold_deg", 15.0)

    markers: list[ChainagePlacemark] = []
    cumulative = 0.0
    next_marker_dist = interval - (start_ch % interval) if start_ch % interval else interval
    # place marker at 0 if start_chainage is exactly on an interval boundary
    if start_ch % interval == 0:
        markers.append(_make_marker(coords[0], start_ch, label_fmt))
        next_marker_dist = interval

    for i in range(1, len(coords)):
        p1, p2 = coords[i - 1], coords[i]
        seg_len = haversine_m(p1, p2)

        # Walk along this segment, placing interval markers
        seg_walked = 0.0
        while seg_walked + (next_marker_dist - cumulative % interval
                            if cumulative % interval else next_marker_dist) <= seg_len:
            remaining = next_marker_dist - (cumulative - (cumulative // interval) * interval) \
                if cumulative > 0 else next_marker_dist
            # Simpler: track distance to next marker directly
            break  # handled below via cumulative approach

        cumulative += seg_len

        # Place all interval markers that fall within [prev_cumulative, cumulative]
        prev_cumul = cumulative - seg_len
        dist = next_marker_dist
        while dist <= cumulative:
            t = (dist - prev_cumul) / seg_len if seg_len > 0 else 0.0
            t = max(0.0, min(1.0, t))
            pt = _lerp(p1, p2, t)
            ch_val = start_ch + dist
            markers.append(_make_marker(pt, ch_val, label_fmt))
            dist += interval
        next_marker_dist = dist  # carry forward

        # Bend point detection (bearing change between consecutive segments)
        if i < len(coords) - 1:
            p3 = coords[i + 1]
            bearing1 = _bearing(p1, p2)
            bearing2 = _bearing(p2, p3)
            delta = abs(bearing2 - bearing1)
            if delta > 180:
                delta = 360 - delta
            if delta >= bend_threshold:
                ch_val = start_ch + cumulative
                # Avoid duplicate if very close to an interval marker
                if not markers or haversine_m(
                        (markers[-1].lon, markers[-1].lat, markers[-1].alt), p2
                ) > interval * 0.1:
                    markers.append(_make_marker(p2, ch_val, label_fmt))

    log.debug("Chainage: %d markers for %d coord line", len(markers), len(coords))
    return markers


def _make_marker(pt: Coord, distance_m: float, label_fmt: str) -> ChainagePlacemark:
    """Create a ChainagePlacemark at the given point and cumulative distance."""
    total_m = int(round(distance_m))
    km = total_m // 1000
    m = total_m % 1000
    name = label_fmt.format(km=km, m=f"{m:03d}")
    return ChainagePlacemark(name=name, lon=pt[0], lat=pt[1], alt=pt[2])


def _bearing(p1: Coord, p2: Coord) -> float:
    """Compute the compass bearing in degrees from p1 to p2."""
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
