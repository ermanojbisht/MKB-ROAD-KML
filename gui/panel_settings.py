"""
panel_settings.py — GUI config editor for MKB-ROAD-KML.

Two tabs:
  • Global Config  — edits ~/.mkb-road-kml/config.toml
  • Project Config — edits <project_dir>/project.toml  (disabled if no project open)

Each section of the TOML is shown as a named group with key=value fields.
Changes are in-memory until the user clicks Save.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QScrollArea, QGroupBox, QGridLayout,
    QLineEdit, QComboBox, QFrame, QMessageBox, QSizePolicy,
)

from core.config_manager import ConfigManager
from core.logger import get_logger
from gui.theme import apply_dark, scroll_area_style, container_style, hint_style

log = get_logger(__name__)

_STYLE = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
QTabWidget::pane { border: 1px solid #313244; background: #1e1e2e; }
QTabBar::tab {
    background: #181825; color: #a6adc8;
    padding: 8px 20px; border: 1px solid #313244;
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #1e1e2e; color: #cba6f7; }
QTabBar::tab:hover:!selected { background: #262637; }
QLabel { color: #cdd6f4; }
QLabel#panelTitle { font-size: 18px; font-weight: bold; color: #cba6f7; }
QLabel#sectionHint { font-size: 11px; color: #585b70; padding: 2px 0 8px 0; }
QGroupBox {
    color: #a6adc8; border: 1px solid #313244;
    border-radius: 6px; margin-top: 10px; padding: 12px 8px 8px 8px;
}
QGroupBox::title { subcontrol-position: top left; padding: 0 8px; color: #cba6f7; }
QLineEdit {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 5px 8px;
    font-size: 12px; min-width: 180px;
}
QLineEdit:focus { border-color: #cba6f7; }
QComboBox {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 4px 8px;
}
QComboBox QAbstractItemView { background: #313244; color: #cdd6f4; }
QPushButton#primary {
    background: #cba6f7; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 8px 22px; font-weight: bold; font-size: 13px;
}
QPushButton#primary:hover { background: #d9b8ff; }
QPushButton#secondary {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 8px 22px; font-size: 13px;
}
QPushButton#secondary:hover { background: #3d3f55; }
QPushButton#secondary:disabled { color: #45475a; border-color: #313244; }
QFrame#separator { background: #313244; max-height: 1px; }
"""

# Sections and their keys with metadata: (display_label, widget_type, choices_if_combo)
_SECTION_META: dict[str, list[tuple[str, str, str, list[str]]]] = {
    # section: [(key, display_label, widget_type, choices)]
    "simplify": [
        ("min_distance_meters", "Min distance (m)", "float", []),
        ("algorithm",           "Algorithm",         "combo", ["rdp"]),
        ("rdp_epsilon",         "RDP epsilon",        "float", []),
    ],
    "densify": [
        ("max_distance_meters", "Max distance (m)", "float", []),
    ],
    "chainage": [
        ("interval_meters", "Interval (m)",    "int",    []),
        ("label_format",    "Label format",    "str",    []),
        ("start_chainage",  "Start chainage",  "int",    []),
    ],
    "merge": [
        ("snap_tolerance_meters",  "Snap tolerance (m)",  "float", []),
        ("overlap_trim_meters",    "Overlap trim (m)",    "float", []),
    ],
    "output": [
        ("default_line_color", "Line color (AABBGGRR)", "str",   []),
        ("default_line_width", "Line width (px)",       "int",   []),
        ("altitude_mode",      "Altitude mode",         "combo",
         ["relativeToGround", "absolute", "clampToGround"]),
    ],
    "logging": [
        ("level",       "Log level",        "combo", ["DEBUG", "INFO", "WARNING", "ERROR"]),
        ("log_to_file", "Log to file",      "combo", ["true", "false"]),
    ],
    "ui": [
        ("window_width",  "Window width",  "int", []),
        ("window_height", "Window height", "int", []),
        ("theme",         "Theme",         "combo", ["light", "dark"]),
    ],
}


def _btn(text: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    return b


def _sep() -> QFrame:
    f = QFrame()
    f.setObjectName("separator")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


class _ConfigTab(QWidget):
    """A scrollable tab showing all config sections as editable form groups."""

    def __init__(
        self,
        config: ConfigManager,
        level: str,       # "global" or "project"
        project_dir: Path | None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._config = config
        self._level = level
        self._project_dir = project_dir
        self._widgets: dict[tuple[str, str], QWidget] = {}  # (section, key) → widget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(scroll_area_style())

        content = QWidget()
        content.setStyleSheet(container_style())
        inner = QVBoxLayout(content)
        inner.setContentsMargins(16, 16, 16, 16)
        inner.setSpacing(12)

        if level == "project" and project_dir is None:
            lbl = QLabel("No project is currently open.\nOpen a project first to edit its config.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(hint_style("font-size: 14px;"))
            inner.addWidget(lbl)
        else:
            hint_text = (
                "Global defaults — apply to all projects unless overridden."
                if level == "global"
                else f"Project overrides — apply only to: {project_dir.name if project_dir else ''}"
            )
            hint = QLabel(hint_text)
            hint.setObjectName("sectionHint")
            inner.addWidget(hint)

            for section, fields in _SECTION_META.items():
                group = QGroupBox(section.upper())
                grid = QGridLayout(group)
                grid.setColumnStretch(1, 1)
                grid.setSpacing(8)

                for row, (key, label, wtype, choices) in enumerate(fields):
                    value = config.get(section, key, "")
                    if level == "project" and project_dir:
                        # Show project-level value if set, else empty (inherits from global)
                        import sys as _sys
                        if _sys.version_info >= (3, 11):
                            import tomllib
                        else:
                            import tomli as tomllib
                        proj_toml = project_dir / "project.toml"
                        proj_val = ""
                        if proj_toml.exists():
                            with open(proj_toml, "rb") as f:
                                proj_data = tomllib.load(f)
                            proj_val = str(proj_data.get(section, {}).get(key, ""))
                        value = proj_val

                    lbl_widget = QLabel(label + ":")
                    lbl_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                    if wtype == "combo" and choices:
                        widget: QWidget = QComboBox()
                        for c in choices:
                            widget.addItem(c)
                        idx = choices.index(str(value)) if str(value) in choices else 0
                        widget.setCurrentIndex(idx)
                    else:
                        widget = QLineEdit(str(value))
                        if level == "project":
                            widget.setPlaceholderText(f"(global: {config.get(section, key, '')})")

                    self._widgets[(section, key)] = widget
                    grid.addWidget(lbl_widget, row, 0)
                    grid.addWidget(widget, row, 1)

                inner.addWidget(group)

        inner.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def collect_values(self) -> dict[str, dict[str, Any]]:
        """Return {section: {key: value}} from current widget states."""
        result: dict[str, dict[str, Any]] = {}
        for (section, key), widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                val: Any = widget.currentText()
            else:
                val = widget.text().strip()

            # Cast to correct Python type
            meta = {k: (wtype, choices) for k, label, wtype, choices in _SECTION_META.get(section, [])}
            wtype_key = meta.get(key, ("str", []))[0]
            try:
                if wtype_key == "int":
                    val = int(val) if val else 0
                elif wtype_key == "float":
                    val = float(val) if val else 0.0
                elif val in ("true", "false"):
                    val = val == "true"
            except (ValueError, TypeError):
                pass  # Keep as string

            result.setdefault(section, {})[key] = val
        return result


class SettingsPanel(QWidget):
    """Settings page with Global and Project config tabs."""

    def __init__(self, config: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._project_dir: Path | None = None

        apply_dark(self, _STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 16)
        layout.setSpacing(8)

        # Title
        title = QLabel("Settings")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        layout.addWidget(_sep())
        layout.addSpacing(4)

        # Tabs
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, stretch=1)

        self._rebuild_tabs()

        # Save / Reload buttons
        btn_row = QHBoxLayout()
        reload_btn = _btn("↺ Reload from disk", "secondary")
        reload_btn.clicked.connect(self._reload)
        self._save_btn = _btn("💾 Save", "primary")
        self._save_btn.clicked.connect(self._save)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)
        layout.addLayout(btn_row)

    def set_project(self, project_dir: Path | None) -> None:
        """Call when project opens/closes to update Project Config tab."""
        self._project_dir = project_dir
        self._rebuild_tabs()

    def _rebuild_tabs(self) -> None:
        self._tabs.clear()
        self._global_tab = _ConfigTab(self._config, "global", None)
        self._project_tab = _ConfigTab(self._config, "project", self._project_dir)
        self._tabs.addTab(self._global_tab, "Global Config")
        self._tabs.addTab(self._project_tab, "Project Config")

    def _save(self) -> None:
        active = self._tabs.currentIndex()
        if active == 0:
            values = self._global_tab.collect_values()
            for section, kvs in values.items():
                for key, val in kvs.items():
                    self._config.set_global(section, key, val)
            self._config.save_global()
            QMessageBox.information(self, "Saved", "Global config saved.")
            log.info("Global config saved by user")
        else:
            if self._project_dir is None:
                QMessageBox.warning(self, "No project", "Open a project first.")
                return
            values = self._project_tab.collect_values()
            # Only write non-empty project overrides
            non_empty = {s: {k: v for k, v in kvs.items() if v != ""}
                         for s, kvs in values.items()}
            non_empty = {s: kvs for s, kvs in non_empty.items() if kvs}
            for section, kvs in non_empty.items():
                for key, val in kvs.items():
                    self._config.set_project(section, key, val)
            self._config.save_project()
            QMessageBox.information(self, "Saved", "Project config saved.")
            log.info("Project config saved: %s", self._project_dir)

    def _reload(self) -> None:
        self._rebuild_tabs()
        log.info("Settings reloaded from disk")
