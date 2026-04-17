"""
panel_edit.py — Edit & Re-process panel for MKB-ROAD-KML.

Left panel (scrollable):
  • Load KML File     — browse + load + map preview
  • Metadata Editor   — name, description, line color, line width, altitude mode
  • Re-process        — simplify / densify / chainage with per-op parameter
                        overrides, dry-run preview on map, then save

Right panel:
  • MapCanvas showing original (blue) and/or re-processed (white) line

Version history:
  Before any overwrite the existing file is backed up automatically as
  <stem>_v1.kml, <stem>_v2.kml, … (incrementing until a free slot is found).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QGridLayout, QCheckBox,
    QDoubleSpinBox, QSpinBox, QFrame, QFileDialog, QMessageBox,
    QScrollArea, QSplitter, QSizePolicy,
)

from core.config_manager import ConfigManager
from core.kml_parser import (
    read_linestring, read_kml_meta, write_kml,
    KMLParseError, Coord, ChainagePlacemark,
)
from core.geometry import simplify, densify, compute_chainage
from core.logger import get_logger
from gui.map_canvas import MapCanvas
from gui.theme import apply_dark, splitter_style, scroll_area_style, container_style

log = get_logger(__name__)

# ── Stylesheet ──────────────────────────────────────────────────────────────

_STYLE = """
QWidget { background: #1e1e2e; color: #cdd6f4; }
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
    font-size: 12px;
}
QLineEdit:focus { border-color: #cba6f7; }
QLineEdit:disabled { background: #252535; color: #45475a; }
QComboBox {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 4px 8px;
}
QComboBox QAbstractItemView { background: #313244; color: #cdd6f4; }
QComboBox:disabled { background: #252535; color: #45475a; }
QDoubleSpinBox, QSpinBox {
    background: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 4px 6px;
}
QDoubleSpinBox:disabled, QSpinBox:disabled { background: #252535; color: #45475a; }
QCheckBox { color: #cdd6f4; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #45475a; border-radius: 3px; background: #313244;
}
QCheckBox::indicator:checked { background: #cba6f7; border-color: #cba6f7; }
QPushButton#primary {
    background: #cba6f7; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 8px 18px; font-weight: bold; font-size: 13px;
}
QPushButton#primary:hover { background: #d9b8ff; }
QPushButton#primary:disabled { background: #45475a; color: #313244; }
QPushButton#secondary {
    background: #313244; color: #cdd6f4; border: 1px solid #45475a;
    border-radius: 6px; padding: 8px 18px; font-size: 12px;
}
QPushButton#secondary:hover { background: #3d3f55; }
QPushButton#secondary:disabled { color: #45475a; border-color: #313244; }
QPushButton#danger {
    background: #f38ba8; color: #1e1e2e; border: none;
    border-radius: 6px; padding: 8px 18px; font-size: 12px;
}
QPushButton#danger:disabled { background: #45475a; color: #313244; }
QFrame#separator { background: #313244; max-height: 1px; }
QLabel#backupNote { color: #585b70; font-size: 10px; }
"""

_ALT_MODES = ["relativeToGround", "absolute", "clampToGround"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _btn(text: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(kind)
    return b


def _sep() -> QFrame:
    f = QFrame()
    f.setObjectName("separator")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


def _backup_version(path: Path) -> Path | None:
    """
    Copy *path* to <stem>_v{n}.kml in the same folder (incrementing n).
    Returns the backup path, or None if source does not exist.
    """
    if not path.exists():
        return None
    n = 1
    while (path.parent / f"{path.stem}_v{n}.kml").exists():
        n += 1
    backup = path.parent / f"{path.stem}_v{n}.kml"
    shutil.copy2(path, backup)
    log.info("Version backup: %s → %s", path.name, backup.name)
    return backup


class _OverrideConfig:
    """Thin wrapper around ConfigManager that injects per-key overrides."""

    def __init__(self, real: ConfigManager, overrides: dict[tuple[str, str], Any]):
        self._real = real
        self._overrides = overrides

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        return self._overrides.get((section, key), self._real.get(section, key, fallback))


# ── Main panel ───────────────────────────────────────────────────────────────

class EditPanel(QWidget):
    """
    Phase 5 panel: load a KML, edit its metadata, re-process its geometry,
    preview changes on the map, and save (with automatic version backup).
    """

    def __init__(self, config: ConfigManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._kml_path: Path | None = None
        self._coords: list[Coord] = []
        self._preview_coords: list[Coord] = []
        self._preview_placemarks: list[ChainagePlacemark] = []
        self._has_preview = False

        apply_dark(self, _STYLE)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 16)
        root.setSpacing(8)

        title = QLabel("Edit & Re-process")
        title.setObjectName("panelTitle")
        root.addWidget(title)
        root.addWidget(_sep())
        root.addSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(splitter_style())

        splitter.addWidget(self._build_left_panel())

        self._map = MapCanvas(self)
        splitter.addWidget(self._map)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 760])

        root.addWidget(splitter, stretch=1)

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(520)
        scroll.setStyleSheet(scroll_area_style())

        content = QWidget()
        content.setStyleSheet(container_style())
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        layout.addWidget(self._build_load_group())
        layout.addWidget(self._build_metadata_group())
        layout.addWidget(self._build_reprocess_group())
        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    # ── Load group ────────────────────────────────────────────────────────

    def _build_load_group(self) -> QGroupBox:
        grp = QGroupBox("Load KML File")
        vbox = QVBoxLayout(grp)
        vbox.setSpacing(6)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("No file loaded…")
        self._path_edit.setReadOnly(True)
        browse_btn = _btn("Browse…", "secondary")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_kml)
        path_row.addWidget(self._path_edit)
        path_row.addWidget(browse_btn)
        vbox.addLayout(path_row)

        load_btn = _btn("Load & Preview", "primary")
        load_btn.clicked.connect(self._load_kml)
        self._load_btn = load_btn
        vbox.addWidget(load_btn)

        return grp

    # ── Metadata group ────────────────────────────────────────────────────

    def _build_metadata_group(self) -> QGroupBox:
        grp = QGroupBox("Metadata")
        self._meta_grp = grp
        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        # Name
        grid.addWidget(QLabel("Name:"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Road Path")
        grid.addWidget(self._name_edit, 0, 1)

        # Description
        grid.addWidget(QLabel("Description:"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self._desc_edit = QLineEdit()
        grid.addWidget(self._desc_edit, 1, 1)

        # Line color + swatch + hint on same row
        grid.addWidget(QLabel("Color (AABBGGRR):"), 2, 0, Qt.AlignmentFlag.AlignRight)
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("ff0000ff")
        self._color_edit.setMaxLength(8)
        self._color_edit.setMaximumWidth(90)
        self._color_swatch = QFrame()
        self._color_swatch.setFixedSize(22, 22)
        self._color_swatch.setStyleSheet("background: #ff0000; border-radius: 4px;")
        self._color_edit.textChanged.connect(self._update_color_swatch)
        hint = QLabel("e.g. ff0000ff = red")
        hint.setObjectName("sectionHint")
        color_row.addWidget(self._color_edit)
        color_row.addWidget(self._color_swatch)
        color_row.addWidget(hint)
        color_row.addStretch()
        color_w = QWidget()
        color_w.setLayout(color_row)
        grid.addWidget(color_w, 2, 1)

        # Line width + altitude mode on same row
        width_alt_row = QHBoxLayout()
        width_alt_row.setSpacing(12)
        lbl_w = QLabel("Width (px):")
        lbl_w.setObjectName("sectionHint")
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20)
        self._width_spin.setValue(4)
        self._width_spin.setFixedWidth(60)
        lbl_a = QLabel("Altitude:")
        lbl_a.setObjectName("sectionHint")
        self._alt_combo = QComboBox()
        for m in _ALT_MODES:
            self._alt_combo.addItem(m)
        width_alt_row.addWidget(lbl_w)
        width_alt_row.addWidget(self._width_spin)
        width_alt_row.addSpacing(8)
        width_alt_row.addWidget(lbl_a)
        width_alt_row.addWidget(self._alt_combo, stretch=1)
        wa_w = QWidget()
        wa_w.setLayout(width_alt_row)
        grid.addWidget(wa_w, 3, 0, 1, 2)

        # Save button
        save_meta_btn = _btn("💾  Save Metadata", "primary")
        save_meta_btn.clicked.connect(self._save_metadata)
        self._save_meta_btn = save_meta_btn
        grid.addWidget(save_meta_btn, 4, 0, 1, 2)

        backup_note = QLabel("Existing file auto-backed up as <name>_v1.kml before saving.")
        backup_note.setObjectName("backupNote")
        backup_note.setWordWrap(True)
        grid.addWidget(backup_note, 5, 0, 1, 2)

        self._set_metadata_enabled(False)
        return grp

    # ── Re-process group ──────────────────────────────────────────────────

    def _build_reprocess_group(self) -> QGroupBox:
        grp = QGroupBox("Re-process")
        self._reproc_grp = grp
        vbox = QVBoxLayout(grp)
        vbox.setSpacing(6)

        # ── Simplify ──────────────────────────────────────────────────
        simp_row = QHBoxLayout()
        simp_row.setSpacing(10)
        self._simplify_chk = QCheckBox("Simplify (RDP)")
        simp_row.addWidget(self._simplify_chk)
        simp_row.addStretch()
        lbl_md = QLabel("Min dist (m):")
        lbl_md.setObjectName("sectionHint")
        self._simp_min_dist = QDoubleSpinBox()
        self._simp_min_dist.setRange(0.1, 1000.0)
        self._simp_min_dist.setDecimals(1)
        self._simp_min_dist.setValue(self._config.get("simplify", "min_distance_meters", 5.0))
        self._simp_min_dist.setFixedWidth(72)
        lbl_eps = QLabel("ε:")
        lbl_eps.setObjectName("sectionHint")
        self._simp_rdp_eps = QDoubleSpinBox()
        self._simp_rdp_eps.setRange(0.000001, 0.01)
        self._simp_rdp_eps.setDecimals(6)
        self._simp_rdp_eps.setSingleStep(0.000001)
        self._simp_rdp_eps.setValue(self._config.get("simplify", "rdp_epsilon", 0.00001))
        self._simp_rdp_eps.setFixedWidth(100)
        simp_row.addWidget(lbl_md)
        simp_row.addWidget(self._simp_min_dist)
        simp_row.addWidget(lbl_eps)
        simp_row.addWidget(self._simp_rdp_eps)
        vbox.addLayout(simp_row)

        # ── Densify ───────────────────────────────────────────────────
        dens_row = QHBoxLayout()
        dens_row.setSpacing(10)
        self._densify_chk = QCheckBox("Densify (interpolate)")
        dens_row.addWidget(self._densify_chk)
        dens_row.addStretch()
        lbl_gap = QLabel("Max gap (m):")
        lbl_gap.setObjectName("sectionHint")
        self._dens_max_dist = QDoubleSpinBox()
        self._dens_max_dist.setRange(0.5, 1000.0)
        self._dens_max_dist.setDecimals(1)
        self._dens_max_dist.setValue(self._config.get("densify", "max_distance_meters", 10.0))
        self._dens_max_dist.setFixedWidth(72)
        dens_row.addWidget(lbl_gap)
        dens_row.addWidget(self._dens_max_dist)
        vbox.addLayout(dens_row)

        # ── Chainage ──────────────────────────────────────────────────
        ch_row = QHBoxLayout()
        ch_row.setSpacing(10)
        self._chainage_chk = QCheckBox("Chainage markers")
        ch_row.addWidget(self._chainage_chk)
        ch_row.addStretch()
        lbl_iv = QLabel("Every (m):")
        lbl_iv.setObjectName("sectionHint")
        self._ch_interval = QSpinBox()
        self._ch_interval.setRange(10, 10000)
        self._ch_interval.setSingleStep(50)
        self._ch_interval.setValue(self._config.get("chainage", "interval_meters", 100))
        self._ch_interval.setFixedWidth(72)
        lbl_st = QLabel("Start (m):")
        lbl_st.setObjectName("sectionHint")
        self._ch_start = QSpinBox()
        self._ch_start.setRange(0, 999999)
        self._ch_start.setSingleStep(100)
        self._ch_start.setValue(self._config.get("chainage", "start_chainage", 0))
        self._ch_start.setFixedWidth(72)
        ch_row.addWidget(lbl_iv)
        ch_row.addWidget(self._ch_interval)
        ch_row.addWidget(lbl_st)
        ch_row.addWidget(self._ch_start)
        vbox.addLayout(ch_row)

        vbox.addWidget(_sep())

        # ── Action buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        preview_btn = _btn("🔍  Preview", "secondary")
        preview_btn.clicked.connect(self._preview_reprocess)
        self._preview_btn = preview_btn
        save_proc_btn = _btn("💾  Save Processed", "primary")
        save_proc_btn.clicked.connect(self._save_processed)
        save_proc_btn.setEnabled(False)
        self._save_proc_btn = save_proc_btn
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(save_proc_btn)
        vbox.addLayout(btn_row)

        backup_note = QLabel("Existing file auto-backed up as <name>_v1.kml before saving.")
        backup_note.setObjectName("backupNote")
        backup_note.setWordWrap(True)
        vbox.addWidget(backup_note)

        self._set_reprocess_enabled(False)
        return grp

    # ── Enable / disable helpers ──────────────────────────────────────────

    def _set_metadata_enabled(self, enabled: bool) -> None:
        for w in [self._name_edit, self._desc_edit, self._color_edit,
                  self._width_spin, self._alt_combo, self._save_meta_btn]:
            w.setEnabled(enabled)

    def _set_reprocess_enabled(self, enabled: bool) -> None:
        for w in [self._simplify_chk, self._densify_chk, self._chainage_chk,
                  self._simp_min_dist, self._simp_rdp_eps,
                  self._dens_max_dist, self._ch_interval, self._ch_start,
                  self._preview_btn]:
            w.setEnabled(enabled)
        if not enabled:
            self._save_proc_btn.setEnabled(False)

    # ── Slots ─────────────────────────────────────────────────────────────

    def _browse_kml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open KML File", "", "KML Files (*.kml);;All Files (*)"
        )
        if path:
            self._path_edit.setText(path)

    def _load_kml(self) -> None:
        path_str = self._path_edit.text().strip()
        if not path_str:
            QMessageBox.warning(self, "No file", "Browse for a KML file first.")
            return

        path = Path(path_str)
        if not path.exists():
            QMessageBox.critical(self, "File not found", f"File not found:\n{path}")
            return

        try:
            coords = read_linestring(path)
            meta = read_kml_meta(path)
        except KMLParseError as exc:
            QMessageBox.critical(self, "KML Error", str(exc))
            return

        self._kml_path = path
        self._coords = coords
        self._has_preview = False
        self._save_proc_btn.setEnabled(False)

        # Populate metadata form
        self._name_edit.setText(meta["name"])
        self._desc_edit.setText(meta["description"])
        self._color_edit.setText(meta["line_color"])
        self._width_spin.setValue(int(meta["line_width"]))
        idx = _ALT_MODES.index(meta["altitude_mode"]) if meta["altitude_mode"] in _ALT_MODES else 0
        self._alt_combo.setCurrentIndex(idx)

        # Enable form sections
        self._set_metadata_enabled(True)
        self._set_reprocess_enabled(True)

        # Show on map
        self._map.clear()
        self._map.load_coords(coords, name=meta["name"], color="#4dabf7")
        log.info("Loaded KML for editing: %s (%d coords)", path.name, len(coords))

    def _update_color_swatch(self, text: str) -> None:
        """Update the color preview swatch when the user edits the color field."""
        if len(text) == 8:
            # KML color is AABBGGRR — convert to #RRGGBB for Qt
            try:
                bb = text[4:6]
                gg = text[2:4]
                rr = text[6:8]
                hex_color = f"#{rr}{gg}{bb}"
                self._color_swatch.setStyleSheet(
                    f"background: {hex_color}; border-radius: 4px;"
                )
            except (ValueError, IndexError):
                pass

    def _build_override_config(self) -> _OverrideConfig:
        """Build a config override from the current re-process spinbox values."""
        return _OverrideConfig(self._config, {
            ("simplify", "min_distance_meters"): self._simp_min_dist.value(),
            ("simplify", "rdp_epsilon"):          self._simp_rdp_eps.value(),
            ("densify",  "max_distance_meters"):  self._dens_max_dist.value(),
            ("chainage", "interval_meters"):       self._ch_interval.value(),
            ("chainage", "start_chainage"):        self._ch_start.value(),
        })

    def _run_reprocess(self) -> tuple[list[Coord], list[ChainagePlacemark]]:
        """Run selected operations on self._coords and return (coords, placemarks)."""
        cfg = self._build_override_config()
        coords = list(self._coords)
        placemarks: list[ChainagePlacemark] = []

        if self._simplify_chk.isChecked():
            coords = simplify(coords, cfg)
            log.info("Re-process simplify: → %d pts", len(coords))

        if self._densify_chk.isChecked():
            coords = densify(coords, cfg)
            log.info("Re-process densify: → %d pts", len(coords))

        if self._chainage_chk.isChecked():
            placemarks = compute_chainage(coords, cfg)
            log.info("Re-process chainage: %d markers", len(placemarks))

        return coords, placemarks

    def _preview_reprocess(self) -> None:
        if not self._coords:
            QMessageBox.warning(self, "No data", "Load a KML file first.")
            return
        if not any([self._simplify_chk.isChecked(),
                    self._densify_chk.isChecked(),
                    self._chainage_chk.isChecked()]):
            QMessageBox.information(self, "Nothing selected",
                                    "Select at least one re-process operation.")
            return

        try:
            coords, placemarks = self._run_reprocess()
        except Exception as exc:
            QMessageBox.critical(self, "Re-process Error", str(exc))
            log.exception("Re-process preview failed")
            return

        self._preview_coords = coords
        self._preview_placemarks = placemarks
        self._has_preview = True

        # Show: original faded blue + processed bright white
        self._map.clear()
        self._map.load_coords(self._coords, name="Original", color="#4dabf770")
        self._map.load_coords(coords, name="Re-processed", color="#ffffff")

        pt_delta = len(coords) - len(self._coords)
        sign = "+" if pt_delta >= 0 else ""
        log.info("Preview: %d → %d pts (%s%d), %d chainage markers",
                 len(self._coords), len(coords), sign, pt_delta, len(placemarks))

        self._save_proc_btn.setEnabled(True)

    def _current_meta(self) -> dict:
        """Collect the current metadata form values."""
        return {
            "name":          self._name_edit.text().strip() or "Road Path",
            "description":   self._desc_edit.text().strip(),
            "line_color":    self._color_edit.text().strip() or "ff0000ff",
            "line_width":    self._width_spin.value(),
            "altitude_mode": self._alt_combo.currentText(),
        }

    def _save_metadata(self) -> None:
        if self._kml_path is None or not self._coords:
            QMessageBox.warning(self, "No data", "Load a KML file first.")
            return

        meta = self._current_meta()
        backup = _backup_version(self._kml_path)

        try:
            write_kml(
                self._kml_path,
                self._coords,
                name=meta["name"],
                line_color=meta["line_color"],
                line_width=meta["line_width"],
                altitude_mode=meta["altitude_mode"],
                description=meta["description"],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            log.exception("Metadata save failed")
            return

        msg = f"Metadata saved to:\n{self._kml_path.name}"
        if backup:
            msg += f"\n\nPrevious version backed up as:\n{backup.name}"
        QMessageBox.information(self, "Saved", msg)
        log.info("Metadata saved: %s (backup: %s)", self._kml_path.name,
                 backup.name if backup else "none")

    def _save_processed(self) -> None:
        if not self._has_preview or not self._preview_coords:
            QMessageBox.warning(self, "No preview", "Run Preview first.")
            return

        meta = self._current_meta()
        backup = _backup_version(self._kml_path)

        try:
            write_kml(
                self._kml_path,
                self._preview_coords,
                self._preview_placemarks or None,
                name=meta["name"],
                line_color=meta["line_color"],
                line_width=meta["line_width"],
                altitude_mode=meta["altitude_mode"],
                description=meta["description"],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            log.exception("Processed save failed")
            return

        # Update the live state to the newly saved version
        self._coords = self._preview_coords
        self._has_preview = False
        self._save_proc_btn.setEnabled(False)

        msg = (
            f"Re-processed KML saved to:\n{self._kml_path.name}\n"
            f"({len(self._coords)} coords"
            + (f", {len(self._preview_placemarks)} chainage markers"
               if self._preview_placemarks else "")
            + ")"
        )
        if backup:
            msg += f"\n\nPrevious version backed up as:\n{backup.name}"
        QMessageBox.information(self, "Saved", msg)
        log.info("Processed KML saved: %s (backup: %s)", self._kml_path.name,
                 backup.name if backup else "none")

    # ── Public API ────────────────────────────────────────────────────────

    def load_kml_path(self, path: Path) -> None:
        """Called externally (e.g. from ProjectPanel) to pre-fill the path."""
        self._path_edit.setText(str(path))
        self._load_kml()
