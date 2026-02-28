"""
heatsync/theme.py — Theme dataclass, presets, apply_theme().
"""

import os
import copy
from collections import OrderedDict
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
    name:         str
    display_name: str
    bg:           str
    card_bg:      str
    card_bd:      str
    txt_hi:       str
    txt_mid:      str
    txt_lo:       str
    cyan:         str   # primary accent — gauge arcs, label highlights
    green:        str   # positive / secondary accent
    purple:       str   # sparklines, GPU accents
    amber:        str   # RAM/NET/DISK labels, date text, warm accents
    c_warn:       str
    c_dang:       str
    is_light:     bool = False


# ── Built-in themes ───────────────────────────────────────────────────────────

DARK_THEME = Theme(
    name="dark", display_name="Dark",
    bg="#090b10",  card_bg="#0c0f1a",  card_bd="#1e2235",
    txt_hi="#e5e8f0", txt_mid="#848ba0", txt_lo="#404560",
    cyan="#00d4e8",  green="#00e676",  purple="#9d6fff",
    amber="#ffa040", c_warn="#ff9800", c_dang="#f44336",
)

LIGHT_THEME = Theme(
    name="light", display_name="Light",
    bg="#edf0f7",  card_bg="#ffffff",  card_bd="#c8d0e8",
    txt_hi="#0f1524", txt_mid="#4a5578", txt_lo="#9aa0bc",
    cyan="#00b4c8",  green="#00c853",  purple="#7c5cbf",
    amber="#e59400", c_warn="#e07c00", c_dang="#d63030",
    is_light=True,
)

SYNTHWAVE_THEME = Theme(
    name="synthwave", display_name="Synthwave",
    bg="#0d0015",  card_bg="#160025",  card_bd="#2d0050",
    txt_hi="#f8f0ff", txt_mid="#b090cf", txt_lo="#604080",
    # Magenta/pink as primary arc, teal as green, electric purple, gold
    cyan="#ff2de0",  green="#00ffd0",  purple="#c030ff",
    amber="#ffe040", c_warn="#ff8020", c_dang="#ff1c50",
)

MIDNIGHT_THEME = Theme(
    name="midnight", display_name="Midnight",
    bg="#020510",  card_bg="#070d20",  card_bd="#0f1c40",
    txt_hi="#c0d0ff", txt_mid="#5070a0", txt_lo="#1c2a50",
    cyan="#4488ff",  green="#00c8a0",  purple="#9060ff",
    amber="#ffb040", c_warn="#ff8020", c_dang="#ff4040",
)

DRACULA_THEME = Theme(
    name="dracula", display_name="Dracula",
    bg="#1e1f29",  card_bg="#282a36",  card_bd="#44475a",
    txt_hi="#f8f8f2", txt_mid="#6272a4", txt_lo="#44475a",
    cyan="#8be9fd",  green="#50fa7b",  purple="#bd93f9",
    amber="#ffb86c", c_warn="#ffb86c", c_dang="#ff5555",
)

NORD_THEME = Theme(
    name="nord", display_name="Nord",
    bg="#1c2028",  card_bg="#2e3440",  card_bd="#3b4252",
    txt_hi="#eceff4", txt_mid="#9099a7", txt_lo="#4c566a",
    cyan="#88c0d0",  green="#a3be8c",  purple="#b48ead",
    amber="#ebcb8b", c_warn="#d08770", c_dang="#bf616a",
)

SOLARIZED_THEME = Theme(
    name="solarized", display_name="Solarized",
    bg="#001e26",  card_bg="#002b36",  card_bd="#073642",
    txt_hi="#fdf6e3", txt_mid="#93a1a1", txt_lo="#586e75",
    cyan="#2aa198",  green="#859900",  purple="#6c71c4",
    amber="#b58900", c_warn="#cb4b16", c_dang="#dc322f",
)

FOREST_THEME = Theme(
    name="forest", display_name="Forest",
    bg="#090f08",  card_bg="#0f1a0d",  card_bd="#1d3019",
    txt_hi="#d0f0c0", txt_mid="#78a860", txt_lo="#344d28",
    cyan="#40e090",  green="#90f040",  purple="#90c890",
    amber="#c8c040", c_warn="#d8a020", c_dang="#e04040",
)

AMBER_THEME = Theme(
    name="amber", display_name="Amber",
    bg="#0e0900",  card_bg="#180e00",  card_bd="#2c1800",
    txt_hi="#ffc030", txt_mid="#906020", txt_lo="#402c10",
    # Warm amber as every accent — monochromatic CRT look
    cyan="#ffb820",  green="#d09020",  purple="#c07818",
    amber="#ff8000", c_warn="#ff5000", c_dang="#ff2000",
)

AMOLED_THEME = Theme(
    name="amoled", display_name="AMOLED",
    bg="#000000",  card_bg="#040406",  card_bd="#0c0e18",
    txt_hi="#ffffff", txt_mid="#808080", txt_lo="#282828",
    cyan="#00ffcc",  green="#00ff66",  purple="#cc00ff",
    amber="#ffcc00", c_warn="#ff8800", c_dang="#ff2200",
)

# Ordered dict — order determines display in the picker (left-to-right, top-to-bottom)
THEMES: "OrderedDict[str, Theme]" = OrderedDict([
    ("dark",      DARK_THEME),
    ("light",     LIGHT_THEME),
    ("synthwave", SYNTHWAVE_THEME),
    ("midnight",  MIDNIGHT_THEME),
    ("dracula",   DRACULA_THEME),
    ("nord",      NORD_THEME),
    ("solarized", SOLARIZED_THEME),
    ("forest",    FOREST_THEME),
    ("amber",     AMBER_THEME),
    ("amoled",    AMOLED_THEME),
])

# _THEME is a mutable copy — mutated in-place by apply_theme() so that all
# modules that did `from .theme import _THEME` always see the current theme.
_THEME: Theme = copy.copy(DARK_THEME)


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
    """Apply a theme.  Mutates _THEME in-place so all importers see the change."""
    for f, v in vars(theme).items():
        setattr(_THEME, f, v)
    app = QApplication.instance()
    if app is None:
        return  # Pre-UI call — _THEME updated, widgets will paint correctly when created
    app.setPalette(_make_palette(_THEME))
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
