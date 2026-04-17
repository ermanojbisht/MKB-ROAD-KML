"""
theme.py — Central theme state for MKB-ROAD-KML.

Set once at startup via set_theme(); all widgets use the helpers below.

Usage:
    # In main.py / run_gui():
    from gui.theme import set_theme
    set_theme(cfg.get("ui", "theme", "dark"))

    # Top-level widget dark stylesheet (skipped in light mode):
    from gui.theme import apply_dark
    apply_dark(self, _MY_DARK_STYLE)

    # Inline child-widget styles (always call, returns correct colors):
    from gui.theme import splitter_style, hint_style, ...
    splitter.setStyleSheet(splitter_style())
"""

from __future__ import annotations
from PyQt6.QtWidgets import QWidget

_theme: str = "dark"

# ── Color palettes ────────────────────────────────────────────────────────────

_DARK = {
    "bg_main":      "#1e1e2e",
    "bg_secondary": "#181825",
    "bg_input":     "#313244",
    "border":       "#45475a",
    "text_primary": "#cdd6f4",
    "text_hint":    "#585b70",
    "text_success": "#a6e3a1",
    "text_warn":    "#f9e2af",
    "text_error":   "#f38ba8",
    "text_accent":  "#cba6f7",
    "splitter":     "#313244",
    "alt_row":      "#181825",
}

_LIGHT = {
    "bg_main":      "#f5f5f5",
    "bg_secondary": "#e8e8e8",
    "bg_input":     "#ffffff",
    "border":       "#c8c8c8",
    "text_primary": "#1a1a2e",
    "text_hint":    "#808080",
    "text_success": "#2d7a2d",
    "text_warn":    "#7a5000",
    "text_error":   "#c0392b",
    "text_accent":  "#5c4a9e",
    "splitter":     "#d0d0d0",
    "alt_row":      "#ebebeb",
}


# ── Core API ─────────────────────────────────────────────────────────────────

def set_theme(theme: str) -> None:
    """Set the active theme. Call once at startup before any widget is created."""
    global _theme
    _theme = theme if theme in ("dark", "light") else "dark"


def is_dark() -> bool:
    return _theme == "dark"


def color(key: str) -> str:
    """Return the current-theme hex color for *key*."""
    return (_DARK if is_dark() else _LIGHT)[key]


def apply_dark(widget: QWidget, stylesheet: str) -> None:
    """Apply *stylesheet* to *widget* only in dark mode (light uses Qt Fusion)."""
    if is_dark():
        widget.setStyleSheet(stylesheet)


# ── Inline style helpers (use for child widgets, splitters, labels, tables) ──
# These always return the correct string for the active theme, so call them
# unconditionally — do NOT guard with is_dark().

def splitter_style() -> str:
    return f"QSplitter::handle {{ background: {color('splitter')}; }}"


def scroll_area_style() -> str:
    return f"QScrollArea {{ border: none; background: {color('bg_main')}; }}"


def container_style() -> str:
    return f"background: {color('bg_main')};"


def alt_row_style() -> str:
    return f"QTableWidget {{ alternate-background-color: {color('alt_row')}; }}"


def log_bar_style() -> str:
    return f"background: {color('bg_secondary')};"


def hint_style(extra: str = "") -> str:
    s = f"color: {color('text_hint')};"
    return f"{s} {extra}".strip() if extra else s


def placeholder_style(font_size: int = 20) -> str:
    return f"color: {color('text_hint')}; font-size: {font_size}px;"


def status_style(kind: str) -> str:
    """kind = 'ok' | 'warn' | 'error' | 'accent'"""
    key = {"ok": "text_success", "warn": "text_warn",
           "error": "text_error", "accent": "text_accent"}.get(kind, "text_hint")
    return f"color: {color(key)};"


def status_style_ex(kind: str, extra: str) -> str:
    """Like status_style but with extra CSS properties."""
    key = {"ok": "text_success", "warn": "text_warn",
           "error": "text_error", "accent": "text_accent"}.get(kind, "text_hint")
    return f"color: {color(key)}; {extra}"
