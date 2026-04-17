"""
wizard_excel.py — Excel → KML multi-step wizard.

Steps:
  1. File picker + sheet selector
  2. Column mapping (auto-detect, manual override)
  3. Validation + dry run
  4. KML output — project folder creation
  5. Map preview
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStackedWidget, QLineEdit, QProgressBar,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QGroupBox,
    QGridLayout, QTextEdit, QSplitter,
)

from core.config_manager import ConfigManager
from core.excel_reader import (
    get_sheet_names, get_headers, auto_map_columns,
    validate_mapping, validate_data, extract_coordinates,
    ExcelReadError, ALL_FIELDS, REQUIRED_FIELDS,
)
from core.kml_parser import write_kml
from core.logger import get_logger
from gui.theme import apply_dark, alt_row_style, status_style

log = get_logger(__name__)

# Field display names for the mapping UI
_FIELD_LABELS = {
    "start_lat": "Start Latitude *",
    "start_lon": "Start Longitude *",
    "start_alt": "Start Altitude",
    "end_lat":   "End Latitude",
    "end_lon":   "End Longitude",
    "end_alt":   "End Altitude",
}

_REQUIRED_SPEC = """Required columns (minimum):
  • Start Latitude   — decimal degrees, range −90 to +90     (e.g. 28.610234)
  • Start Longitude  — decimal degrees, range −180 to +180   (e.g. 77.209456)

Optional but recommended:
  • Start Altitude   — metres above ground                   (e.g. 220.5)
  • End Latitude / End Longitude / End Altitude
      — if your data is segment-based (one row = one road segment),
        the End columns of the last row are used as the final KML point.

Tips:
  • Column names are matched automatically (case-insensitive, underscores ignored).
  • Coordinates must be decimal degrees — NOT degrees/minutes/seconds.
  • Do not use comma as decimal separator.
"""

_WIZARD_STYLE = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
QLabel { color: #cdd6f4; }
QLabel#stepTitle {
    font-size: 18px;
    font-weight: bold;
    color: #cba6f7;
    padding-bottom: 4px;
}
QLabel#stepSub {
    font-size: 12px;
    color: #a6adc8;
    padding-bottom: 12px;
}
QPushButton#primary {
    background: #cba6f7;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: bold;
    min-width: 100px;
}
QPushButton#primary:hover { background: #d9b8ff; }
QPushButton#primary:disabled { background: #45475a; color: #585b70; }
QPushButton#secondary {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 24px;
    font-size: 13px;
    min-width: 100px;
}
QPushButton#secondary:hover { background: #3d3f55; }
QLineEdit {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
}
QComboBox {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox QAbstractItemView {
    background: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
}
QTableWidget {
    background: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    gridline-color: #313244;
    font-size: 12px;
}
QTableWidget::item:selected { background: #313244; }
QHeaderView::section {
    background: #1e1e2e;
    color: #a6adc8;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #313244;
    font-size: 12px;
}
QTextEdit#specBox {
    background: #181825;
    color: #a6e3a1;
    font-family: monospace;
    font-size: 11px;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 8px;
}
QGroupBox {
    color: #a6adc8;
    border: 1px solid #313244;
    border-radius: 6px;
    margin-top: 8px;
    padding: 8px;
    font-size: 12px;
}
QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
QFrame#separator { background: #313244; max-height: 1px; }
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 6px;
}
QProgressBar::chunk { background: #cba6f7; border-radius: 4px; }
"""


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("stepTitle")
    return lbl


def _sub(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("stepSub")
    lbl.setWordWrap(True)
    return lbl


def _sep() -> QFrame:
    f = QFrame()
    f.setObjectName("separator")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


def _btn(text: str, primary: bool = True) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primary" if primary else "secondary")
    return b


class ExcelKmlWizard(QWidget):
    """5-step wizard: Excel → KML with guided column mapping and preview."""

    def __init__(self, config: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._excel_path: Path | None = None
        self._sheet_name: str = ""
        self._headers: list[str] = []
        self._mapping: dict[str, str] = {}
        self._coords: list = []
        self._output_kml: Path | None = None
        self._project_dir: Path | None = None

        apply_dark(self, _WIZARD_STYLE)
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        self._build_step5()

    # ------------------------------------------------------------------
    # Step 1 — File picker + sheet selector
    # ------------------------------------------------------------------

    def _build_step1(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 1 of 5 — Load Excel File"))
        layout.addWidget(_sub("Select the Excel file containing your GPS road survey data."))
        layout.addWidget(_sep())
        layout.addSpacing(8)

        # Spec box
        spec_group = QGroupBox("Required column format")
        sg_layout = QVBoxLayout(spec_group)
        spec_box = QTextEdit()
        spec_box.setObjectName("specBox")
        spec_box.setReadOnly(True)
        spec_box.setPlainText(_REQUIRED_SPEC)
        spec_box.setFixedHeight(160)
        sg_layout.addWidget(spec_box)
        layout.addWidget(spec_group)
        layout.addSpacing(16)

        # File picker
        file_group = QGroupBox("Excel file")
        fg_layout = QHBoxLayout(file_group)
        self._s1_path_edit = QLineEdit()
        self._s1_path_edit.setPlaceholderText("Click Browse to select file…")
        self._s1_path_edit.setReadOnly(True)
        browse_btn = _btn("Browse…", primary=False)
        browse_btn.clicked.connect(self._s1_browse)
        fg_layout.addWidget(self._s1_path_edit)
        fg_layout.addWidget(browse_btn)
        layout.addWidget(file_group)

        # Sheet selector (hidden until file loaded)
        self._s1_sheet_group = QGroupBox("Select sheet")
        sg2 = QHBoxLayout(self._s1_sheet_group)
        self._s1_sheet_combo = QComboBox()
        self._s1_sheet_combo.setMinimumWidth(200)
        sg2.addWidget(QLabel("Sheet:"))
        sg2.addWidget(self._s1_sheet_combo)
        sg2.addStretch()
        self._s1_sheet_group.setVisible(False)
        layout.addWidget(self._s1_sheet_group)

        layout.addStretch()

        nav = QHBoxLayout()
        self._s1_next = _btn("Next →")
        self._s1_next.setEnabled(False)
        self._s1_next.clicked.connect(self._s1_to_step2)
        nav.addStretch()
        nav.addWidget(self._s1_next)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _s1_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Excel File", str(Path.home()),
            "Excel Files (*.xlsx *.xls *.xlsm);;All Files (*)"
        )
        if not path:
            return
        self._excel_path = Path(path)
        self._s1_path_edit.setText(str(self._excel_path))
        try:
            sheets = get_sheet_names(self._excel_path)
        except ExcelReadError as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        self._s1_sheet_combo.clear()
        for s in sheets:
            self._s1_sheet_combo.addItem(s)

        if len(sheets) > 1:
            self._s1_sheet_group.setVisible(True)
        else:
            self._s1_sheet_group.setVisible(False)

        self._s1_next.setEnabled(True)
        log.info("File loaded: %s (%d sheets)", self._excel_path.name, len(sheets))

    def _s1_to_step2(self) -> None:
        self._sheet_name = self._s1_sheet_combo.currentText()
        try:
            self._headers = get_headers(self._excel_path, self._sheet_name)
            self._mapping = auto_map_columns(self._headers)
        except ExcelReadError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self._populate_step2()
        self._stack.setCurrentIndex(1)

    # ------------------------------------------------------------------
    # Step 2 — Column mapping
    # ------------------------------------------------------------------

    def _build_step2(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 2 of 5 — Map Columns"))
        layout.addWidget(_sub(
            "Auto-detected mappings are shown below. "
            "If a column is wrong or missing, select the correct one from the dropdown. "
            "Fields marked * are required."
        ))
        layout.addWidget(_sep())
        layout.addSpacing(8)

        # Mapping grid
        self._s2_combos: dict[str, QComboBox] = {}
        grid = QGroupBox("Column mapping")
        grid_layout = QGridLayout(grid)
        grid_layout.setColumnStretch(1, 1)

        for row, field in enumerate(ALL_FIELDS):
            label_text = _FIELD_LABELS.get(field, field)
            lbl = QLabel(label_text)
            combo = QComboBox()
            combo.setObjectName(f"combo_{field}")
            self._s2_combos[field] = combo
            status_lbl = QLabel("")
            status_lbl.setObjectName(f"status_{field}")
            grid_layout.addWidget(lbl, row, 0)
            grid_layout.addWidget(combo, row, 1)
            grid_layout.addWidget(status_lbl, row, 2)

        scroll = QScrollArea()
        scroll.setWidget(grid)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll, stretch=1)

        nav = QHBoxLayout()
        back_btn = _btn("← Back", primary=False)
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._s2_next = _btn("Validate →")
        self._s2_next.clicked.connect(self._s2_to_step3)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(self._s2_next)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step2(self) -> None:
        """Fill combos with current headers and pre-select auto-mapped values."""
        none_option = "— not mapped —"
        for field, combo in self._s2_combos.items():
            combo.clear()
            combo.addItem(none_option)
            for h in self._headers:
                combo.addItem(h)
            # Pre-select auto-mapped value
            mapped_col = self._mapping.get(field, "")
            if mapped_col and mapped_col in self._headers:
                idx = self._headers.index(mapped_col) + 1  # +1 for none option
                combo.setCurrentIndex(idx)
                # Show green tick
                status = self.findChild(QLabel, f"status_{field}")
                if status:
                    status.setText("✓")
                    status.setStyleSheet(status_style("ok"))
            else:
                combo.setCurrentIndex(0)
                status = self.findChild(QLabel, f"status_{field}")
                if status:
                    if field in REQUIRED_FIELDS:
                        status.setText("⚠")
                        status.setStyleSheet(status_style("warn"))
                    else:
                        status.setText("–")
                        status.setStyleSheet(status_style("hint"))

    def _s2_collect_mapping(self) -> dict[str, str]:
        mapping = {}
        none_option = "— not mapped —"
        for field, combo in self._s2_combos.items():
            val = combo.currentText()
            if val != none_option:
                mapping[field] = val
        return mapping

    def _s2_to_step3(self) -> None:
        self._mapping = self._s2_collect_mapping()
        missing = validate_mapping(self._mapping)
        if missing:
            names = [_FIELD_LABELS.get(f, f) for f in missing]
            QMessageBox.warning(
                self, "Required fields missing",
                f"Please map these required fields:\n• " + "\n• ".join(names)
            )
            return
        self._populate_step3()
        self._stack.setCurrentIndex(2)

    # ------------------------------------------------------------------
    # Step 3 — Validation + dry run
    # ------------------------------------------------------------------

    def _build_step3(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 3 of 5 — Validate Data"))
        self._s3_sub = _sub("Checking your data…")
        layout.addWidget(self._s3_sub)
        layout.addWidget(_sep())
        layout.addSpacing(8)

        # Summary row
        sum_row = QHBoxLayout()
        self._s3_rows_lbl = QLabel("Rows: —")
        self._s3_coords_lbl = QLabel("Coordinates: —")
        self._s3_errors_lbl = QLabel("")
        sum_row.addWidget(self._s3_rows_lbl)
        sum_row.addWidget(self._s3_coords_lbl)
        sum_row.addWidget(self._s3_errors_lbl)
        sum_row.addStretch()
        layout.addLayout(sum_row)
        layout.addSpacing(8)

        # Issues table
        self._s3_table = QTableWidget(0, 4)
        self._s3_table.setHorizontalHeaderLabels(["Row", "Field", "Column", "Issue"])
        self._s3_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._s3_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._s3_table.setAlternatingRowColors(True)
        self._s3_table.setStyleSheet(alt_row_style())
        layout.addWidget(self._s3_table)
        layout.addStretch()

        nav = QHBoxLayout()
        back_btn = _btn("← Back", primary=False)
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        self._s3_next = _btn("Generate KML →")
        self._s3_next.clicked.connect(self._s3_to_step4)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(self._s3_next)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step3(self) -> None:
        issues = validate_data(self._excel_path, self._sheet_name, self._mapping)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        # Try to extract coords for count
        try:
            coords = extract_coordinates(self._excel_path, self._sheet_name, self._mapping)
            self._coords = coords
            self._s3_coords_lbl.setText(f"Coordinates: {len(coords)}")
        except ExcelReadError:
            self._coords = []
            self._s3_coords_lbl.setText("Coordinates: —")

        self._s3_rows_lbl.setText(f"Data rows read successfully")

        if errors:
            self._s3_errors_lbl.setText(
                f"⚠ {len(errors)} error(s), {len(warnings)} warning(s) — fix before proceeding"
            )
            self._s3_errors_lbl.setStyleSheet(status_style("error") + " font-weight: bold;")
            self._s3_next.setEnabled(False)
        elif warnings:
            self._s3_errors_lbl.setText(
                f"✓ {len(warnings)} warning(s) — you may proceed"
            )
            self._s3_errors_lbl.setStyleSheet(status_style("warn"))
            self._s3_next.setEnabled(True)
        else:
            self._s3_errors_lbl.setText("✓ All checks passed")
            self._s3_errors_lbl.setStyleSheet(status_style("ok") + " font-weight: bold;")
            self._s3_next.setEnabled(True)

        # Fill table
        self._s3_table.setRowCount(len(issues))
        for r, issue in enumerate(issues):
            row_item = QTableWidgetItem(str(issue.row) if issue.row else "—")
            row_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            field_item = QTableWidgetItem(_FIELD_LABELS.get(issue.field, issue.field))
            col_item = QTableWidgetItem(issue.column)
            msg_item = QTableWidgetItem(issue.message)

            color = "#f38ba8" if issue.severity == "error" else "#f9e2af"
            for item in [row_item, field_item, col_item, msg_item]:
                item.setForeground(QColor(color))

            self._s3_table.setItem(r, 0, row_item)
            self._s3_table.setItem(r, 1, field_item)
            self._s3_table.setItem(r, 2, col_item)
            self._s3_table.setItem(r, 3, msg_item)

        self._s3_sub.setText(
            "Data validation complete. Review any issues below. "
            "Errors must be fixed (go back to remap). Warnings can be accepted."
        )

    def _s3_to_step4(self) -> None:
        self._populate_step4()
        self._stack.setCurrentIndex(3)

    # ------------------------------------------------------------------
    # Step 4 — KML output + project folder
    # ------------------------------------------------------------------

    def _build_step4(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 4 of 5 — Save KML"))
        layout.addWidget(_sub(
            "Choose a project name and output folder. "
            "A project folder will be created with your KML file inside."
        ))
        layout.addWidget(_sep())
        layout.addSpacing(12)

        form = QGroupBox("Project settings")
        form_layout = QGridLayout(form)

        form_layout.addWidget(QLabel("Project name:"), 0, 0)
        self._s4_name_edit = QLineEdit()
        self._s4_name_edit.setPlaceholderText("e.g. NH58_km42_to_km67")
        form_layout.addWidget(self._s4_name_edit, 0, 1)

        form_layout.addWidget(QLabel("Output folder:"), 1, 0)
        folder_row = QHBoxLayout()
        self._s4_folder_edit = QLineEdit()
        self._s4_folder_edit.setPlaceholderText("Click Browse to select…")
        self._s4_folder_edit.setReadOnly(True)
        folder_btn = _btn("Browse…", primary=False)
        folder_btn.clicked.connect(self._s4_browse_folder)
        folder_row.addWidget(self._s4_folder_edit)
        folder_row.addWidget(folder_btn)
        form_layout.addLayout(folder_row, 1, 1)

        form_layout.addWidget(QLabel("KML name:"), 2, 0)
        self._s4_kml_name_edit = QLineEdit()
        self._s4_kml_name_edit.setPlaceholderText("road_path  (without .kml)")
        form_layout.addWidget(self._s4_kml_name_edit, 2, 1)

        layout.addWidget(form)

        self._s4_summary = QLabel("")
        self._s4_summary.setWordWrap(True)
        self._s4_summary.setStyleSheet(status_style("ok") + " font-size: 12px; padding: 8px 0;")
        layout.addWidget(self._s4_summary)
        layout.addStretch()

        nav = QHBoxLayout()
        back_btn = _btn("← Back", primary=False)
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))
        self._s4_generate = _btn("Generate KML")
        self._s4_generate.clicked.connect(self._s4_generate_kml)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(self._s4_generate)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step4(self) -> None:
        if self._excel_path:
            self._s4_name_edit.setText(self._excel_path.stem)
            self._s4_kml_name_edit.setText("road_path")
            self._s4_folder_edit.setText(str(self._excel_path.parent))

    def _s4_browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(Path.home())
        )
        if folder:
            self._s4_folder_edit.setText(folder)

    def _s4_generate_kml(self) -> None:
        project_name = self._s4_name_edit.text().strip()
        output_folder = self._s4_folder_edit.text().strip()
        kml_name = self._s4_kml_name_edit.text().strip() or "road_path"

        if not project_name:
            QMessageBox.warning(self, "Missing", "Please enter a project name.")
            return
        if not output_folder:
            QMessageBox.warning(self, "Missing", "Please select an output folder.")
            return

        # Create project folder structure
        project_dir = Path(output_folder) / project_name
        for sub in ["sources", "intermediates", "output"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        # Copy source Excel
        if self._excel_path:
            dest_excel = project_dir / "sources" / self._excel_path.name
            if not dest_excel.exists():
                shutil.copy2(self._excel_path, dest_excel)

        # Create project.toml
        proj_toml = project_dir / "project.toml"
        if not proj_toml.exists():
            proj_toml.write_text(
                f'# Project: {project_name}\n'
                f'# Created from: {self._excel_path.name if self._excel_path else ""}\n\n'
                f'[app]\nproject_name = "{project_name}"\n'
            )

        # Write KML
        kml_file = kml_name if kml_name.endswith(".kml") else kml_name + ".kml"
        output_path = project_dir / "output" / kml_file

        try:
            write_kml(
                output_path,
                self._coords,
                name=project_name,
                line_color=self._config.get("output", "default_line_color", "ff0000ff"),
                line_width=int(self._config.get("output", "default_line_width", 4)),
                altitude_mode=self._config.get("output", "altitude_mode", "relativeToGround"),
            )
        except Exception as e:
            QMessageBox.critical(self, "Error writing KML", str(e))
            return

        self._output_kml = output_path
        self._project_dir = project_dir

        # Update global config with last project
        self._config.set_last_project(str(project_dir))
        self._config.save_global()

        self._s4_summary.setText(
            f"✓ Project created: {project_dir}\n"
            f"✓ KML saved: {output_path}\n"
            f"✓ {len(self._coords)} coordinate points"
        )
        log.info("KML generated: %s (%d points)", output_path, len(self._coords))

        self._populate_step5()
        self._stack.setCurrentIndex(4)

    # ------------------------------------------------------------------
    # Step 5 — Map preview
    # ------------------------------------------------------------------

    def _build_step5(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 5 of 5 — Preview"))
        self._s5_sub = _sub("Your KML file has been generated. Preview the road line on the map below.")
        layout.addWidget(self._s5_sub)
        layout.addWidget(_sep())
        layout.addSpacing(8)

        from gui.map_canvas import MapCanvas
        self._s5_map = MapCanvas(self)
        self._s5_map.setMinimumHeight(400)
        layout.addWidget(self._s5_map, stretch=1)
        layout.addSpacing(8)

        nav = QHBoxLayout()
        open_btn = _btn("Open Project Folder", primary=False)
        open_btn.clicked.connect(self._s5_open_folder)
        new_btn = _btn("Convert Another File", primary=False)
        new_btn.clicked.connect(self._reset_wizard)
        done_btn = _btn("Done ✓")
        done_btn.clicked.connect(self._reset_wizard)

        nav.addWidget(open_btn)
        nav.addStretch()
        nav.addWidget(new_btn)
        nav.addWidget(done_btn)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step5(self) -> None:
        self._s5_map.clear()
        if self._coords:
            self._s5_map.load_coords(
                self._coords,
                name=self._s4_name_edit.text().strip() or "Road Path",
                color="#e63946",
            )
        if self._output_kml:
            self._s5_sub.setText(
                f"KML saved to: {self._output_kml}\n"
                f"Project folder: {self._project_dir}"
            )

    def _s5_open_folder(self) -> None:
        if self._project_dir and self._project_dir.exists():
            import sys
            if sys.platform == "win32":
                import os
                os.startfile(str(self._project_dir))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(self._project_dir)])

    def _reset_wizard(self) -> None:
        self._excel_path = None
        self._sheet_name = ""
        self._headers = []
        self._mapping = {}
        self._coords = []
        self._output_kml = None
        self._project_dir = None
        self._s1_path_edit.clear()
        self._s1_sheet_group.setVisible(False)
        self._s1_next.setEnabled(False)
        self._stack.setCurrentIndex(0)
