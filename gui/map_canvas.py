"""
map_canvas.py — Leaflet.js map widget embedded in QWebEngineView.

Usage:
    canvas = MapCanvas(parent)
    canvas.load_coords([(lon, lat, alt), ...], color="#ff0000", name="Road A-B")
    canvas.clear()

Features:
    - Renders LineString polylines from coordinate lists
    - Supports multiple named layers (different colors)
    - Auto-fits map to show all loaded geometry
    - Hybrid: loads OSM tiles when online, graceful plain background offline
    - Direction arrows on lines (using CSS rotation)
    - Start marker (green) and end marker (red) per layer
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile
from PyQt6.QtWidgets import QWidget, QVBoxLayout

# Tile CDNs block Qt's default "QtWebEngine/x.x" User-Agent with HTTP 403.
# Set this on QWebEngineProfile.defaultProfile() BEFORE any view is created.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
QWebEngineProfile.defaultProfile().setHttpUserAgent(_BROWSER_UA)

# Temp file used for rendering — file:// origin + LocalContentCanAccessRemoteUrls
# is more reliable than setHtml(..., "about:blank") which gives a null origin.
_TMP_MAP = Path(tempfile.gettempdir()) / "mkb_road_kml_map.html"

from core.logger import get_logger
from core.kml_parser import Coord

log = get_logger(__name__)

_ASSETS_DIR = Path(__file__).parent / "assets" / "leaflet"
_LEAFLET_JS = _ASSETS_DIR / "leaflet.js"
_LEAFLET_CSS = _ASSETS_DIR / "leaflet.css"


def _build_html(layers: list[dict]) -> str:
    """Build the full Leaflet HTML page with a tile layer switcher."""
    leaflet_js = _LEAFLET_JS.read_text(encoding="utf-8") if _LEAFLET_JS.exists() else ""
    leaflet_css = _LEAFLET_CSS.read_text(encoding="utf-8") if _LEAFLET_CSS.exists() else ""

    layers_json = json.dumps(layers)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  {leaflet_css}
  html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
  .direction-arrow {{
    font-size: 18px;
    color: rgba(0,0,0,0.6);
    text-shadow: 0 0 3px white;
    line-height: 1;
  }}
</style>
</head>
<body>
<div id="map"></div>
<script>
{leaflet_js}
</script>
<script>
var map = L.map('map');

// ── Base tile layers ──────────────────────────────────────────────────────────
var baseLayers = {{
  "Voyager (default)": L.tileLayer(
    'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{ attribution: '© OpenStreetMap © CARTO', subdomains: 'abcd', maxZoom: 20, errorTileUrl: '' }}
  ),
  "CARTO Light": L.tileLayer(
    'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{ attribution: '© OpenStreetMap © CARTO', subdomains: 'abcd', maxZoom: 20, errorTileUrl: '' }}
  ),
  "CARTO Dark": L.tileLayer(
    'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{ attribution: '© OpenStreetMap © CARTO', subdomains: 'abcd', maxZoom: 20, errorTileUrl: '' }}
  ),
  "OpenStreetMap": L.tileLayer(
    'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
    {{ attribution: '© OpenStreetMap contributors', maxZoom: 19, errorTileUrl: '' }}
  ),
  "ESRI Satellite": L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{ attribution: '© Esri, DigitalGlobe', maxZoom: 19, errorTileUrl: '' }}
  ),
  "ESRI Topo": L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{ attribution: '© Esri', maxZoom: 19, errorTileUrl: '' }}
  )
}};

baseLayers["Voyager (default)"].addTo(map);
L.control.layers(baseLayers, null, {{ collapsed: true, position: 'topright' }}).addTo(map);

var allBounds = [];
var layers = {layers_json};

var COLORS = ["#e63946","#2a9d8f","#e9c46a","#f4a261","#264653","#7b2d8b","#1d3557"];

layers.forEach(function(layer, idx) {{
    var color = layer.color || COLORS[idx % COLORS.length];
    var pts = layer.coords.map(function(c) {{ return [c[1], c[0]]; }});

    if (pts.length > 0) {{
        var poly = L.polyline(pts, {{
            color: color,
            weight: 4,
            opacity: 0.85
        }}).addTo(map);

        allBounds.push(poly.getBounds());

        L.circleMarker(pts[0], {{
            radius: 8,
            color: '#006400',
            fillColor: '#00c800',
            fillOpacity: 1,
            weight: 2
        }}).addTo(map).bindTooltip(layer.name + ' — Start', {{permanent: false}});

        L.circleMarker(pts[pts.length-1], {{
            radius: 8,
            color: '#8b0000',
            fillColor: '#e60000',
            fillOpacity: 1,
            weight: 2
        }}).addTo(map).bindTooltip(layer.name + ' — End', {{permanent: false}});

        var arrowInterval = Math.max(1, Math.floor(pts.length / 5));
        for (var i = arrowInterval; i < pts.length - 1; i += arrowInterval) {{
            var p1 = pts[i-1], p2 = pts[i];
            var dx = p2[1] - p1[1], dy = p2[0] - p1[0];
            var angle = Math.atan2(dx, dy) * 180 / Math.PI;
            var icon = L.divIcon({{
                className: '',
                html: '<div class="direction-arrow" style="transform:rotate(' + angle + 'deg)">▲</div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            }});
            L.marker(pts[i], {{icon: icon}}).addTo(map);
        }}
    }}

    // Chainage / point markers
    if (layer.markers && layer.markers.length > 0) {{
        layer.markers.forEach(function(m) {{
            // m = [lon, lat, name]
            var pt = [m[1], m[0]];
            L.circleMarker(pt, {{
                radius: 5,
                color: '#1a1a1a',
                fillColor: color,
                fillOpacity: 0.95,
                weight: 1.5
            }}).addTo(map).bindTooltip(m[2], {{permanent: false, direction: 'top'}});
        }});
    }}
}});

if (allBounds.length > 0) {{
    var combined = allBounds[0];
    for (var i = 1; i < allBounds.length; i++) {{
        combined = combined.extend(allBounds[i]);
    }}
    map.fitBounds(combined, {{padding: [30, 30]}});
}} else {{
    map.setView([20.5937, 78.9629], 5);
}}
</script>
</body>
</html>"""


class MapCanvas(QWidget):
    """
    Embeds a Leaflet.js map in a PyQt6 widget.
    Call load_coords() to add a layer, clear() to reset.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layers: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView(self)
        self._view.setMinimumWidth(250)
        # Allow the local file:// page to fetch remote HTTPS tile images
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        layout.addWidget(self._view)
        self._render()

    def load_coords(
        self,
        coords: list[Coord],
        *,
        name: str = "Layer",
        color: str = "#e63946",
    ) -> None:
        """Add a coordinate layer to the map and re-render."""
        self._layers.append({
            "name": name,
            "color": color,
            "coords": [[c[0], c[1], c[2]] for c in coords],
        })
        log.debug("MapCanvas: added layer '%s' with %d points", name, len(coords))
        self._render()

    def load_markers(
        self,
        placemarks: list,          # list[ChainagePlacemark]
        *,
        color: str = "#f59e0b",
    ) -> None:
        """Add chainage point markers to the map (separate from the line layer)."""
        marker_data = [[p.lon, p.lat, p.name] for p in placemarks]
        self._layers.append({
            "name": "Chainage markers",
            "color": color,
            "coords": [],
            "markers": marker_data,
        })
        log.debug("MapCanvas: added %d chainage markers", len(placemarks))
        self._render()

    def clear(self) -> None:
        """Remove all layers and reset the map."""
        self._layers.clear()
        self._render()

    def _render(self) -> None:
        html = _build_html(self._layers)
        # Write to a temp file and load via file:// so the page has a real
        # origin; combined with LocalContentCanAccessRemoteUrls this reliably
        # allows HTTPS tile requests without 403 errors.
        _TMP_MAP.write_text(html, encoding="utf-8")
        self._view.load(QUrl.fromLocalFile(str(_TMP_MAP)))
