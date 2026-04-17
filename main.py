"""
main.py — MKB-ROAD-KML entry point.

Modes:
  GUI (default):    python main.py
  Headless CLI:     python main.py --headless [options]

Headless options:
  --input   PATH      Input KML file
  --output  PATH      Output KML file
  --simplify          Apply simplify (RDP + min-distance filter)
  --densify           Apply densify (interpolate points)
  --chainage          Add chainage markers
  --project PATH      Project directory (for project-level config)
"""

import argparse
import os
import sys
from pathlib import Path

# Suppress Gdk-CRITICAL Wayland/GTK D-Bus warnings on Linux.
# PyQt6 + WebEngine works more reliably under XWayland (xcb backend).
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    # Suppress "GBM is not supported" / Vulkan fallback messages from Chromium.
    # Software rendering (--disable-gpu) is reliable on all Linux GPU configs.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from core.config_manager import ConfigManager
from core.logger import setup_logging, get_logger


def run_headless(args: argparse.Namespace) -> int:
    """Run geometry operations without GUI. Returns exit code."""
    cfg = ConfigManager(project_dir=args.project)
    setup_logging(cfg)
    log = get_logger(__name__)

    from core.kml_parser import read_linestring, write_kml, KMLParseError
    from core.geometry import simplify, densify, compute_chainage

    if not args.input:
        log.error("--input is required in headless mode")
        return 1
    if not args.output:
        log.error("--output is required in headless mode")
        return 1

    input_path = Path(args.input)
    output_path = Path(args.output)

    log.info("MKB-ROAD-KML headless mode")
    log.info("Input:  %s", input_path)
    log.info("Output: %s", output_path)

    try:
        coords = read_linestring(input_path)
        log.info("Read %d coordinates", len(coords))
    except KMLParseError as exc:
        log.error("Failed to read KML: %s", exc)
        return 1
    except FileNotFoundError:
        log.error("Input file not found: %s", input_path)
        return 1

    if args.simplify:
        before = len(coords)
        coords = simplify(coords, cfg)
        log.info("Simplify: %d → %d points", before, len(coords))

    if args.densify:
        before = len(coords)
        coords = densify(coords, cfg)
        log.info("Densify: %d → %d points", before, len(coords))

    placemarks = None
    if args.chainage:
        placemarks = compute_chainage(coords, cfg)
        log.info("Chainage: %d markers", len(placemarks))

    write_kml(output_path, coords, placemarks=placemarks)
    log.info("Done. Output written to %s", output_path)
    return 0


def run_gui() -> int:
    """Launch the PyQt6 GUI application."""
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        # WebEngineView must be imported (or AA_ShareOpenGLContexts set)
        # BEFORE QApplication is instantiated
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        print("ERROR: PyQt6 is not installed. Run: pip install pyqt6 pyqt6-webengine")
        return 1

    cfg = ConfigManager()
    setup_logging(cfg)
    log = get_logger(__name__)
    log.info("Launching MKB-ROAD-KML GUI")

    # Set theme before any widget is created so apply_dark() works everywhere.
    from gui.theme import set_theme
    theme = cfg.get("ui", "theme", "dark")
    set_theme(theme)

    app = QApplication(sys.argv)
    app.setApplicationName("MKB-ROAD-KML")
    app.setApplicationVersion(cfg.get("app", "version", "0.1.0"))
    app.setStyle("Fusion")   # clean base for both light and dark

    # GUI main window — imported here so headless mode works without PyQt6
    from gui.main_window import MainWindow
    window = MainWindow(cfg)
    window.show()
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mkb-road-kml",
        description="MKB-ROAD-KML — Road survey KML management tool",
    )
    parser.add_argument("--headless", action="store_true",
                        help="Run without GUI (batch processing mode)")
    parser.add_argument("--input", metavar="PATH", help="Input KML file")
    parser.add_argument("--output", metavar="PATH", help="Output KML file")
    parser.add_argument("--simplify", action="store_true", help="Apply simplification")
    parser.add_argument("--densify", action="store_true", help="Apply densification")
    parser.add_argument("--chainage", action="store_true", help="Add chainage markers")
    parser.add_argument("--project", metavar="PATH", default=None,
                        help="Project directory (loads project.toml config)")

    args = parser.parse_args()

    if args.headless:
        return run_headless(args)
    else:
        return run_gui()


if __name__ == "__main__":
    sys.exit(main())
