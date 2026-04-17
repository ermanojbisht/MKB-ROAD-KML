# -*- mode: python ; coding: utf-8 -*-
"""
mkb-road-kml-linux.spec — PyInstaller spec for Linux (Ubuntu 22.04+)

Build command (run from repo root with venv active):
    pyinstaller mkb-road-kml-linux.spec

Output: dist/mkb-road-kml/mkb-road-kml   (one-folder bundle)

Notes:
  • PyQt6-WebEngine requires QtWebEngineProcess, .pak resource files, and
    qtwebengine_locales to be present beside the main binary — these are
    added as explicit datas below.
  • The Leaflet.js/CSS assets and config/defaults.toml are bundled so the
    app works on machines with no internet and no Python installed.
  • Use --onedir (default here) rather than --onefile so Qt can find its
    helper process at a predictable relative path.
"""

import sys
from pathlib import Path
import PyQt6

# ── Paths ────────────────────────────────────────────────────────────────────
HERE       = Path(SPECPATH)                                  # repo root
QT6_DIR    = Path(PyQt6.__file__).parent / "Qt6"
QT_LIBEXEC = QT6_DIR / "libexec"
QT_RES     = QT6_DIR / "resources"
QT_TRANS   = QT6_DIR / "translations"

# ── Data files ───────────────────────────────────────────────────────────────
datas = [
    # App assets
    (str(HERE / "gui" / "assets" / "leaflet"),  "gui/assets/leaflet"),
    (str(HERE / "config" / "defaults.toml"),    "config"),
    # Qt WebEngine — helper process
    (str(QT_LIBEXEC / "QtWebEngineProcess"),    "PyQt6/Qt6/libexec"),
    # Qt WebEngine — .pak resource blobs
    (str(QT_RES),                               "PyQt6/Qt6/resources"),
    # Qt WebEngine — locale paks.
    # Shipping only en-US saves ~50 MB. Add more locales here if needed
    # (e.g. "hi.pak" for Hindi). To ship ALL locales replace the two lines
    # below with a single line:
    #   (str(QT_TRANS / "qtwebengine_locales"), "PyQt6/Qt6/translations/qtwebengine_locales"),
    (str(QT_TRANS / "qtwebengine_locales" / "en-US.pak"),
     "PyQt6/Qt6/translations/qtwebengine_locales"),
]

# ── Hidden imports ────────────────────────────────────────────────────────────
# PyInstaller sometimes misses Qt plugin loaders and sip bindings.
hiddenimports = [
    "PyQt6.sip",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    "tomllib",
    "tomli_w",
    "lxml.etree",
    "lxml._elementpath",
    "pandas",
    "openpyxl",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mkb-road-kml",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(HERE / "gui" / "assets" / "icons" / "app.png")
        if (HERE / "gui" / "assets" / "icons" / "app.png").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mkb-road-kml",
)
