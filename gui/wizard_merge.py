"""
wizard_merge.py — Merge Wizard for MKB-ROAD-KML.

4-step guided merge workflow:
  Step 1 — File selection: add KML files, reorder, preview on map
  Step 2 — Connection review: auto-detected joins, user overrides (reverse/trim)
  Step 3 — Dry run: merged result previewed on map
  Step 4 — Save: output name + project folder, write KML

Key design:
  - Visual-first: map canvas updated at every step
  - Direction arrows + colored segments + start/end dots
  - User can reverse any segment individually
  - Overlap trim slider per connection
  - Dry run shows merged line vs originals (faded)
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QListWidget, QListWidgetItem, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QGridLayout, QDoubleSpinBox, QCheckBox, QLineEdit,
    QSplitter, QFrame, QMessageBox, QAbstractItemView,
    QSizePolicy, QScrollArea,
)

from core.config_manager import ConfigManager
from core.kml_parser import read_linestring, write_kml, KMLParseError
from core.merger import (
    find_best_connection, apply_connection, chain_merge,
    reverse_coords, ConnectionInfo, MergeResult,
)
from core.logger import get_logger
from gui.theme import apply_dark, splitter_style, status_style

log = get_logger(__name__)

# Distinct colors for up to 6 segments
_SEG_COLORS = ["#e63946", "#2a9d8f", "#e9c46a", "#f4a261", "#264653", "#7b2d8b"]

_STYLE = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
QLabel#stepTitle { font-size: 18px; font-weight: bold; color: #cba6f7; padding-bottom: 4px; }
QLabel#stepSub   { font-size: 12px; color: #a6adc8; padding-bottom: 10px; }
QPushButton#primary {
    background: #cba6f7; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 8px 22px; font-weight: bold; font-size: 13px; min-width: 100px;
}
QPushButton#primary:hover   { background: #d9b8ff; }
QPushButton#primary:disabled{ background: #45475a; color: #585b70; }
QPushButton#secondary {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 8px 22px; font-size: 13px; min-width: 100px;
}
QPushButton#secondary:hover { background: #3d3f55; }
QPushButton#warn {
    background: #f9e2af; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 6px 14px; font-size: 12px;
}
QPushButton#warn:hover { background: #faecc8; }
QPushButton#small {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 4px; padding: 4px 10px; font-size: 11px;
}
QPushButton#small:hover { background: #3d3f55; }
QListWidget {
    background: #181825; color: #cdd6f4; border: 1px solid #313244;
    font-size: 12px;
}
QListWidget::item { padding: 6px 10px; }
QListWidget::item:selected { background: #313244; color: #cba6f7; }
QTableWidget {
    background: #181825; color: #cdd6f4; border: 1px solid #313244;
    gridline-color: #313244; font-size: 12px;
}
QTableWidget::item:selected { background: #313244; }
QHeaderView::section {
    background: #1e1e2e; color: #a6adc8;
    padding: 6px; border: none; border-bottom: 1px solid #313244; font-size: 12px;
}
QGroupBox {
    color: #a6adc8; border: 1px solid #313244;
    border-radius: 6px; margin-top: 8px; padding: 8px; font-size: 12px;
}
QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
QDoubleSpinBox {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 4px 6px;
}
QFrame#separator { background: #313244; max-height: 1px; }
QLineEdit {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 6px 10px;
}
QLabel#stat { color: #a6e3a1; font-size: 12px; padding: 2px 0; }
QLabel#warn { color: #f9e2af; font-size: 12px; padding: 2px 0; }
"""


def _btn(text: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    return b


def _title(t: str) -> QLabel:
    l = QLabel(t); l.setObjectName("stepTitle"); return l


def _sub(t: str) -> QLabel:
    l = QLabel(t); l.setObjectName("stepSub"); l.setWordWrap(True); return l


def _sep() -> QFrame:
    f = QFrame(); f.setObjectName("separator"); f.setFrameShape(QFrame.Shape.HLine); return f


class MergeWizard(QWidget):
    """4-step guided KML merge wizard."""

    def __init__(self, config: ConfigManager, project_dir: Path | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._project_dir: Path | None = project_dir

        # State
        self._kml_paths: list[Path] = []        # ordered list of files to merge
        self._connections: list[ConnectionInfo] = []   # auto-detected (may be overridden)
        self._reversed: list[bool] = []          # user-toggled reversals per segment
        self._trim_values: list[float] = []      # per-connection trim distance
        self._merge_result: MergeResult | None = None
        self._output_path: Path | None = None

        apply_dark(self, _STYLE)
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()

    def set_project_dir(self, project_dir: Path | None) -> None:
        self._project_dir = project_dir

    # ──────────────────────────────────────────────────────────────────
    # Step 1 — File selection + map preview
    # ──────────────────────────────────────────────────────────────────

    def _build_step1(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 1 of 4 — Select KML Files"))
        layout.addWidget(_sub(
            "Add the KML segments you want to merge. Use ↑ ↓ to set the merge order. "
            "Each segment is shown in a different colour on the map."
        ))
        layout.addWidget(_sep())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(splitter_style())

        # Left: file list + controls
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        self._s1_list = QListWidget()
        self._s1_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._s1_list.currentRowChanged.connect(self._s1_on_select)
        self._s1_list.model().rowsMoved.connect(self._s1_on_drag_reorder)
        left_layout.addWidget(self._s1_list, stretch=1)

        btn_row = QHBoxLayout()
        add_btn    = _btn("＋ Add KML", "primary")
        remove_btn = _btn("✕ Remove", "secondary")
        up_btn     = _btn("↑", "small")
        down_btn   = _btn("↓", "small")
        add_btn.clicked.connect(self._s1_add_files)
        remove_btn.clicked.connect(self._s1_remove)
        up_btn.clicked.connect(lambda: self._s1_move(-1))
        down_btn.clicked.connect(lambda: self._s1_move(1))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        left_layout.addLayout(btn_row)

        splitter.addWidget(left)

        # Right: map
        from gui.map_canvas import MapCanvas
        self._s1_map = MapCanvas(self)
        splitter.addWidget(self._s1_map)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

        nav = QHBoxLayout()
        self._s1_next = _btn("Next →", "primary")
        self._s1_next.setEnabled(False)
        self._s1_next.clicked.connect(self._s1_to_step2)
        nav.addStretch()
        nav.addWidget(self._s1_next)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _s1_add_files(self) -> None:
        start_dir = str(self._project_dir / "sources") if self._project_dir else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add KML Files", start_dir, "KML Files (*.kml);;All Files (*)"
        )
        for p in paths:
            path = Path(p)
            if path not in self._kml_paths:
                self._kml_paths.append(path)
                color = _SEG_COLORS[(len(self._kml_paths) - 1) % len(_SEG_COLORS)]
                item = QListWidgetItem(f"  {path.name}")
                item.setForeground(QColor(color))
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self._s1_list.addItem(item)
        self._s1_refresh_map()
        self._s1_next.setEnabled(len(self._kml_paths) >= 2)

    def _s1_remove(self) -> None:
        row = self._s1_list.currentRow()
        if row < 0:
            return
        self._s1_list.takeItem(row)
        self._kml_paths.pop(row)
        self._s1_refresh_map()
        self._s1_next.setEnabled(len(self._kml_paths) >= 2)

    def _s1_move(self, direction: int) -> None:
        row = self._s1_list.currentRow()
        new_row = row + direction
        if new_row < 0 or new_row >= self._s1_list.count():
            return
        item = self._s1_list.takeItem(row)
        self._s1_list.insertItem(new_row, item)
        self._s1_list.setCurrentRow(new_row)
        self._kml_paths.insert(new_row, self._kml_paths.pop(row))
        self._s1_refresh_map()

    def _s1_on_select(self, row: int) -> None:
        pass  # could highlight selected segment in map — future enhancement

    def _s1_on_drag_reorder(self) -> None:
        self._kml_paths = [
            Path(self._s1_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self._s1_list.count())
        ]
        self._s1_refresh_map()

    def _s1_refresh_map(self) -> None:
        self._s1_map.clear()
        for i, path in enumerate(self._kml_paths):
            try:
                coords = read_linestring(path)
                color = _SEG_COLORS[i % len(_SEG_COLORS)]
                self._s1_map.load_coords(coords, name=path.stem, color=color)
            except KMLParseError as e:
                log.warning("Cannot preview %s: %s", path.name, e)

    def _s1_to_step2(self) -> None:
        # Sync list order with _kml_paths (in case drag-drop reordered)
        self._kml_paths = []
        for i in range(self._s1_list.count()):
            item = self._s1_list.item(i)
            self._kml_paths.append(Path(item.data(Qt.ItemDataRole.UserRole)))

        # Read all coords
        try:
            self._all_coords = [read_linestring(p) for p in self._kml_paths]
        except KMLParseError as e:
            QMessageBox.critical(self, "KML Error", str(e))
            return

        # Auto-detect connections
        self._reversed = [False] * len(self._kml_paths)
        self._connections = []
        for i in range(len(self._kml_paths) - 1):
            c1 = reverse_coords(self._all_coords[i]) if self._reversed[i] else self._all_coords[i]
            c2 = reverse_coords(self._all_coords[i+1]) if self._reversed[i+1] else self._all_coords[i+1]
            conn = find_best_connection(c1, c2, self._kml_paths[i].stem, self._kml_paths[i+1].stem)
            self._connections.append(conn)
            # Apply connection reversals to the reversed state
            if conn.seg1_reversed:
                self._reversed[i] = not self._reversed[i]
            if conn.seg2_reversed:
                self._reversed[i+1] = not self._reversed[i+1]

        default_trim = self._config.get("merge", "overlap_trim_meters", 5.0)
        self._trim_values = [default_trim] * len(self._connections)

        self._populate_step2()
        self._stack.setCurrentIndex(1)

    # ──────────────────────────────────────────────────────────────────
    # Step 2 — Connection review + user overrides
    # ──────────────────────────────────────────────────────────────────

    def _build_step2(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 2 of 4 — Review Connections"))
        layout.addWidget(_sub(
            "Auto-detected connections shown below. "
            "Reverse any segment that points the wrong way. "
            "Adjust overlap trim to remove duplicate junction points."
        ))
        layout.addWidget(_sep())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet(splitter_style())

        # Left: controls panel (in a scroll area)
        left_inner = QWidget()
        left_layout = QVBoxLayout(left_inner)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # Segment reversal group
        self._s2_seg_group = QGroupBox("Segment directions")
        self._s2_seg_layout = QVBoxLayout(self._s2_seg_group)
        left_layout.addWidget(self._s2_seg_group)

        # Connection details group
        self._s2_conn_group = QGroupBox("Detected connections")
        self._s2_conn_layout = QGridLayout(self._s2_conn_group)
        left_layout.addWidget(self._s2_conn_group)

        left_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(left_inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(280)
        scroll.setMaximumWidth(420)
        splitter.addWidget(scroll)

        # Right: map
        from gui.map_canvas import MapCanvas
        self._s2_map = MapCanvas(self)
        splitter.addWidget(self._s2_map)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

        nav = QHBoxLayout()
        back_btn = _btn("← Back", "secondary")
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._s2_next = _btn("Dry Run →", "primary")
        self._s2_next.clicked.connect(self._s2_to_step3)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(self._s2_next)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step2(self) -> None:
        # Clear previous widgets
        for i in reversed(range(self._s2_seg_layout.count())):
            w = self._s2_seg_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        for i in reversed(range(self._s2_conn_layout.count())):
            w = self._s2_conn_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        self._s2_rev_btns: list[QPushButton] = []
        self._s2_rev_labels: list[QLabel] = []

        # Segment reversal buttons
        for i, path in enumerate(self._kml_paths):
            color = _SEG_COLORS[i % len(_SEG_COLORS)]
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            name_lbl = QLabel(f"<span style='color:{color}'>■</span>  {path.stem}")
            name_lbl.setTextFormat(Qt.TextFormat.RichText)
            status_lbl = QLabel("reversed ↺" if self._reversed[i] else "normal →")
            status_lbl.setStyleSheet(
                status_style("warn") if self._reversed[i] else status_style("ok")
            )
            rev_btn = _btn("Reverse ↺", "warn")
            rev_btn.setFixedWidth(90)

            seg_idx = i  # capture for lambda
            def make_toggle(idx):
                def toggle():
                    self._reversed[idx] = not self._reversed[idx]
                    self._s2_rev_labels[idx].setText(
                        "reversed ↺" if self._reversed[idx] else "normal →"
                    )
                    self._s2_rev_labels[idx].setStyleSheet(
                        status_style("warn") if self._reversed[idx] else status_style("ok")
                    )
                    self._s2_refresh_map()
                return toggle

            rev_btn.clicked.connect(make_toggle(seg_idx))
            self._s2_rev_btns.append(rev_btn)
            self._s2_rev_labels.append(status_lbl)

            row_layout.addWidget(name_lbl)
            row_layout.addStretch()
            row_layout.addWidget(status_lbl)
            row_layout.addWidget(rev_btn)
            self._s2_seg_layout.addWidget(row_widget)

        # Connection details + trim spinboxes
        self._s2_trim_spins: list[QDoubleSpinBox] = []
        headers = ["Connection", "Gap (m)", "Overlap trim (m)"]
        for col, h in enumerate(headers):
            lbl = QLabel(f"<b>{h}</b>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            self._s2_conn_layout.addWidget(lbl, 0, col)

        for i, conn in enumerate(self._connections):
            conn_lbl = QLabel(
                f"{self._kml_paths[i].stem} → {self._kml_paths[i+1].stem}"
            )
            gap_lbl = QLabel(f"{conn.junction_distance_m:.1f} m")
            if conn.junction_distance_m > 50:
                gap_lbl.setStyleSheet(status_style("error"))
            elif conn.junction_distance_m > 10:
                gap_lbl.setStyleSheet(status_style("warn"))
            else:
                gap_lbl.setStyleSheet(status_style("ok"))

            trim_spin = QDoubleSpinBox()
            trim_spin.setRange(0.0, 100.0)
            trim_spin.setSingleStep(1.0)
            trim_spin.setDecimals(1)
            trim_spin.setSuffix(" m")
            trim_spin.setValue(self._trim_values[i])
            idx = i
            trim_spin.valueChanged.connect(lambda v, x=idx: self._on_trim_changed(x, v))
            self._s2_trim_spins.append(trim_spin)

            row = i + 1
            self._s2_conn_layout.addWidget(conn_lbl, row, 0)
            self._s2_conn_layout.addWidget(gap_lbl,  row, 1)
            self._s2_conn_layout.addWidget(trim_spin, row, 2)

        self._s2_refresh_map()

    def _on_trim_changed(self, idx: int, value: float) -> None:
        self._trim_values[idx] = value

    def _s2_refresh_map(self) -> None:
        self._s2_map.clear()
        for i, (path, coords) in enumerate(zip(self._kml_paths, self._all_coords)):
            display = reverse_coords(coords) if self._reversed[i] else coords
            color = _SEG_COLORS[i % len(_SEG_COLORS)]
            self._s2_map.load_coords(display, name=path.stem, color=color)

    def _s2_to_step3(self) -> None:
        self._compute_merge()
        if self._merge_result:
            self._populate_step3()
            self._stack.setCurrentIndex(2)

    def _compute_merge(self) -> None:
        """Run the merge with current reversals + trim settings."""
        try:
            default_trim = self._config.get("merge", "overlap_trim_meters", 5.0)
            # Build adjusted segments (apply user reversals)
            segs = []
            for i, (path, coords) in enumerate(zip(self._kml_paths, self._all_coords)):
                c = reverse_coords(coords) if self._reversed[i] else list(coords)
                segs.append((path.stem, c))

            # Build override connections (re-detect with user reversals applied, use trim)
            overrides: list[ConnectionInfo] = []
            for i in range(len(segs) - 1):
                conn = find_best_connection(segs[i][1], segs[i+1][1], segs[i][0], segs[i+1][0])
                overrides.append(conn)

            # Patch trim values into config
            class TrimConfig:
                def __init__(self, base_cfg, trims):
                    self._base = base_cfg
                    self._trims = trims
                    self._current_pair = 0
                def get(self, section, key, fallback=None):
                    if section == "merge" and key == "overlap_trim_meters":
                        val = self._trims[self._current_pair] if self._current_pair < len(self._trims) else fallback
                        self._current_pair += 1
                        return val
                    return self._base.get(section, key, fallback)

            trim_cfg = TrimConfig(self._config, self._trim_values)
            self._merge_result = chain_merge(segs, trim_cfg, overrides=overrides)

            log.info(
                "Dry run: %d segments → %d points",
                len(segs), self._merge_result.total_output_points
            )
        except Exception as e:
            QMessageBox.critical(self, "Merge error", str(e))
            log.exception("Merge failed")
            self._merge_result = None

    # ──────────────────────────────────────────────────────────────────
    # Step 3 — Dry run preview
    # ──────────────────────────────────────────────────────────────────

    def _build_step3(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 3 of 4 — Dry Run Preview"))
        layout.addWidget(_sub(
            "Merged result shown in white. Original segments shown faded. "
            "Go back to adjust reversals or trim if the join looks wrong."
        ))
        layout.addWidget(_sep())

        # Stats panel
        stats_group = QGroupBox("Merge summary")
        stats_layout = QGridLayout(stats_group)
        self._s3_stats: list[QLabel] = []
        for i in range(6):
            lbl = QLabel("")
            lbl.setObjectName("stat")
            self._s3_stats.append(lbl)
            stats_layout.addWidget(lbl, i // 2, i % 2)
        layout.addWidget(stats_group)

        # Map
        from gui.map_canvas import MapCanvas
        self._s3_map = MapCanvas(self)
        self._s3_map.setMinimumHeight(380)
        layout.addWidget(self._s3_map, stretch=1)

        nav = QHBoxLayout()
        back_btn = _btn("← Back", "secondary")
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        confirm_btn = _btn("Confirm & Save →", "primary")
        confirm_btn.clicked.connect(self._s3_to_step4)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(confirm_btn)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step3(self) -> None:
        r = self._merge_result
        if not r:
            return

        # Stats
        stat_data = [
            f"Segments merged: {len(self._kml_paths)}",
            f"Input points: {r.total_input_points}",
            f"Output points: {r.total_output_points}",
            f"Point delta: {r.point_delta:+d}",
        ]
        for i, conn in enumerate(r.connections):
            stat_data.append(
                f"Junction {i+1} gap: {conn.junction_distance_m:.1f} m"
            )
        for i, lbl in enumerate(self._s3_stats):
            lbl.setText(stat_data[i] if i < len(stat_data) else "")

        # Map: faded originals + bright merged result
        self._s3_map.clear()
        for i, (path, coords) in enumerate(zip(self._kml_paths, self._all_coords)):
            display = reverse_coords(coords) if self._reversed[i] else coords
            color = _SEG_COLORS[i % len(_SEG_COLORS)]
            self._s3_map.load_coords(display, name=f"{path.stem} (original)", color=color)
        # Merged result in bright white
        self._s3_map.load_coords(r.coords, name="Merged result", color="#ffffff")

    def _s3_to_step4(self) -> None:
        self._populate_step4()
        self._stack.setCurrentIndex(3)

    # ──────────────────────────────────────────────────────────────────
    # Step 4 — Save
    # ──────────────────────────────────────────────────────────────────

    def _build_step4(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(8)

        layout.addWidget(_title("Step 4 of 4 — Save Merged KML"))
        layout.addWidget(_sub("Choose a filename and location for the merged KML."))
        layout.addWidget(_sep())
        layout.addSpacing(12)

        form = QGroupBox("Output settings")
        form_layout = QGridLayout(form)

        form_layout.addWidget(QLabel("Output filename:"), 0, 0)
        self._s4_name_edit = QLineEdit()
        self._s4_name_edit.setPlaceholderText("merged_road  (without .kml)")
        form_layout.addWidget(self._s4_name_edit, 0, 1)

        form_layout.addWidget(QLabel("Output folder:"), 1, 0)
        folder_row = QHBoxLayout()
        self._s4_folder_edit = QLineEdit()
        self._s4_folder_edit.setReadOnly(True)
        browse_btn = _btn("Browse…", "secondary")
        browse_btn.clicked.connect(self._s4_browse)
        folder_row.addWidget(self._s4_folder_edit)
        folder_row.addWidget(browse_btn)
        form_layout.addLayout(folder_row, 1, 1)

        layout.addWidget(form)

        self._s4_result_lbl = QLabel("")
        self._s4_result_lbl.setObjectName("stat")
        self._s4_result_lbl.setWordWrap(True)
        layout.addWidget(self._s4_result_lbl)
        layout.addStretch()

        nav = QHBoxLayout()
        back_btn = _btn("← Back", "secondary")
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))
        save_btn = _btn("💾 Save KML", "primary")
        save_btn.clicked.connect(self._s4_save)
        done_btn = _btn("Done — Merge Another", "secondary")
        done_btn.clicked.connect(self._reset)
        nav.addWidget(back_btn)
        nav.addStretch()
        nav.addWidget(save_btn)
        nav.addWidget(done_btn)
        layout.addLayout(nav)

        self._stack.addWidget(page)

    def _populate_step4(self) -> None:
        # Auto-generate a sensible name from the input files
        names = [p.stem for p in self._kml_paths]
        self._s4_name_edit.setText("_merged_".join(names[:2]) + ("_etc" if len(names) > 2 else ""))
        out_dir = (self._project_dir / "output") if self._project_dir else Path.home()
        self._s4_folder_edit.setText(str(out_dir))

    def _s4_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder",
            str(self._project_dir / "output") if self._project_dir else str(Path.home())
        )
        if folder:
            self._s4_folder_edit.setText(folder)

    def _s4_save(self) -> None:
        name = self._s4_name_edit.text().strip()
        folder = self._s4_folder_edit.text().strip()
        if not name or not folder:
            QMessageBox.warning(self, "Missing", "Please fill in filename and folder.")
            return

        fname = name if name.endswith(".kml") else name + ".kml"
        out = Path(folder) / fname
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            write_kml(
                out,
                self._merge_result.coords,
                name=name,
                line_color=self._config.get("output", "default_line_color", "ff0000ff"),
                line_width=int(self._config.get("output", "default_line_width", 4)),
                altitude_mode=self._config.get("output", "altitude_mode", "relativeToGround"),
            )
            self._output_path = out
            self._s4_result_lbl.setText(
                f"✓ Saved: {out}\n"
                f"✓ {self._merge_result.total_output_points} points total"
            )
            log.info("Merged KML saved: %s", out)
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def _reset(self) -> None:
        self._kml_paths.clear()
        self._s1_list.clear()
        self._connections.clear()
        self._reversed.clear()
        self._trim_values.clear()
        self._merge_result = None
        self._s1_map.clear()
        self._s1_next.setEnabled(False)
        self._stack.setCurrentIndex(0)
