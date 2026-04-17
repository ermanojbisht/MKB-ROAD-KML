"""
merger.py — KML segment merge engine for MKB-ROAD-KML.

Solves three real-world stitching problems:
  1. Endpoint proximity mismatch  — B in seg1 ≠ B in seg2 (within snap_tolerance)
  2. Direction reversal           — segment stored in wrong direction
  3. Overlap at junction          — trailing/leading points too close to snap point

Public API:
    find_best_connection(coords1, coords2)     -> ConnectionInfo
    apply_connection(coords1, coords2, conn, config) -> list[Coord]
    chain_merge(segments, config)              -> MergeResult
    reverse_coords(coords)                     -> list[Coord]

Data types:
    ConnectionInfo   — describes how two segments connect
    MergeResult      — final merged coords + per-pair connection details
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.geometry import haversine_m
from core.kml_parser import Coord
from core.logger import get_logger

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ConnectionInfo:
    """
    Describes how two segments (1 and 2) should be connected.

    After applying seg1_reversed / seg2_reversed the rule is always:
        corrected_seg1[-1]  →  corrected_seg2[0]

    connection_type encodes which raw endpoints were closest:
        "end1-start2"    natural order, no reversal
        "end1-end2"      seg2 must be reversed
        "start1-start2"  seg1 must be reversed
        "start1-end2"    both must be reversed
    """
    seg1_name: str
    seg2_name: str
    connection_type: str
    junction_distance_m: float
    seg1_reversed: bool
    seg2_reversed: bool

    @property
    def description(self) -> str:
        parts = []
        if self.seg1_reversed:
            parts.append(f"'{self.seg1_name}' reversed")
        if self.seg2_reversed:
            parts.append(f"'{self.seg2_name}' reversed")
        if not parts:
            parts.append("no reversal needed")
        return f"Junction gap: {self.junction_distance_m:.1f}m  |  {', '.join(parts)}"


@dataclass
class MergeResult:
    """Result of a chain merge operation."""
    coords: list[Coord]
    connections: list[ConnectionInfo]        # one per pair merged
    segment_names: list[str]                 # ordered names used
    total_input_points: int
    total_output_points: int

    @property
    def point_delta(self) -> int:
        return self.total_output_points - self.total_input_points


# ──────────────────────────────────────────────────────────────────────────────
# Core operations
# ──────────────────────────────────────────────────────────────────────────────

def reverse_coords(coords: list[Coord]) -> list[Coord]:
    """Return a reversed copy of a coordinate list."""
    return list(reversed(coords))


def find_best_connection(
    coords1: list[Coord],
    coords2: list[Coord],
    name1: str = "Segment 1",
    name2: str = "Segment 2",
) -> ConnectionInfo:
    """
    Compute all 4 endpoint distances and return the ConnectionInfo
    describing the best (minimum distance) connection.

    Distances checked:
        end1   ↔ start2   →  "end1-start2"   (natural, no reversal)
        end1   ↔ end2     →  "end1-end2"     (reverse seg2)
        start1 ↔ start2   →  "start1-start2" (reverse seg1)
        start1 ↔ end2     →  "start1-end2"   (reverse both)
    """
    if not coords1 or not coords2:
        raise ValueError("Cannot merge empty coordinate lists")

    s1, e1 = coords1[0], coords1[-1]
    s2, e2 = coords2[0], coords2[-1]

    candidates: list[tuple[float, str, bool, bool]] = [
        (haversine_m(e1, s2), "end1-start2",   False, False),
        (haversine_m(e1, e2), "end1-end2",     False, True),
        (haversine_m(s1, s2), "start1-start2", True,  False),
        (haversine_m(s1, e2), "start1-end2",   True,  True),
    ]

    best = min(candidates, key=lambda x: x[0])
    dist, ctype, rev1, rev2 = best

    conn = ConnectionInfo(
        seg1_name=name1,
        seg2_name=name2,
        connection_type=ctype,
        junction_distance_m=dist,
        seg1_reversed=rev1,
        seg2_reversed=rev2,
    )
    log.debug(
        "Best connection %s ↔ %s: %s (gap=%.1fm, rev1=%s, rev2=%s)",
        name1, name2, ctype, dist, rev1, rev2
    )
    return conn


def apply_connection(
    coords1: list[Coord],
    coords2: list[Coord],
    conn: ConnectionInfo,
    config: "ConfigManager",
) -> list[Coord]:
    """
    Apply a ConnectionInfo to produce a merged coordinate list.

    Steps:
      1. Reverse segments as indicated by conn
      2. Trim overlap: remove trailing points of seg1 and leading points of seg2
         that lie within overlap_trim_meters of the junction
      3. Insert a snap point at the midpoint if junction gap > 0
      4. Concatenate
    """
    trim_dist = config.get("merge", "overlap_trim_meters", 5.0)

    c1 = reverse_coords(coords1) if conn.seg1_reversed else list(coords1)
    c2 = reverse_coords(coords2) if conn.seg2_reversed else list(coords2)

    c1, c2 = _trim_overlap(c1, c2, trim_dist)

    # Snap point: midpoint between the two junction ends (smooths the join)
    snap = _midpoint(c1[-1], c2[0])
    merged = c1 + [snap] + c2

    log.debug(
        "Merged %s + %s: %d + %d → %d points (trim=%.1fm)",
        conn.seg1_name, conn.seg2_name, len(coords1), len(coords2), len(merged), trim_dist
    )
    return merged


def chain_merge(
    segments: list[tuple[str, list[Coord]]],
    config: "ConfigManager",
    overrides: list[ConnectionInfo] | None = None,
) -> MergeResult:
    """
    Merge a list of (name, coords) pairs sequentially.

    segments: ordered list of (name, coords) — e.g. [("A-B", [...]), ("B-C", [...]), ("C-D", [...])]
    overrides: optional per-pair ConnectionInfo list (from user manual adjustments).
               Length must be len(segments) - 1 if provided.

    Returns a MergeResult with the fully merged coords and all ConnectionInfo records.
    """
    if len(segments) < 2:
        raise ValueError("Need at least 2 segments to merge")

    total_input = sum(len(c) for _, c in segments)
    connections: list[ConnectionInfo] = []
    names: list[str] = [s[0] for s in segments]

    # Start with the first segment
    current_name, current_coords = segments[0]

    for i in range(1, len(segments)):
        next_name, next_coords = segments[i]

        if overrides and i - 1 < len(overrides):
            conn = overrides[i - 1]
        else:
            conn = find_best_connection(current_coords, next_coords, current_name, next_name)

        connections.append(conn)
        current_coords = apply_connection(current_coords, next_coords, conn, config)
        current_name = f"{current_name}+{next_name}"

    return MergeResult(
        coords=current_coords,
        connections=connections,
        segment_names=names,
        total_input_points=total_input,
        total_output_points=len(current_coords),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _trim_overlap(
    coords1: list[Coord],
    coords2: list[Coord],
    trim_dist_m: float,
) -> tuple[list[Coord], list[Coord]]:
    """
    Remove trailing points of coords1 and leading points of coords2
    that are within trim_dist_m of the junction point.

    Always preserves at least 1 point in each list.
    """
    # Trim from end of coords1: walk backward, remove points within trim_dist of coords2[0]
    c1 = list(coords1)
    junction2 = coords2[0]
    while len(c1) > 1 and haversine_m(c1[-1], junction2) <= trim_dist_m:
        c1.pop()

    # Trim from start of coords2: walk forward, remove points within trim_dist of (new) c1[-1]
    c2 = list(coords2)
    junction1 = c1[-1]
    while len(c2) > 1 and haversine_m(junction1, c2[0]) <= trim_dist_m:
        c2.pop(0)

    trimmed1 = len(coords1) - len(c1)
    trimmed2 = len(coords2) - len(c2)
    if trimmed1 or trimmed2:
        log.debug("Overlap trim: removed %d from seg1 tail, %d from seg2 head", trimmed1, trimmed2)

    return c1, c2


def _midpoint(p1: Coord, p2: Coord) -> Coord:
    """Return the midpoint between two coordinates."""
    return (
        (p1[0] + p2[0]) / 2,
        (p1[1] + p2[1]) / 2,
        (p1[2] + p2[2]) / 2,
    )
