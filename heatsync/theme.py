"""
heatsync/theme.py — Theme dataclass, light/dark presets, apply_theme().
"""

import os
from dataclasses import dataclass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QPalette,
    QIcon, QPixmap, QBrush,
)

from .constants import (
    _SCRIPT_DIR, CYAN, GREEN, PURPLE, AMBER, C_WARN, C_DANG,
    NVIDIA_GREEN, AMD_RED, INTEL_BLUE,
)


# ── Theme dataclass ───────────────────────────────────────────────────────────
@dataclass
class Theme:
    name:     str
    bg:       str
    card_bg:  str
    card_bd:  str
    txt_hi:   str
    txt_mid:  str
    txt_lo:   str
    cyan:     str
    green:    str
    purple:   str
    amber:    str
    c_warn:   str
    c_dang:   str


DARK_THEME = Theme(
    name="dark",
    bg="#090b10",  card_bg="#0e1018",  card_bd="#1a1d2b",
    txt_hi="#e5e8f0", txt_mid="#848ba0", txt_lo="#404560",
    cyan="#00ccdd",  green="#00e676",  purple="#9d6fff",
    amber="#ffa040", c_warn="#ff9800", c_dang="#f44336",
)

# NZXT CAM-inspired white theme
LIGHT_THEME = Theme(
    name="light",
    bg="#edf0f7",  card_bg="#ffffff",  card_bd="#c8d0e8",
    txt_hi="#0f1524", txt_mid="#4a5578", txt_lo="#9aa0bc",
    cyan="#00b4c8",  green="#00c853",  purple="#7c5cbf",
    amber="#e59400", c_warn="#e07c00", c_dang="#d63030",
)

_THEME: Theme = DARK_THEME


# ── Palette helper ────────────────────────────────────────────────────────────
def _make_palette(theme: Theme) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(theme.bg))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(theme.txt_hi))
    pal.setColor(QPalette.ColorRole.Base,            QColor(theme.card_bg))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(theme.card_bd))
    pal.setColor(QPalette.ColorRole.Text,            QColor(theme.txt_hi))
    pal.setColor(QPalette.ColorRole.Button,          QColor(theme.card_bg))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(theme.txt_hi))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(theme.cyan))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.bg))
    return pal


def apply_theme(theme: Theme) -> None:
    global _THEME
    _THEME = theme
    app = QApplication.instance()
    if app is None:
        return
    app.setPalette(_make_palette(theme))
    for w in app.allWidgets():
        if hasattr(w, "_apply_theme_styles"):
            w._apply_theme_styles()
        w.update()


# ── Font helper ───────────────────────────────────────────────────────────────
_FONT_FAMILIES = ["JetBrainsMono NF", "JetBrainsMono Nerd Font", "JetBrains Mono",
                  "Consolas", "Hack", "Fira Mono", "Fira Sans", "Sans Serif"]

def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(_FONT_FAMILIES)
    f.setPixelSize(max(8, int(px)))
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


# ── Tray icon ─────────────────────────────────────────────────────────────────
def _make_tray_icon(level: str = "normal") -> QIcon:
    icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
    if os.path.exists(icon_path) and level == "normal":
        return QIcon(icon_path)
    color_map = {"danger": _THEME.c_dang, "warn": _THEME.c_warn, "normal": _THEME.cyan}
    arc_color = color_map.get(level, _THEME.cyan)
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#1c1f2e"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawArc(QRectF(4, 4, 24, 24), 240 * 16, -300 * 16)
    p.setPen(QPen(QColor(arc_color), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    span = {"danger": -300, "warn": -225, "normal": -180}.get(level, -180)
    p.drawArc(QRectF(4, 4, 24, 24), 240 * 16, span * 16)
    p.end()
    return QIcon(px)


# ── Clock / Calendar pixmap helpers ──────────────────────────────────────────
def _make_clock_pixmap(size: int = 14) -> QPixmap:
    px = QPixmap(size, size); px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(_THEME.cyan)
    cx = cy = size / 2.0; r = cx - 1.0
    p.setPen(QPen(col, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
    from PyQt6.QtCore import QPointF
    p.drawEllipse(QPointF(cx, cy), r, r)
    cap = Qt.PenCapStyle.RoundCap
    p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, cap))
    p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.35, cy - r * 0.35))  # hour
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.65))              # minute
    p.end(); return px


def _make_calendar_pixmap(size: int = 14) -> QPixmap:
    px = QPixmap(size, size); px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(_THEME.cyan)
    p.setPen(QPen(col, 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(1, 2, size - 2, size - 3), 1.5, 1.5)
    p.drawLine(QPoint(1, 5), QPoint(size - 1, 5))
    # binding nubs at top
    p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPoint(4, 1), QPoint(4, 4))
    p.drawLine(QPoint(size - 4, 1), QPoint(size - 4, 4))
    # 3×2 dot grid in body
    from PyQt6.QtCore import QPointF
    for row in range(2):
        for col_i in range(3):
            xp = 4 + col_i * ((size - 6) // 2)
            yp = 8 + row * 3
            p.drawPoint(QPointF(xp, yp))
    p.end(); return px
