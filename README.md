# MKB-ROAD-KML

A standalone desktop tool for road survey engineers to convert Excel GPS data into KML, simplify and densify road lines, add chainage markers, and merge multi-segment KML files — with step-by-step wizards and a live map preview.

Runs on **Ubuntu 22.04+** and **Windows 10/11**.

---

## Features

| Feature | Description |
|---|---|
| **Excel → KML Wizard** | Auto-maps columns, validates data, shows dry-run preview before saving |
| **Project Management** | One folder per road (`sources/`, `output/`, `project.toml`) |
| **Simplify** | Ramer-Douglas-Peucker + minimum-distance filter; removes redundant GPS points |
| **Densify** | Interpolates new points where gaps exceed a configurable distance |
| **Chainage Markers** | Places distance markers every N metres + at detected road bends |
| **Merge Wizard** | Stitches 2+ KML segments; auto-detects direction, handles reversed segments and overlap |
| **Edit & Re-process** | Edit metadata (name, color, width) and re-run geometry operations on any KML; collapsible sidebar frees space |
| **Version History** | Auto-backs up existing files as `name_v1.kml`, `name_v2.kml`, … before every save |
| **Settings Panel** | In-app editor for all config values (global and per-project) |
| **Offline Map** | Leaflet.js map works without internet; tiles load when online |
| **Map Layer Switcher** | Switch between 6 tile providers in-map: CARTO Voyager/Light/Dark, OSM, ESRI Satellite, ESRI Topo |

---

## Installation

### Option A — Run from source (Linux / Ubuntu)

```bash
# 1. Clone the repository
git clone https://github.com/ermanojbisht/MKB-ROAD-KML.git
cd MKB-ROAD-KML

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch
python main.py
```

**Requirements:** Python 3.10+, pip, git

#### Pulling future updates (Linux)

```bash
cd MKB-ROAD-KML
git pull
pip install -r requirements.txt   # only if requirements changed
python main.py
```

---

### Option A — Run from source (Windows 10/11)

**One-time prerequisites:**
- Python 3.10+ from https://www.python.org/downloads/ — tick **"Add Python to PATH"** during install
- Git from https://git-scm.com/download/win

Open **Command Prompt** or **PowerShell**:

```bat
:: 1. Clone the repository
git clone https://github.com/ermanojbisht/MKB-ROAD-KML.git
cd MKB-ROAD-KML

:: 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

:: 3. Install dependencies
pip install -r requirements.txt

:: 4. Launch
python main.py
```

The app creates its config file (`%USERPROFILE%\.mkb-road-kml\config.toml`) automatically on first run.

#### Pulling future updates (Windows)

```bat
cd MKB-ROAD-KML
git pull
pip install -r requirements.txt
python main.py
```

---

### Option B — Pre-built Windows binary (no Python needed)

Download the latest `mkb-road-kml-windows.zip` from the [GitHub Releases](https://github.com/ermanojbisht/MKB-ROAD-KML/releases) page, unzip it, and run `mkb-road-kml.exe`. No Python or installation required.

The Windows binary is built automatically by GitHub Actions on every push to `main` and on every `v*` tag release.

---

### Option C — Pre-built Linux binary

```bash
# After downloading or building the dist/ folder:
bash install-linux.sh

# Then launch from terminal or app menu:
mkb-road-kml
```

### Option D — Build the binary yourself

```bash
# Install dev dependencies (includes PyInstaller)
pip install -r requirements-dev.txt

# Clean any previous build first (important after code changes)
# Linux:
rm -rf build/ dist/
# Windows:
rmdir /s /q build dist

# Linux
pyinstaller mkb-road-kml-linux.spec
./dist/mkb-road-kml/mkb-road-kml

# Windows (run these commands on a Windows machine)
pyinstaller mkb-road-kml-windows.spec
dist\mkb-road-kml\mkb-road-kml.exe
```

> **Important:** The binary freezes your code at build time. After every `git pull`,
> delete `build/` and `dist/` and rebuild — otherwise the binary runs the old code.

---

## How to Use

### 1. Create a Project

Open the **Projects** tab → **New Project** → enter a name and choose a parent folder.

The tool creates:
```
MyRoad/
├── sources/        ← original KML and Excel files
├── intermediates/  ← working copies
├── output/         ← final merged / processed KML
└── project.toml    ← project-specific config overrides
```

### 2. Convert Excel to KML

Go to the **Excel → KML** tab and follow the 5-step wizard:

1. **Select file** — pick your `.xlsx` or `.xls` file; choose the sheet if there are multiple.
2. **Map columns** — the wizard auto-detects `Latitude`, `Longitude`, `Chainage` columns by name. If detection fails, use the dropdown menus to map manually.
3. **Validate** — errors (missing values, out-of-range coordinates) are shown in a table. Fix the Excel file and reload, or click **Ignore Warnings** to continue with warnings only.
4. **Save** — choose a project folder; the KML is written to `sources/`.
5. **Preview** — the generated road line is shown on the map.

**Required columns:** `Latitude` (or `lat`, `start_lat`) and `Longitude` (or `lon`, `lng`, `start_lon`).

**Optional columns:** `Chainage` / `distance`, `Altitude` / `elevation`.

### 3. Merge KML Segments

Go to the **Merge** tab:

1. **Step 1 — Add files:** Click **Add KML** to load each segment. Drag rows to reorder. The map shows each segment in a different colour with direction arrows, green start dot, and red end dot.
2. **Step 2 — Review connections:** The wizard auto-detects whether each pair joins naturally, or whether a segment needs to be reversed. Click **Reverse** on any segment if the direction arrow looks wrong. Adjust **Overlap trim** if there are duplicate points near the join.
3. **Step 3 — Preview:** The merged line (white) is shown overlaid on the originals (faded). Check that it flows correctly.
4. **Step 4 — Save:** Enter an output name and folder; the merged KML is written to disk.

### 4. Edit & Re-process

Go to the **Edit** tab:

1. Click **Browse…** and pick any KML file, then **Load & Preview**.
2. **Metadata** section — change the name, description, line colour (AABBGGRR hex), width, or altitude mode, then **Save Metadata**.
3. **Re-process** section — tick **Simplify**, **Densify**, and/or **Chainage markers**, adjust the parameters, then **Preview** to see the result on the map. Click **Save Processed** when satisfied.

Every save automatically backs up the previous version: `road_v1.kml`, `road_v2.kml`, …

### 5. Settings

Go to the **Settings** tab to edit global defaults or project-specific overrides. Changes are in-memory until you click **Save**.

Key settings:

| Section | Key | Default | Description |
|---|---|---|---|
| simplify | min_distance_meters | 5.0 | Remove points closer than this |
| simplify | rdp_epsilon | 0.00001 | RDP angular tolerance (degrees) |
| densify | max_distance_meters | 10.0 | Interpolate when gap exceeds this |
| chainage | interval_meters | 100 | Place a marker every N metres |
| chainage | start_chainage | 0 | Starting distance offset |
| merge | snap_tolerance_meters | 50.0 | Max gap still considered a valid join |
| merge | overlap_trim_meters | 5.0 | Strip points this close to the junction |
| output | default_line_color | ff0000ff | AABBGGRR (opaque red) |
| output | default_line_width | 4 | Line width in pixels |

---

## Line Color Format

KML uses **AABBGGRR** order (not RGB). Examples:

| Color | AABBGGRR |
|---|---|
| Opaque red | `ff0000ff` |
| Opaque blue | `ffff0000` |
| Opaque green | `ff00ff00` |
| Opaque yellow | `ff00ffff` |
| 50% transparent red | `800000ff` |

---

## Headless / Batch Mode

Run geometry operations without the GUI:

```bash
python main.py --headless \
    --input road_raw.kml \
    --output road_clean.kml \
    --simplify \
    --densify \
    --chainage \
    --project /path/to/MyRoad
```

Flags:

| Flag | Description |
|---|---|
| `--simplify` | Apply RDP simplification |
| `--densify` | Interpolate points to fill gaps |
| `--chainage` | Add chainage markers to output |
| `--project PATH` | Load `project.toml` config from this folder |

---

## Config Files

**Global config** (`~/.mkb-road-kml/config.toml`) — created automatically on first run.

**Project config** (`<project>/project.toml`) — overrides global values for one road only.

Both are plain TOML files you can also edit in a text editor.

---

## Troubleshooting

### Map shows no tiles / blank grey background

**Cause:** The app is offline, or the tile server returned an error.

**Fix:** The map still shows your road lines (polylines do not need internet). Tiles reload automatically when you reconnect. If you are online but still see no tiles, see the "403 Forbidden from tile server" section below.

---

### 403 Forbidden error from tile server (OpenStreetMap / CARTO)

**Cause:** The embedded browser's User-Agent was identified as a bot and blocked.

**Fix (already applied in v0.1.0+):** `map_canvas.py` now sets a standard browser User-Agent and uses the CARTO Voyager tile service, which does not block embedded WebView clients.

If you are running an older version:

1. Open `gui/map_canvas.py`.
2. In `MapCanvas.__init__`, add after `self._view = QWebEngineView(self)`:
   ```python
   self._view.page().profile().setHttpUserAgent(
       "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   )
   ```
3. In `_build_html()`, replace the OSM tile URL with:
   ```
   https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png
   ```

**Built-in tile layer switcher:** Click the layers icon (top-right of the map) to switch between:

| Layer | Style |
|---|---|
| Voyager (default) | CARTO colour road map |
| CARTO Light | Clean minimal light |
| CARTO Dark | Dark night mode |
| OpenStreetMap | Standard OSM |
| ESRI Satellite | Satellite imagery |
| ESRI Topo | Topographic map |

---

### Gdk-CRITICAL Wayland warnings in terminal (Linux)

```
(python:XXXXX): Gdk-CRITICAL **: gdk_wayland_window_set_dbus_properties_libgtk_only: assertion failed
```

**Cause:** GTK attempts to set D-Bus properties on Qt's native Wayland window, which fails harmlessly.

**Fix (already applied in v0.1.0+):** `main.py` sets `QT_QPA_PLATFORM=xcb` on Linux, forcing Qt to use XWayland instead of native Wayland. No action needed.

If you still see it (e.g. running an older version), launch with:
```bash
QT_QPA_PLATFORM=xcb python main.py
```

---

### App does not start — "PyQt6 is not installed"

```bash
pip install pyqt6 pyqt6-webengine
```

---

### App does not start — "No module named 'tomllib'"

The `tomli` backport is missing from your environment. This can happen if you created the venv before `requirements.txt` was updated.

**Fix:**
```bash
pip install tomli
```

The code already handles Python 3.10 and 3.11+ automatically — no code changes needed.

---

### Excel file not loading — "Sheet not found" or column mapping fails

- Ensure the file is `.xlsx` (not `.xls`). If it is `.xls`, open it in Excel/LibreOffice and **Save As** `.xlsx`.
- Column names must contain recognisable keywords. Supported aliases:

  | Field | Recognised column names |
  |---|---|
  | Latitude | lat, latitude, start_lat, y, northing |
  | Longitude | lon, lng, longitude, start_lon, x, easting |
  | Chainage | chainage, ch, distance, dist, km |
  | Altitude | alt, altitude, elevation, elev, z, height |

- If your column names are not in this list, use the **manual mapping dropdowns** in Step 2 of the wizard.

---

### KML output has too few or too many points after simplify

- **Too few:** Reduce `simplify.min_distance_meters` (e.g. from 5.0 → 2.0) and reduce `rdp_epsilon` (e.g. 0.000005).
- **Too many:** Increase both values.
- These can be changed per-project in `project.toml` without affecting other roads.

---

### Merged KML has a gap or wrong direction at the join

1. Open the **Merge** wizard.
2. In Step 2, check the direction arrows on each segment. If a segment points the wrong way, click **Reverse**.
3. Increase **Snap tolerance** in Settings if the gap between endpoints is larger than 50 m.
4. Increase **Overlap trim** if there are duplicate points near the junction (symptom: the line doubles back at the join).

---

### Packaged binary does not launch on Linux

**Dependency check:**
```bash
./mkb-road-kml --headless --input test.kml --output /tmp/out.kml
```
If this works, the issue is display/GPU related.

**GPU / OpenGL issues (common on VMs or older hardware):**
```bash
./mkb-road-kml --no-sandbox
# or
QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu" ./mkb-road-kml
```

**Missing system libraries:**
```bash
ldd ./mkb-road-kml | grep "not found"
```
Install any missing packages with `apt install <library>`.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

All 88 tests should pass.

---

## Project Structure

```
MKB-ROAD-KML/
├── main.py                    # Entry point (GUI + headless CLI)
├── requirements.txt           # Runtime dependencies
├── requirements-dev.txt       # + pytest + pyinstaller
├── mkb-road-kml-linux.spec    # PyInstaller spec for Linux
├── mkb-road-kml-windows.spec  # PyInstaller spec for Windows
├── install-linux.sh           # One-shot Linux installer
├── mkb-road-kml.desktop       # Linux desktop launcher
├── .github/
│   └── workflows/
│       └── build-windows.yml  # GitHub Actions: builds Windows .exe automatically
├── config/
│   └── defaults.toml          # Shipped default config (read-only)
├── core/
│   ├── config_manager.py      # Two-level TOML config (global + project)
│   ├── geometry.py            # Simplify, densify, chainage
│   ├── kml_parser.py          # KML read/write (lxml)
│   ├── excel_reader.py        # Excel column detection + extraction
│   └── merger.py              # Endpoint detection, reversal, chain merge
├── gui/
│   ├── main_window.py         # App shell, sidebar navigation
│   ├── wizard_excel.py        # Excel → KML wizard (5 steps)
│   ├── wizard_merge.py        # Merge wizard (4 steps)
│   ├── panel_project.py       # Project file browser
│   ├── panel_edit.py          # Edit & re-process panel
│   ├── panel_settings.py      # Settings editor
│   ├── map_canvas.py          # Leaflet.js map widget
│   └── assets/
│       ├── leaflet/           # Bundled Leaflet.js + CSS (offline)
│       └── icons/             # App icon (SVG + PNG + ICO for Windows)
└── tests/
    ├── fixtures/              # Sample KML, Excel, and polygon files
    ├── test_geometry.py
    ├── test_kml_parser.py
    ├── test_excel_reader.py
    ├── test_merger.py
    └── test_config_manager.py
```

---

## License

Personal / internal use. Not licensed for redistribution.
