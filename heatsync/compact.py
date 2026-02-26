"""
heatsync/compact.py — CompactBar widget.
"""

import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame, QApplication, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush

from .theme import _THEME, _font


class CompactBar(QWidget):
    """Full-info floating bar shown in compact mode. Double-click to dock to top."""

    def __init__(self, on_normal_mode=None, on_settings=None):
        super().__init__()
        self._on_normal_mode  = on_normal_mode
        self._on_settings     = on_settings
        self._last_press_ms   = 0.0
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMinimumWidth(600)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0); lay.setSpacing(0)

        self._name_lbs: list[QLabel] = []
        self._val_lbs:  list[QLabel] = []
        self._seps:     list[QFrame] = []
        self._cpu_pct = QLabel("–"); self._cpu_tmp = QLabel("–°C")
        self._gpu_pct = QLabel("–"); self._gpu_tmp = QLabel("–°C")

        def _add_sep():
            sep = QFrame(); sep.setFixedSize(1, 22)
            self._seps.append(sep)
            lay.addSpacing(12); lay.addWidget(sep); lay.addSpacing(12)

        def _add_section(name_text: str, min_val_w: int = 110):
            name = QLabel(name_text)
            name.setFont(_font(10)); name.setFixedWidth(36)
            self._name_lbs.append(name)
            val = QLabel("–"); val.setFont(_font(13, bold=True))
            val.setMinimumWidth(min_val_w)
            self._val_lbs.append(val)
            lay.addWidget(name); lay.addWidget(val)

        # CPU — name + pct label + temp label (each colored separately)
        cpu_name = QLabel("CPU"); cpu_name.setFont(_font(10)); cpu_name.setFixedWidth(36)
        self._name_lbs.append(cpu_name)
        self._cpu_pct.setFont(_font(13, bold=True)); self._cpu_pct.setFixedWidth(38)
        self._cpu_tmp.setFont(_font(13, bold=True)); self._cpu_tmp.setMinimumWidth(56)
        lay.addWidget(cpu_name)
        lay.addWidget(self._cpu_pct); lay.addSpacing(4); lay.addWidget(self._cpu_tmp)

        _add_sep()

        # GPU — same pattern
        gpu_name = QLabel("GPU"); gpu_name.setFont(_font(10)); gpu_name.setFixedWidth(36)
        self._name_lbs.append(gpu_name)
        self._gpu_pct.setFont(_font(13, bold=True)); self._gpu_pct.setFixedWidth(38)
        self._gpu_tmp.setFont(_font(13, bold=True)); self._gpu_tmp.setMinimumWidth(56)
        lay.addWidget(gpu_name)
        lay.addWidget(self._gpu_pct); lay.addSpacing(4); lay.addWidget(self._gpu_tmp)

        _add_sep()
        _add_section("RAM",  110)
        _add_sep()
        _add_section("NET",  140)
        _add_sep()
        _add_section("DISK", 120)
        _add_sep()
        self._clk_time_lbl = QLabel("–")
        self._clk_time_lbl.setFont(_font(12, bold=True))
        self._clk_time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clk_date_lbl = QLabel("")
        self._clk_date_lbl.setFont(_font(10))
        self._clk_date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        clk_box = QHBoxLayout(); clk_box.setSpacing(8); clk_box.setContentsMargins(0, 0, 0, 0)
        clk_box.addWidget(self._clk_time_lbl)
        clk_box.addWidget(self._clk_date_lbl)
        clk_w = QWidget(); clk_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        clk_w.setLayout(clk_box)
        lay.addWidget(clk_w, 1)

        _clk = QTimer(self); _clk.timeout.connect(self._tick_clock); _clk.start(1000)
        self._tick_clock()
        self._apply_theme_styles()

    @staticmethod
    def _temp_color(temp: float, temp_hi: float) -> str:
        """Same white→red heat gradient as ArcGauge temp mode."""
        pct = max(0.0, min(1.0, temp / max(temp_hi, 1.0)))
        r = 255
        g = int(255 * (1.0 - pct) ** 0.6)
        b = int(255 * (1.0 - pct) ** 1.5)
        return QColor(r, g, b).name()

    def _tick_clock(self):
        now  = datetime.now()
        hour = now.hour % 12 or 12
        self._clk_time_lbl.setText(now.strftime(f"{hour}:%M %p"))
        self._clk_date_lbl.setText(now.strftime("%a %d %b %Y"))
        self._clk_time_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._clk_date_lbl.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")

    def update_values(self, cpu_pct: float, cpu_temp: float,
                      gpu_pct: float, gpu_temp: float,
                      ram_used: float = 0, ram_tot: float = 0,
                      net_up: float = 0, net_down: float = 0,
                      disk_used: float = 0, disk_tot: float = 0, **_):
        hi = _THEME.txt_hi
        self._cpu_pct.setText(f"{cpu_pct:.0f}%")
        self._cpu_pct.setStyleSheet(f"color: {hi}; background: transparent;")
        self._cpu_tmp.setText(f"{cpu_temp:.0f}°C")
        self._cpu_tmp.setStyleSheet(
            f"color: {self._temp_color(cpu_temp, 105)}; background: transparent;")

        self._gpu_pct.setText(f"{gpu_pct:.0f}%")
        self._gpu_pct.setStyleSheet(f"color: {hi}; background: transparent;")
        self._gpu_tmp.setText(f"{gpu_temp:.0f}°C")
        self._gpu_tmp.setStyleSheet(
            f"color: {self._temp_color(gpu_temp, 95)}; background: transparent;")

        self._val_lbs[0].setText(f"{ram_used:.1f}/{ram_tot:.0f} GB")
        self._val_lbs[1].setText(f"↑{net_up:.1f}  ↓{net_down:.1f} Mb/s")
        self._val_lbs[2].setText(f"{disk_used:.0f}/{disk_tot:.0f} GB")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            now = time.monotonic() * 1000
            dt, self._last_press_ms = now - self._last_press_ms, now
            if dt > QApplication.doubleClickInterval():
                h = self.window().windowHandle()
                if h: h.startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._last_press_ms = 0.0
            self.window().toggle_dock()
        super().mouseDoubleClickEvent(e)

    def _apply_theme_styles(self):
        for lb in self._name_lbs:
            lb.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
        for lb in self._val_lbs:
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        for sep in self._seps:
            sep.setStyleSheet(f"background: {_THEME.card_bd};")
        self._clk_time_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._clk_date_lbl.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
        self.update()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        bg = _THEME.card_bg; fg = _THEME.txt_hi; bd = _THEME.card_bd
        menu.setStyleSheet(
            f"QMenu{{background:{bg};color:{fg};border:1px solid {bd};}}"
            f"QMenu::item:selected{{background:{bd};}}")
        menu.addAction("Dock to Top",  self.window().toggle_dock)
        if self._on_normal_mode:
            menu.addAction("Normal Mode", self._on_normal_mode)
        if self._on_settings:
            menu.addAction("Settings…",   self._on_settings)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.instance().quit)
        menu.exec(e.globalPos())

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_THEME.card_bg)))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QPen(QColor(_THEME.card_bd), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 10, 10)
        p.end()
