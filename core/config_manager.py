"""
config_manager.py — TOML config loader for MKB-ROAD-KML.

Priority (highest wins):
  project.toml  >  ~/.mkb-road-kml/config.toml  >  config/defaults.toml

Usage:
    from core.config_manager import ConfigManager
    cfg = ConfigManager()                         # global config, no project
    cfg = ConfigManager(project_dir="/path/to/project")
    val = cfg.get("simplify", "min_distance_meters")
    cfg.set("simplify", "min_distance_meters", 3.0)  # writes to active level
    cfg.save_global()
    cfg.save_project()
"""

import copy
import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
import tomli_w
from pathlib import Path
from typing import Any


# Path to the shipped defaults inside the package
_DEFAULTS_PATH = Path(__file__).parent.parent / "config" / "defaults.toml"
_GLOBAL_CONFIG_PATH = Path.home() / ".mkb-road-kml" / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Returns a new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_toml(path: Path) -> dict:
    """Load a TOML file. Returns empty dict if file does not exist."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _save_toml(path: Path, data: dict) -> None:
    """Write a TOML file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


class ConfigManager:
    """
    Loads and merges config from three levels:
      1. Shipped defaults  (config/defaults.toml)
      2. Global user config (~/.mkb-road-kml/config.toml)
      3. Project config    (<project_dir>/project.toml)  — optional

    The merged result is available via get(). Changes can be written back to
    the global or project level with save_global() / save_project().
    """

    def __init__(self, project_dir: str | Path | None = None):
        self._defaults: dict = _load_toml(_DEFAULTS_PATH)
        self._global: dict = self._load_or_create_global()
        self._project_dir: Path | None = Path(project_dir) if project_dir else None
        self._project: dict = self._load_project()
        self._merged: dict = self._build_merged()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """Return config value from merged config. Falls back to fallback if missing."""
        return self._merged.get(section, {}).get(key, fallback)

    def get_section(self, section: str) -> dict:
        """Return a full config section as a dict."""
        return copy.deepcopy(self._merged.get(section, {}))

    def set_global(self, section: str, key: str, value: Any) -> None:
        """Set a value in the global config layer (not yet saved to disk)."""
        self._global.setdefault(section, {})[key] = value
        self._merged = self._build_merged()

    def set_project(self, section: str, key: str, value: Any) -> None:
        """Set a value in the project config layer (not yet saved to disk)."""
        if self._project_dir is None:
            raise ValueError("No project directory set — cannot write project config.")
        self._project.setdefault(section, {})[key] = value
        self._merged = self._build_merged()

    def save_global(self) -> None:
        """Persist the current global config layer to disk."""
        _save_toml(_GLOBAL_CONFIG_PATH, self._global)

    def save_project(self) -> None:
        """Persist the current project config layer to disk."""
        if self._project_dir is None:
            raise ValueError("No project directory set — cannot save project config.")
        _save_toml(self._project_dir / "project.toml", self._project)

    def set_last_project(self, project_dir: str | Path) -> None:
        """Update last_project in global config and save."""
        self.set_global("app", "last_project", str(project_dir))
        self.save_global()

    @property
    def global_path(self) -> Path:
        return _GLOBAL_CONFIG_PATH

    @property
    def project_path(self) -> Path | None:
        if self._project_dir is None:
            return None
        return self._project_dir / "project.toml"

    @property
    def merged(self) -> dict:
        """Return a deep copy of the fully merged config."""
        return copy.deepcopy(self._merged)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_create_global(self) -> dict:
        """Load global config, creating it from defaults if it doesn't exist."""
        if not _GLOBAL_CONFIG_PATH.exists():
            _save_toml(_GLOBAL_CONFIG_PATH, self._defaults)
        return _load_toml(_GLOBAL_CONFIG_PATH)

    def _load_project(self) -> dict:
        if self._project_dir is None:
            return {}
        return _load_toml(self._project_dir / "project.toml")

    def _build_merged(self) -> dict:
        merged = copy.deepcopy(self._defaults)
        merged = _deep_merge(merged, self._global)
        merged = _deep_merge(merged, self._project)
        return merged
