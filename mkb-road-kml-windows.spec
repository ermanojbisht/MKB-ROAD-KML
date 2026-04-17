# -*- mode: python ; coding: utf-8 -*-
"""
mkb-road-kml-windows.spec — PyInstaller spec for Windows 10/11

Build command (run from repo root in a Windows venv):
    pyinstaller mkb-road-kml-windows.spec

Output: dist\\mkb-road-kml\\mkb-road-kml.exe   (one-folder bundle)

Prerequisites on the Windows build machine:
    pip install pyqt6 pyqt6-webengine pandas openpyxl lxml tomli-w pyinstaller

Notes:
  • console=False → no black terminal window on launch
  • QtWebEngineProcess.exe and .pak files must be beside the .exe
  • On Windows, Qt6 data sits in site-packages/PyQt6/Qt6/ just like Linux
  • xdg-open is not available on Windows — use os.startfile() instead
    (already tracked in Refinements Queue; no code change needed for packaging)
"""

import sys
from pathlib import Path
import PyQt6

# ── Paths ────────────────────────────────────────────────────────────────────
HERE       = Path(SPECPATH)
QT6_DIR    = Path(PyQt6.__file__).parent / "Qt6"
QT_LIBEXEC = QT6_DIR / "bin"          # on Windows QtWebEngineProcess.exe is in bin/
QT_RES     = QT6_DIR / "resources"
QT_TRANS   = QT6_DIR / "translations"

# Fallback: some PyQt6 Windows wheels put it in libexec/
if not (QT_LIBEXEC / "QtWebEngineProcess.exe").exists():
    QT_LIBEXEC = QT6_DIR / "libexec"

# ── Data files ────────────────────────────────────────────────────────────────
_datas = [
    # App assets
    (str(HERE / "gui" / "assets" / "leaflet"),  "gui/assets/leaflet"),
    (str(HERE / "config" / "defaults.toml"),    "config"),
    # Qt WebEngine resources
    (str(QT_RES),                               "PyQt6/Qt6/resources"),
    # Ship only en-US to save ~50 MB. For more locales add additional lines
    # or replace with the full directory as a single tuple.
    (str(QT_TRANS / "qtwebengine_locales" / "en-US.pak"),
     "PyQt6/Qt6/translations/qtwebengine_locales"),
]

# Add QtWebEngineProcess.exe only if it exists at discovery time
_we_proc = QT_LIBEXEC / "QtWebEngineProcess.exe"
if _we_proc.exists():
    _datas.append((str(_we_proc), "PyQt6/Qt6/bin"))

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = [
    "PyQt6.sip",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    "tomllib",
    "tomli",
    "tomli_w",
    "lxml.etree",
    "lxml._elementpath",
    "pandas",
    "openpyxl",
]

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

_icon = str(HERE / "gui" / "assets" / "icons" / "app.ico")
_icon_arg = _icon if Path(_icon).exists() else None

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
    icon=_icon_arg,
    version=None,           # optional: add a version_file= here for Windows metadata
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    name="mkb-road-kml",
)
