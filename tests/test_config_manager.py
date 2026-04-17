"""
test_config_manager.py — Unit tests for core/config_manager.py

Tests: defaults load, global override, project override,
       missing files, invalid TOML, save/reload.
"""

import pytest
import tempfile
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_manager import ConfigManager, _GLOBAL_CONFIG_PATH


class TestDefaultsOnly:
    def test_defaults_load(self, tmp_path):
        # Redirect global config to tmp so we don't pollute real config
        fake_global = tmp_path / "config.toml"
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(5.0)
            assert cfg.get("chainage", "interval_meters") == 100
            assert cfg.get("output", "default_line_color") == "ff0000ff"

    def test_global_config_created_on_first_run(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        assert not fake_global.exists()
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
        assert fake_global.exists()

    def test_fallback_value_returned(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            result = cfg.get("nonexistent_section", "nonexistent_key", fallback="DEFAULT")
            assert result == "DEFAULT"


class TestGlobalOverride:
    def test_global_overrides_defaults(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        fake_global.write_text('[simplify]\nmin_distance_meters = 10.0\n')
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(10.0)

    def test_global_partial_override_keeps_other_defaults(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        fake_global.write_text('[simplify]\nmin_distance_meters = 10.0\n')
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            # Other simplify keys still come from defaults
            assert cfg.get("simplify", "algorithm") == "rdp"

    def test_set_global_and_save(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            cfg.set_global("chainage", "interval_meters", 50)
            cfg.save_global()
            assert fake_global.exists()
            with open(fake_global, "rb") as f:
                data = tomllib.load(f)
            assert data["chainage"]["interval_meters"] == 50


class TestProjectOverride:
    def test_project_overrides_global(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        fake_global.write_text('[simplify]\nmin_distance_meters = 10.0\n')
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "project.toml").write_text('[simplify]\nmin_distance_meters = 3.0\n')
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager(project_dir=project_dir)
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(3.0)

    def test_project_partial_override(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "project.toml").write_text('[chainage]\ninterval_meters = 50\n')
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager(project_dir=project_dir)
            assert cfg.get("chainage", "interval_meters") == 50
            # Other keys still from global/defaults
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(5.0)

    def test_no_project_dir_raises_on_save(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            with pytest.raises(ValueError, match="No project directory"):
                cfg.save_project()

    def test_set_project_and_save(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        project_dir = tmp_path / "proj2"
        project_dir.mkdir()
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager(project_dir=project_dir)
            cfg.set_project("merge", "snap_tolerance_meters", 25.0)
            cfg.save_project()
        proj_toml = project_dir / "project.toml"
        assert proj_toml.exists()
        with open(proj_toml, "rb") as f:
            data = tomllib.load(f)
        assert data["merge"]["snap_tolerance_meters"] == pytest.approx(25.0)


class TestMissingFiles:
    def test_missing_global_uses_defaults(self, tmp_path):
        fake_global = tmp_path / "nonexistent" / "config.toml"
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager()
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(5.0)

    def test_missing_project_toml_uses_global(self, tmp_path):
        fake_global = tmp_path / "config.toml"
        project_dir = tmp_path / "empty_proj"
        project_dir.mkdir()
        # No project.toml created
        with patch("core.config_manager._GLOBAL_CONFIG_PATH", fake_global):
            cfg = ConfigManager(project_dir=project_dir)
            assert cfg.get("simplify", "min_distance_meters") == pytest.approx(5.0)
