"""
main_window.py — MKB-ROAD-KML main application window.

Layout:
    ┌─────────────┬──────────────────────────────────────────┐
    │  Sidebar    │  Content Panel (stacked pages)           │
    │  Nav items  │                                          │
    │             │                                          │
    ├─────────────┴──────────────────────────────────────────┤
    │  Status bar + collapsible log viewer                   │
    └────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QListWidget, QListWidgetItem,
    QStatusBar, QLabel, QSplitter, QTextEdit, QPushButton,
    QFrame, QSizePolicy,
)

from core.config_manager import ConfigManager
from core.logger import get_logger
from gui.theme import apply_dark, splitter_style, log_bar_style, placeholder_style

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Navigation page indices
PAGE_EXCEL_WIZARD = 0
PAGE_PROJECTS = 1
PAGE_MERGE = 2
PAGE_EDIT = 3
PAGE_SETTINGS = 4

_NAV_ITEMS = [
    ("📄  Excel → KML", PAGE_EXCEL_WIZARD),
    ("📁  Projects",    PAGE_PROJECTS),
    ("🔗  Merge",       PAGE_MERGE),
    ("✏️   Edit",        PAGE_EDIT),
    ("⚙️   Settings",    PAGE_SETTINGS),
]

_APP_STYLE = """
QMainWindow { background: #1e1e2e; }
QWidget#sidebar {
    background: #181825;
}
QPushButton#collapseBtn {
    background: #181825;
    color: #585b70;
    border: none;
    border-top: 1px solid #313244;
    font-size: 14px;
    padding: 8px;
}
QPushButton#collapseBtn:hover { color: #cba6f7; }
QListWidget#navList {
    background: #181825;
    border: none;
    color: #cdd6f4;
    font-size: 13px;
    outline: none;
}
QListWidget#navList::item {
    padding: 12px 16px;
    border-radius: 6px;
    margin: 2px 6px;
}
QListWidget#navList::item:selected {
    background: #313244;
    color: #cba6f7;
}
QListWidget#navList::item:hover:!selected {
    background: #262637;
}
QLabel#appTitle {
    color: #cba6f7;
    font-size: 14px;
    font-weight: bold;
    padding: 16px 16px 8px 16px;
}
QLabel#appVersion {
    color: #585b70;
    font-size: 10px;
    padding: 0 16px 12px 16px;
}
QWidget#contentArea {
    background: #1e1e2e;
}
QStatusBar {
    background: #181825;
    color: #a6adc8;
    font-size: 11px;
    border-top: 1px solid #313244;
}
QTextEdit#logViewer {
    background: #11111b;
    color: #a6e3a1;
    font-family: monospace;
    font-size: 11px;
    border: none;
    border-top: 1px solid #313244;
}
QPushButton#logToggle {
    background: #181825;
    color: #585b70;
    border: none;
    font-size: 10px;
    padding: 2px 8px;
}
QPushButton#logToggle:hover { color: #a6adc8; }
"""


class QtLogHandler(logging.Handler):
    """Forwards log records to a QTextEdit widget."""

    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self._edit = text_edit
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                                             datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        color = {
            "DEBUG":   "#585b70",
            "INFO":    "#a6e3a1",
            "WARNING": "#f9e2af",
            "ERROR":   "#f38ba8",
            "CRITICAL":"#f38ba8",
        }.get(record.levelname, "#cdd6f4")
        html = f'<span style="color:{color}">{msg}</span>'
        # Must run on GUI thread
        self._edit.append(html)
        self._edit.verticalScrollBar().setValue(
            self._edit.verticalScrollBar().maximum()
        )


class MainWindow(QMainWindow):

    page_changed = pyqtSignal(int)

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self._setup_window()
        self._build_ui()
        self._attach_log_handler()
        log.info("MKB-ROAD-KML started — version %s",
                 config.get("app", "version", "0.1.0"))

        # Auto-reopen last project after window is shown
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, self._auto_reopen_last_project)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("MKB-ROAD-KML")
        w = self._config.get("ui", "window_width", 1280)
        h = self._config.get("ui", "window_height", 800)
        self.resize(w, h)
        apply_dark(self, _APP_STYLE)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Top: sidebar + content ────────────────────────────────────
        self._sidebar_collapsed = False
        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter = self._top_splitter
        top_splitter.setHandleWidth(1)
        top_splitter.setStyleSheet(splitter_style())

        self._sidebar = self._build_sidebar()
        self._stack = self._build_content_stack()

        top_splitter.addWidget(self._sidebar)
        top_splitter.addWidget(self._stack)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)

        # ── Bottom: log viewer (collapsible) ─────────────────────────
        self._log_viewer = QTextEdit()
        self._log_viewer.setObjectName("logViewer")
        self._log_viewer.setReadOnly(True)
        self._log_viewer.setMinimumHeight(120)
        self._log_viewer.setMaximumHeight(300)
        self._log_viewer.setVisible(False)

        log_bar = QWidget()
        log_bar.setObjectName("logBar")
        log_bar.setStyleSheet(log_bar_style())
        lb_layout = QHBoxLayout(log_bar)
        lb_layout.setContentsMargins(4, 0, 4, 0)
        self._log_toggle = QPushButton("▲ Logs")
        self._log_toggle.setObjectName("logToggle")
        self._log_toggle.setCheckable(True)
        self._log_toggle.toggled.connect(self._toggle_log)
        lb_layout.addWidget(self._log_toggle)
        lb_layout.addStretch()

        root_layout.addWidget(top_splitter, stretch=1)
        root_layout.addWidget(log_bar)
        root_layout.addWidget(self._log_viewer)

        # ── Status bar ───────────────────────────────────────────────
        self._status_label = QLabel("Ready")
        self.statusBar().addWidget(self._status_label)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar_title = QLabel("MKB-ROAD-KML")
        self._sidebar_title.setObjectName("appTitle")
        self._sidebar_version = QLabel(f"v{self._config.get('app', 'version', '0.1.0')}")
        self._sidebar_version.setObjectName("appVersion")

        self._nav = QListWidget()
        self._nav.setObjectName("navList")
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for label, _ in _NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().__class__(180, 44))
            self._nav.addItem(item)

        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_nav_changed)

        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setObjectName("collapseBtn")
        self._collapse_btn.clicked.connect(self._toggle_sidebar)

        layout.addWidget(self._sidebar_title)
        layout.addWidget(self._sidebar_version)
        layout.addWidget(self._nav)
        layout.addStretch()
        layout.addWidget(self._collapse_btn)
        return sidebar

    def _build_content_stack(self) -> QStackedWidget:
        stack = QStackedWidget()
        stack.setObjectName("contentArea")

        # PAGE 0: Excel → KML Wizard
        from gui.wizard_excel import ExcelKmlWizard
        self._excel_wizard = ExcelKmlWizard(self._config, self)
        stack.addWidget(self._excel_wizard)

        # PAGE 1: Projects panel (Phase 3)
        from gui.panel_project import ProjectPanel
        self._project_panel = ProjectPanel(self._config, self)
        self._project_panel.project_loaded.connect(self._on_project_loaded)
        stack.addWidget(self._project_panel)

        # PAGE 2: Merge Wizard (Phase 4)
        from gui.wizard_merge import MergeWizard
        self._merge_wizard = MergeWizard(self._config, parent=self)
        stack.addWidget(self._merge_wizard)

        # PAGE 3: Edit & Re-process (Phase 5)
        from gui.panel_edit import EditPanel
        self._edit_panel = EditPanel(self._config, self)
        stack.addWidget(self._edit_panel)

        # PAGE 4: Settings panel (Phase 3)
        from gui.panel_settings import SettingsPanel
        self._settings_panel = SettingsPanel(self._config, self)
        stack.addWidget(self._settings_panel)

        return stack

    def _make_placeholder(self, text: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(placeholder_style(20))
        layout.addWidget(lbl)
        return w

    def _attach_log_handler(self) -> None:
        handler = QtLogHandler(self._log_viewer)
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_nav_changed(self, row: int) -> None:
        self._stack.setCurrentIndex(row)
        self.page_changed.emit(row)

    def _toggle_log(self, checked: bool) -> None:
        self._log_viewer.setVisible(checked)
        self._log_toggle.setText("▼ Logs" if checked else "▲ Logs")

    def _toggle_sidebar(self) -> None:
        if self._sidebar_collapsed:
            self._sidebar_title.setVisible(True)
            self._sidebar_version.setVisible(True)
            self._nav.setVisible(True)
            self._sidebar.setFixedWidth(180)
            self._collapse_btn.setText("◀")
        else:
            self._sidebar_title.setVisible(False)
            self._sidebar_version.setVisible(False)
            self._nav.setVisible(False)
            self._sidebar.setFixedWidth(40)
            self._collapse_btn.setText("▶")
        self._sidebar_collapsed = not self._sidebar_collapsed

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_project_loaded(self, project_dir) -> None:
        """Called when ProjectPanel loads a project — propagate to all panels."""
        from pathlib import Path
        p = Path(project_dir)
        self._settings_panel.set_project(p)
        self._merge_wizard.set_project_dir(p)
        self.set_status(f"Project: {p.name}")
        log.info("Active project set: %s", project_dir)

    def _auto_reopen_last_project(self) -> None:
        """Reopen the last used project on startup if it still exists."""
        last = self._config.get("app", "last_project", "")
        if not last:
            return
        from pathlib import Path
        project_dir = Path(last)
        if project_dir.exists() and (project_dir / "project.toml").exists():
            log.info("Auto-reopening last project: %s", project_dir)
            self._project_panel.load_project(project_dir)
            # Switch to Projects page
            self._nav.setCurrentRow(PAGE_PROJECTS)
        else:
            log.debug("Last project not found, skipping auto-reopen: %s", last)
