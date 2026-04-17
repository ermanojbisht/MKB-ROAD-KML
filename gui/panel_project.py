"""
panel_project.py — Project management panel for MKB-ROAD-KML.

Responsibilities:
  - Create new project (name + folder picker)
  - Open existing project (picks a folder containing project.toml)
  - Display project file browser (KMLs, Excels with metadata)
  - KML upload button with geometry validator
  - Polygon warning flow (modal dialog with map preview)
  - Emits project_loaded signal so main_window can propagate context

Layout:
    ┌──────────────────────────────────────────────────────┐
    │  Project header bar  [Create] [Open] [Upload KML]    │
    ├──────────────────────────────────────────────────────┤
    │  File browser table                                   │
    │  (name | type | size | modified | actions)           │
    ├──────────────────────────────────────────────────────┤
    │  Map preview (shows selected KML)                    │
    └──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QDialogButtonBox, QLineEdit, QGroupBox, QGridLayout,
    QMessageBox, QSplitter, QFrame, QSizePolicy, QAbstractItemView,
)

from core.config_manager import ConfigManager
from core.kml_parser import (
    read_linestring, detect_geometry_types, KMLParseError,
)
from core.logger import get_logger
from gui.theme import apply_dark, splitter_style, alt_row_style, hint_style, status_style_ex

log = get_logger(__name__)

_PANEL_STYLE = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
QLabel#panelTitle {
    font-size: 18px; font-weight: bold; color: #cba6f7; padding-bottom: 4px;
}
QLabel#projectName {
    font-size: 14px; color: #a6e3a1; font-weight: bold;
}
QLabel#projectPath {
    font-size: 11px; color: #585b70;
}
QPushButton#primary {
    background: #cba6f7; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 7px 18px; font-size: 12px; font-weight: bold;
}
QPushButton#primary:hover { background: #d9b8ff; }
QPushButton#secondary {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 7px 18px; font-size: 12px;
}
QPushButton#secondary:hover { background: #3d3f55; }
QPushButton#danger {
    background: #f38ba8; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 7px 18px; font-size: 12px; font-weight: bold;
}
QPushButton#danger:hover { background: #f5a0b5; }
QTableWidget {
    background: #181825; color: #cdd6f4;
    border: 1px solid #313244; gridline-color: #313244;
    font-size: 12px; selection-background-color: #313244;
}
QTableWidget::item:selected { background: #313244; color: #cba6f7; }
QHeaderView::section {
    background: #1e1e2e; color: #a6adc8;
    padding: 6px; border: none; border-bottom: 1px solid #313244; font-size: 12px;
}
QFrame#separator { background: #313244; max-height: 1px; }
QLineEdit {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 6px 10px;
}
QGroupBox {
    color: #a6adc8; border: 1px solid #313244;
    border-radius: 6px; margin-top: 8px; padding: 8px; font-size: 12px;
}
QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
QLabel#noProject {
    color: #45475a; font-size: 16px;
}
"""


def _btn(text: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    return b


def _sep() -> QFrame:
    f = QFrame()
    f.setObjectName("separator")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


# ──────────────────────────────────────────────────────────────────────────────
# Create Project Dialog
# ──────────────────────────────────────────────────────────────────────────────

class CreateProjectDialog(QDialog):
    """Modal dialog to name + locate a new project folder."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Create New Project")
        self.setMinimumWidth(480)
        apply_dark(self, _PANEL_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Project name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g.  NH58_km42_to_km67")
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("Parent folder (project subfolder will be created here):"))
        row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("Click Browse…")
        browse = _btn("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self._folder_edit)
        row.addWidget(browse)
        layout.addLayout(row)

        self._preview_lbl = QLabel("")
        self._preview_lbl.setStyleSheet(hint_style("font-size: 11px;"))
        layout.addWidget(self._preview_lbl)

        self._name_edit.textChanged.connect(self._update_preview)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select parent folder", str(Path.home()))
        if folder:
            self._folder_edit.setText(folder)
            self._update_preview()

    def _update_preview(self) -> None:
        parent = self._folder_edit.text().strip()
        name = self._name_edit.text().strip()
        if parent and name:
            self._preview_lbl.setText(f"Will create: {parent}/{name}/")

    def _accept(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Required", "Please enter a project name.")
            return
        if not self._folder_edit.text().strip():
            QMessageBox.warning(self, "Required", "Please select a parent folder.")
            return
        self.accept()

    def project_name(self) -> str:
        return self._name_edit.text().strip()

    def parent_folder(self) -> Path:
        return Path(self._folder_edit.text().strip())


# ──────────────────────────────────────────────────────────────────────────────
# Polygon Warning Dialog
# ──────────────────────────────────────────────────────────────────────────────

class PolygonWarningDialog(QDialog):
    """Shown when an uploaded KML contains Polygon geometry."""

    def __init__(self, kml_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Polygon Geometry Detected")
        self.setMinimumSize(700, 500)
        apply_dark(self, _PANEL_STYLE)
        self._decision = "abort"

        layout = QVBoxLayout(self)

        warn_lbl = QLabel(
            f"⚠  The file <b>{kml_path.name}</b> contains <b>Polygon</b> geometry.\n\n"
            "MKB-ROAD-KML works with road <b>LineString</b> data. "
            "What would you like to do?"
        )
        warn_lbl.setWordWrap(True)
        warn_lbl.setStyleSheet(status_style_ex("warn", "font-size: 13px; padding: 8px 0;"))
        layout.addWidget(warn_lbl)

        # Map preview showing the polygon
        from gui.map_canvas import MapCanvas
        map_canvas = MapCanvas(self)
        map_canvas.setMinimumHeight(300)
        try:
            # Try to read any LineString for context; show polygon boundary via coords
            from lxml import etree
            NS = "http://www.opengis.net/kml/2.2"
            tree = etree.parse(str(kml_path))
            root = tree.getroot()
            poly_coords_el = root.find(f".//{{{NS}}}Polygon//{{{NS}}}coordinates")
            if poly_coords_el is not None:
                from core.kml_parser import _parse_coord_text
                coords = _parse_coord_text(poly_coords_el.text or "")
                if coords:
                    map_canvas.load_coords(coords, name="Polygon boundary", color="#f9e2af")
        except Exception:
            pass
        layout.addWidget(map_canvas)

        # Buttons
        btn_row = QHBoxLayout()
        skip_btn = _btn("Import LineStrings only (skip polygons)", "secondary")
        skip_btn.clicked.connect(self._skip)
        abort_btn = _btn("Abort — do not import", "danger")
        abort_btn.clicked.connect(self._abort)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(abort_btn)
        layout.addLayout(btn_row)

    def _skip(self) -> None:
        self._decision = "skip"
        self.accept()

    def _abort(self) -> None:
        self._decision = "abort"
        self.reject()

    def decision(self) -> str:
        return self._decision


# ──────────────────────────────────────────────────────────────────────────────
# Project Panel (main widget)
# ──────────────────────────────────────────────────────────────────────────────

class ProjectPanel(QWidget):
    """
    Projects page shown when user clicks 'Projects' in the sidebar.
    Manages create/open project and file browser.
    """

    project_loaded = pyqtSignal(Path)   # emitted when a project is loaded
    kml_selected = pyqtSignal(Path)     # emitted when user clicks a KML to preview

    def __init__(self, config: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._project_dir: Path | None = None

        apply_dark(self, _PANEL_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        # ── Header ──────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("Projects")
        title_lbl.setObjectName("panelTitle")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        create_btn = _btn("＋ New Project", "primary")
        open_btn   = _btn("📂 Open Project", "secondary")
        create_btn.clicked.connect(self._create_project)
        open_btn.clicked.connect(self._open_project)
        title_row.addWidget(create_btn)
        title_row.addWidget(open_btn)
        layout.addLayout(title_row)
        layout.addWidget(_sep())

        # ── Project info bar ────────────────────────────────────────
        self._proj_name_lbl = QLabel("No project open")
        self._proj_name_lbl.setObjectName("noProject")
        self._proj_path_lbl = QLabel("")
        self._proj_path_lbl.setObjectName("projectPath")

        info_row = QHBoxLayout()
        info_col = QVBoxLayout()
        info_col.addWidget(self._proj_name_lbl)
        info_col.addWidget(self._proj_path_lbl)
        info_row.addLayout(info_col)
        info_row.addStretch()

        self._upload_btn = _btn("⬆ Upload KML", "secondary")
        self._upload_btn.setEnabled(False)
        self._upload_btn.clicked.connect(self._upload_kml)
        info_row.addWidget(self._upload_btn)
        layout.addLayout(info_row)
        layout.addSpacing(8)

        # ── Splitter: file browser (top) + map preview (bottom) ─────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(splitter_style())

        self._file_table = self._build_file_table()
        splitter.addWidget(self._file_table)

        from gui.map_canvas import MapCanvas
        self._map = MapCanvas(self)
        splitter.addWidget(self._map)
        splitter.setSizes([300, 450])

        layout.addWidget(splitter, stretch=1)

    # ── File table ──────────────────────────────────────────────────

    def _build_file_table(self) -> QTableWidget:
        tbl = QTableWidget(0, 5)
        tbl.setHorizontalHeaderLabels(["Name", "Type", "Size", "Modified", "Location"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setAlternatingRowColors(True)
        tbl.setStyleSheet(alt_row_style())
        tbl.itemDoubleClicked.connect(self._on_file_double_clicked)
        tbl.itemClicked.connect(self._on_file_clicked)
        return tbl

    def _refresh_file_table(self) -> None:
        """Scan project folder and repopulate the file browser table."""
        self._file_table.setRowCount(0)
        if self._project_dir is None:
            return

        files: list[Path] = []
        for sub in ["sources", "intermediates", "output", "."]:
            folder = self._project_dir / sub if sub != "." else self._project_dir
            if folder.exists():
                for f in sorted(folder.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".kml", ".xlsx", ".xls", ".xlsm", ".toml"):
                        files.append(f)

        # Deduplicate (root-level files might overlap)
        seen: set[Path] = set()
        unique: list[Path] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)

        self._file_table.setRowCount(len(unique))
        for row, f in enumerate(unique):
            type_map = {".kml": "KML", ".xlsx": "Excel", ".xls": "Excel",
                        ".xlsm": "Excel", ".toml": "Config"}
            ftype = type_map.get(f.suffix.lower(), f.suffix)
            size_kb = f.stat().st_size / 1024
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            rel = f.relative_to(self._project_dir)

            items = [
                QTableWidgetItem(f.name),
                QTableWidgetItem(ftype),
                QTableWidgetItem(f"{size_kb:.1f} KB"),
                QTableWidgetItem(mtime),
                QTableWidgetItem(str(rel.parent)),
            ]
            color_map = {"KML": "#89b4fa", "Excel": "#a6e3a1", "Config": "#f9e2af"}
            for i, item in enumerate(items):
                if i == 0:
                    item.setForeground(QColor(color_map.get(ftype, "#cdd6f4")))
                self._file_table.setItem(row, i, item)
                item.setData(Qt.ItemDataRole.UserRole, str(f))

        log.debug("File browser refreshed: %d files in project", len(unique))

    # ── Create / open project ───────────────────────────────────────

    def _create_project(self) -> None:
        dlg = CreateProjectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        project_dir = dlg.parent_folder() / dlg.project_name()
        for sub in ["sources", "intermediates", "output"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        # Write project.toml
        toml_path = project_dir / "project.toml"
        toml_path.write_text(
            f'# MKB-ROAD-KML project: {dlg.project_name()}\n\n'
            f'[app]\nproject_name = "{dlg.project_name()}"\n'
        )

        log.info("Project created: %s", project_dir)
        self._load_project(project_dir)

    def _open_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Open Project Folder", str(Path.home())
        )
        if not folder:
            return
        project_dir = Path(folder)
        if not (project_dir / "project.toml").exists():
            QMessageBox.warning(
                self, "Not a project folder",
                f"No project.toml found in:\n{project_dir}\n\n"
                "Please select a folder created by MKB-ROAD-KML."
            )
            return
        self._load_project(project_dir)

    def load_project(self, project_dir: Path) -> None:
        """Public method — called from main_window for auto-reopen."""
        self._load_project(project_dir)

    def _load_project(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        name = project_dir.name
        self._proj_name_lbl.setText(name)
        self._proj_name_lbl.setObjectName("projectName")
        self._proj_name_lbl.setStyleSheet(status_style_ex("ok", "font-size: 14px; font-weight: bold;"))
        self._proj_path_lbl.setText(str(project_dir))
        self._upload_btn.setEnabled(True)
        self._refresh_file_table()

        # Save as last project
        self._config.set_last_project(str(project_dir))
        self._config.save_global()

        self.project_loaded.emit(project_dir)
        log.info("Project loaded: %s", project_dir)

    # ── KML upload ──────────────────────────────────────────────────

    def _upload_kml(self) -> None:
        if self._project_dir is None:
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Upload KML File(s)", str(Path.home()),
            "KML Files (*.kml);;All Files (*)"
        )
        if not paths:
            return

        for path_str in paths:
            self._process_kml_upload(Path(path_str))

        self._refresh_file_table()

    def _process_kml_upload(self, kml_path: Path) -> None:
        """Validate a KML file and copy it to sources/ if accepted."""
        # Validate XML and detect geometry
        try:
            geom_types = detect_geometry_types(kml_path)
        except KMLParseError as exc:
            QMessageBox.critical(
                self, "Invalid KML",
                f"Could not read {kml_path.name}:\n\n{exc}\n\n"
                "Please check the file is a valid KML."
            )
            return

        log.info("KML upload: %s — geometry types: %s", kml_path.name, geom_types)

        # Handle polygon warning
        if "Polygon" in geom_types:
            dlg = PolygonWarningDialog(kml_path, self)
            result = dlg.exec()
            if dlg.decision() == "abort":
                log.info("Upload aborted by user (polygon detected): %s", kml_path.name)
                return
            log.info("User chose to skip polygons for: %s", kml_path.name)

        if "LineString" not in geom_types and "Point" not in geom_types:
            QMessageBox.warning(
                self, "No usable geometry",
                f"{kml_path.name} contains no LineString or Point geometry.\n"
                "Nothing to import."
            )
            return

        # Copy to project sources/
        dest = self._project_dir / "sources" / kml_path.name
        if dest.exists():
            reply = QMessageBox.question(
                self, "File exists",
                f"{kml_path.name} already exists in sources/.\nOverwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        shutil.copy2(kml_path, dest)
        log.info("KML copied to: %s", dest)

        QMessageBox.information(
            self, "Upload complete",
            f"✓ {kml_path.name} imported to project sources/\n"
            f"Geometry: {', '.join(sorted(geom_types))}"
        )

    # ── File browser interactions ───────────────────────────────────

    def _on_file_clicked(self, item: QTableWidgetItem) -> None:
        """Single click — preview KML on map if it's a KML file."""
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".kml":
            return
        self._preview_kml(path)

    def _on_file_double_clicked(self, item: QTableWidgetItem) -> None:
        """Double click — open file in default system app."""
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if path_str:
            import sys
            if sys.platform == "win32":
                import os
                os.startfile(path_str)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path_str])

    def _preview_kml(self, kml_path: Path) -> None:
        """Load a KML file's coordinates onto the map canvas."""
        try:
            coords = read_linestring(kml_path)
            self._map.clear()
            self._map.load_coords(coords, name=kml_path.stem, color="#89b4fa")
            self.kml_selected.emit(kml_path)
            log.debug("Previewing KML: %s (%d pts)", kml_path.name, len(coords))
        except KMLParseError as exc:
            log.warning("Cannot preview %s: %s", kml_path.name, exc)

    @property
    def current_project_dir(self) -> Path | None:
        return self._project_dir
