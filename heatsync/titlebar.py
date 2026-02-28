"""
heatsync/titlebar.py — TitleBar, window control buttons, vendor helpers.
"""

import os
import time
from datetime import datetime

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QApplication, QSizePolicy, QMenu
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap,
)

from .constants import (
    _SCRIPT_DIR, VERSION,
    AMD_RED, INTEL_BLUE, NVIDIA_GREEN, CYAN,
    GPU_NAME, GPU_COLOR, _get_cpu_name, _cpu_vendor_color,
)
from .theme import _THEME, _font, _make_clock_pixmap, _make_calendar_pixmap


# ── Vendor keywords (used for hw name coloring) ───────────────────────────────
_VENDOR_KEYWORDS = {
    AMD_RED:      ("AMD", "RYZEN", "EPYC", "ATHLON", "THREADRIPPER"),
    INTEL_BLUE:   ("INTEL",),
    NVIDIA_GREEN: ("NVIDIA", "GEFORCE", "RTX", "GTX", "QUADRO", "TESLA"),
}

def _hw_html(text: str, color: str) -> str:
    keywords = _VENDOR_KEYWORDS.get(color, ())
    parts = []
    for word in text.split():
        if any(kw in word.upper() for kw in keywords):
            parts.append(f'<span style="color:{color};">{word}</span>')
        else:
            parts.append(f'<span style="color:{_THEME.txt_hi};">{word}</span>')
    return " ".join(parts)


# ── Window control button ─────────────────────────────────────────────────────
class _WinBtn(QWidget):
    def __init__(self, symbol, color, callback):
        super().__init__()
        self._symbol = symbol; self._color = QColor(color)
        self._dim = QColor(color).darker(140); self._cb = callback
        self._hovered = False; self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._cb()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color if self._hovered else self._dim)
        p.drawEllipse(0, 0, 18, 18)
        if self._hovered:
            p.setFont(_font(9, bold=True)); p.setPen(QColor(0, 0, 0, 210))
            p.drawText(QRectF(0, 0, 18, 18), Qt.AlignmentFlag.AlignCenter, self._symbol)
        p.end()


# ── Icon button (gear / history) ──────────────────────────────────────────────
class _IconBtn(QWidget):
    def __init__(self, symbol: str, callback):
        super().__init__()
        self._symbol  = symbol
        self._cb      = callback
        self._hovered = False
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._cb()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(_THEME.cyan) if self._hovered else QColor(_THEME.txt_lo)
        p.setFont(_font(13)); p.setPen(col)
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   Qt.AlignmentFlag.AlignCenter, self._symbol)
        p.end()

    def _apply_theme_styles(self): self.update()


# ── Dock button ───────────────────────────────────────────────────────────────
class _DockBtn(QWidget):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback; self._active = False; self._hovered = False
        self.setFixedSize(26, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_active(self, v): self._active = v; self.update()
    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._cb()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H  = self.width(), self.height()
        rim_c = QColor(_THEME.cyan) if (self._active or self._hovered) else QColor(_THEME.txt_lo)
        p.setPen(QPen(rim_c, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 2.5, 2.5)
        bar_c = QColor(_THEME.cyan if self._active else rim_c.name())
        bar_c.setAlpha(220 if self._active else (160 if self._hovered else 90))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bar_c))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, 5), 2.5, 2.5); p.end()


# ── Resize grip ───────────────────────────────────────────────────────────────
class ResizeGrip(QWidget):
    def __init__(self, parent_win):
        super().__init__(parent_win)
        self._win = parent_win; self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self._win.windowHandle()
            if h: h.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(_THEME.txt_lo), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(3):
            o = 5 + i * 5; p.drawLine(o, 20, 20, o)
        p.end()


# ── Title / Drag Bar ──────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, parent_win, cpu_color=None, gpu_color=None,
                 on_settings=None, on_history=None):
        super().__init__(parent_win)
        self._win = parent_win
        self._last_press_ms = 0.0
        self._press_pos = None
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0); lay.setSpacing(0)

        icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
        if os.path.exists(icon_path):
            src = QPixmap(icon_path).scaled(
                26, 26,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            bordered = QPixmap(34, 34)
            bordered.fill(Qt.GlobalColor.transparent)
            bp = QPainter(bordered)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setPen(Qt.PenStyle.NoPen)
            bp.setBrush(QBrush(QColor(0, 0, 0, 170)))
            bp.drawEllipse(QRectF(0, 0, 34, 34))
            bp.drawPixmap(4, 4, src); bp.end()
            icon_lbl = QLabel(); icon_lbl.setPixmap(bordered); icon_lbl.setFixedSize(34, 34)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lay.addWidget(icon_lbl); lay.addSpacing(8)

        self._title_label = QLabel("HEATSYNC")
        self._title_label.setFont(_font(15, bold=True))
        self._title_label.setStyleSheet(
            f"color: {_THEME.cyan}; letter-spacing: 3px; background: transparent;")
        self._title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._ver_label = QLabel(VERSION)
        self._ver_label.setFont(_font(11))
        self._ver_label.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
        self._ver_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        def _icon_lbl(px: QPixmap) -> QLabel:
            lb = QLabel(); lb.setPixmap(px)
            lb.setFixedSize(px.size())
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lb.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            return lb

        self._clk_icon = _icon_lbl(_make_clock_pixmap(14))
        self._cal_icon = _icon_lbl(_make_calendar_pixmap(14))

        self._time_lbl = QLabel()
        self._time_lbl.setFont(_font(14))
        self._time_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._time_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._date_lbl = QLabel()
        self._date_lbl.setFont(_font(14))
        self._date_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._date_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._tick()
        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000)

        btn_min       = _WinBtn("−", "#ffbd2e", parent_win.showMinimized)
        btn_cls       = _WinBtn("✕", "#ff5f57", parent_win.close)
        self.dock_btn = _DockBtn(parent_win.toggle_dock)
        for btn in (btn_min, btn_cls, self.dock_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hw_cpu = QLabel(_get_cpu_name())
        self._hw_cpu.setFont(_font(10))
        self._hw_cpu.setMinimumWidth(0)
        self._hw_cpu.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._hw_cpu.setStyleSheet(
            f"color: {_THEME.txt_hi}; background: transparent;")
        self._hw_cpu.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._hw_gpu = QLabel(GPU_NAME)
        self._hw_gpu.setFont(_font(10))
        self._hw_gpu.setMinimumWidth(0)
        self._hw_gpu.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._hw_gpu.setStyleSheet(
            f"color: {_THEME.txt_hi}; background: transparent;")
        self._hw_gpu.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        lay.addWidget(self._title_label); lay.addSpacing(6)
        lay.addWidget(self._ver_label); lay.addSpacing(14)
        lay.addWidget(self._hw_cpu); lay.addSpacing(10)
        lay.addWidget(self._hw_gpu)
        lay.addStretch()
        lay.addWidget(self._clk_icon); lay.addSpacing(5)
        lay.addWidget(self._time_lbl); lay.addSpacing(14)
        lay.addWidget(self._cal_icon); lay.addSpacing(5)
        lay.addWidget(self._date_lbl); lay.addSpacing(18)
        if on_history:
            self._hist_btn = _IconBtn("⏱", on_history)
            lay.addWidget(self._hist_btn); lay.addSpacing(6)
        if on_settings:
            self._settings_btn = _IconBtn("⚙", on_settings)
            lay.addWidget(self._settings_btn); lay.addSpacing(6)
        lay.addSpacing(8)
        lay.addWidget(self.dock_btn); lay.addSpacing(10)
        lay.addWidget(btn_min); lay.addSpacing(8); lay.addWidget(btn_cls)

    def _tick(self):
        now  = datetime.now()
        hour = now.hour % 12 or 12
        self._time_lbl.setText(now.strftime(f"{hour}:%M %p"))
        self._date_lbl.setText(now.strftime("%a %d %b %Y"))

    def _apply_theme_styles(self):
        self._title_label.setStyleSheet(
            f"color: {_THEME.cyan}; letter-spacing: 3px; background: transparent;")
        self._ver_label.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
        self._hw_cpu.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._hw_gpu.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._time_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._date_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._clk_icon.setPixmap(_make_clock_pixmap(14))
        self._cal_icon.setPixmap(_make_calendar_pixmap(14))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            now = time.monotonic() * 1000
            dt, self._last_press_ms = now - self._last_press_ms, now
            if dt > QApplication.doubleClickInterval():
                if getattr(self._win, '_locked_to_top', False):
                    pass  # locked — no drag
                elif self._win._docked:
                    self._press_pos = e.position()
                else:
                    h = self._win.windowHandle()
                    if h: h.startSystemMove()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None
                and self._win._docked
                and not getattr(self._win, '_locked_to_top', False)
                and e.buttons() & Qt.MouseButton.LeftButton):
            delta = e.position() - self._press_pos
            if abs(delta.x()) + abs(delta.y()) > QApplication.startDragDistance():
                self._press_pos = None
                self._win.toggle_dock(via_drag=True)
                h = self._win.windowHandle()
                if h: h.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
            self._win.toggle_dock()
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        win = self._win
        menu = QMenu(self)
        bg = _THEME.card_bg; fg = _THEME.txt_hi; bd = _THEME.card_bd
        menu.setStyleSheet(
            f"QMenu{{background:{bg};color:{fg};border:1px solid {bd};}}"
            f"QMenu::item:selected{{background:{bd};}}")
        dock_lbl = "Undock" if win._docked else "Dock to Top"
        menu.addAction(dock_lbl, win.toggle_dock)
        if win._docked:
            lock_act = menu.addAction("Lock to Top")
            lock_act.setCheckable(True)
            lock_act.setChecked(getattr(win, '_locked_to_top', False))
            lock_act.triggered.connect(win._toggle_lock_top)
        menu.addSeparator()
        menu.addAction("Compact Mode", win._enter_compact_mode)
        menu.addAction("Settings…",    win._open_settings)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.instance().quit)
        menu.exec(e.globalPos())
