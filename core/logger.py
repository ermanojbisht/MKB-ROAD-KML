"""
logger.py — Centralised logging setup for MKB-ROAD-KML.

Usage:
    from core.logger import get_logger
    log = get_logger(__name__)
    log.info("Starting conversion")
    log.warning("Point count low")
    log.error("Could not parse KML: %s", path)

Call setup_logging(config) once at app startup (main.py).
After that, get_logger() returns correctly configured loggers everywhere.
"""

import logging
import logging.handlers
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

_INITIALIZED = False
_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(config: "ConfigManager | None" = None) -> None:
    """
    Initialise root logger. Call once at startup.
    If config is None, defaults to INFO level, console only.
    """
    global _INITIALIZED

    level_name = "INFO"
    log_to_file = False
    log_dir = Path.home() / ".mkb-road-kml" / "logs"

    if config is not None:
        level_name = config.get("logging", "level", "INFO").upper()
        log_to_file = config.get("logging", "log_to_file", False)
        raw_dir = config.get("logging", "log_dir", "~/.mkb-road-kml/logs")
        log_dir = Path(raw_dir).expanduser()

    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers (re-init safe)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    if log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "mkb-road-kml.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _INITIALIZED = True
    logging.getLogger(__name__).debug("Logging initialised — level=%s file=%s", level_name, log_to_file)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. setup_logging() should be called first."""
    if not _INITIALIZED:
        # Fallback: basic console logging so nothing breaks if called early
        logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    return logging.getLogger(name)
