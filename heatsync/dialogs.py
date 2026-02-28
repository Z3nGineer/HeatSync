"""
heatsync/dialogs.py — DataLogger, HistoryWindow, SettingsDialog.
"""

import os
import json
import time
import csv as _csv
from collections import deque
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QDialog, QDialogButtonBox, QTabWidget, QGroupBox,
    QRadioButton, QCheckBox, QComboBox, QLineEdit, QSpinBox,
    QScrollArea, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QApplication,
    QFileDialog, QFrame, QPushButton, QButtonGroup, QGridLayout,
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QIcon, QFont

from .constants import _SCRIPT_DIR, CYAN, GREEN, PURPLE, CPU_COLOR, GPU_COLOR
from .theme import _THEME, _font, THEMES
from .settings import _DEFAULT_SETTINGS
from .sensors import s_battery
from .widgets import Sparkline
from .titlebar import _WinBtn


# ── Data Logger ───────────────────────────────────────────────────────────────
class DataLogger:
    def __init__(self, path: str, fmt: str, max_hours: int):
        self._path       = os.path.expanduser(path)
        self._fmt        = fmt
        self._max_entries = max(1, max_hours * 3600)
        self._buffer: deque = deque(maxlen=self._max_entries)
        self._last_flush = time.monotonic()
        try:
            os.makedirs(self._path, exist_ok=True)
        except Exception:
            pass

    def record(self, metrics: dict):
        row = {"timestamp": datetime.now().isoformat()}
        row.update(metrics)
        self._buffer.append(row)

    def flush(self):
        if not self._buffer:
            return
        try:
            if self._fmt == "json":
                self._flush_json()
            else:
                self._flush_csv()
        except Exception as e:
            print(f"[WARN] DataLogger flush failed: {e}")
        self._last_flush = time.monotonic()

    def _flush_csv(self):
        fname  = os.path.join(self._path, "heatsync_data.csv")
        exists = os.path.exists(fname)
        rows   = list(self._buffer)
        if not rows:
            return
        with open(fname, "a", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if not exists:
                writer.writeheader()
            writer.writerows(rows)

    def _flush_json(self):
        fname = os.path.join(self._path, "heatsync_data.ndjson")
        with open(fname, "a") as f:
            for row in self._buffer:
                f.write(json.dumps(row) + "\n")

    def close(self):
        self.flush()


# ── History Window ────────────────────────────────────────────────────────────
class HistoryWindow(QWidget):
    def __init__(self, settings: dict):
        super().__init__()
        from .constants import IS_WAYLAND
        self.setWindowTitle("HeatSync — History")
        if IS_WAYLAND:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        hw = settings.get("history_window", {})
        self.resize(hw.get("w", 900), hw.get("h", 400))
        if hw.get("x") is not None and hw.get("y") is not None:
            self.move(hw["x"], hw["y"])

        self._sparklines: dict[str, Sparkline] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(6)

        # Header drag bar
        hdr = QHBoxLayout()
        self._title_lbl = QLabel("HISTORY")
        self._title_lbl.setFont(_font(14, bold=True))
        self._title_lbl.setStyleSheet(
            f"color: {_THEME.cyan}; letter-spacing: 2px; background: transparent;")
        png_btn   = _WinBtn("⬇", "#2979ff", self._save_as_png)
        close_btn = _WinBtn("✕", "#ff5f57", self.hide)
        hdr.addWidget(self._title_lbl); hdr.addStretch()
        hdr.addWidget(png_btn); hdr.addSpacing(6); hdr.addWidget(close_btn)
        root.addLayout(hdr)

        # Scrollable sparkline area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._content = QWidget()
        self._content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setSpacing(2)
        self._content_lay.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        self._build_sparklines(settings)

    def _build_sparklines(self, settings: dict):
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._sparklines.clear()

        gauges = settings.get("gauges", {})
        metric_defs = [
            ("cpu_usage", "CPU Usage %",       CPU_COLOR),
            ("cpu_temp",  "CPU Temp °C",        CPU_COLOR),
            ("gpu_usage", "GPU Usage %",        GPU_COLOR),
            ("gpu_temp",  "GPU Temp °C",        GPU_COLOR),
        ]
        if gauges.get("network", False):
            metric_defs += [
                ("net_up",   "Network Upload Mbps",   CYAN),
                ("net_down", "Network Download Mbps", PURPLE),
            ]
        if gauges.get("battery", False):
            metric_defs.append(("battery", "Battery %", GREEN))

        for key, label, color in metric_defs:
            if not gauges.get(key.split("_")[0] + "_" + key.split("_")[1]
                               if key.count("_") >= 1 else key, True):
                continue
            row = QWidget()
            row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            rl = QVBoxLayout(row); rl.setContentsMargins(0, 4, 0, 0); rl.setSpacing(2)
            lbl = QLabel(label)
            lbl.setFont(_font(11))
            lbl.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
            spark = Sparkline(color=color, max_pts=3600, unit="")
            spark.setFixedHeight(56)
            self._sparklines[key] = spark
            rl.addWidget(lbl); rl.addWidget(spark)
            self._content_lay.addWidget(row)

        self._content_lay.addStretch()

    def update_metric(self, key: str, value: float):
        if key in self._sparklines:
            self._sparklines[key].push(value)

    def populate_from_logger(self, logger: DataLogger):
        for entry in logger._buffer:
            for key, val in entry.items():
                if key != "timestamp" and key in self._sparklines:
                    self._sparklines[key].push(float(val))

    def _save_as_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save History as PNG",
            os.path.join(os.path.expanduser("~"), "heatsync_history.png"),
            "PNG Images (*.png)")
        if path:
            self._content.grab().save(path)

    def save_geometry(self, settings: dict):
        g = self.geometry()
        settings["history_window"] = {
            "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}

    def _apply_theme_styles(self):
        self._title_lbl.setStyleSheet(
            f"color: {_THEME.cyan}; letter-spacing: 2px; background: transparent;")

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(_THEME.bg)))
        p.drawRoundedRect(r, 14.0, 14.0)
        p.setPen(QPen(QColor(_THEME.card_bd), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14.0, 14.0); p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.windowHandle()
            if h: h.startSystemMove()

    def closeEvent(self, e):
        self.hide(); e.ignore()


# ── Theme Swatch Button ───────────────────────────────────────────────────────
class _ThemeSwatch(QPushButton):
    """Mini visual theme preview button used in the Settings theme picker."""

    def __init__(self, theme_key: str, theme, parent=None):
        super().__init__(parent)
        self._key = theme_key
        self._t   = theme
        self.setCheckable(True)
        self.setFixedSize(116, 74)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(theme.display_name)
        self.setStyleSheet("border: none; background: transparent;")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t  = self._t
        w, h = self.width(), self.height()

        # Outer fill + border
        outer = QRectF(1.5, 1.5, w - 3, h - 3)
        p.setBrush(QBrush(QColor(t.bg)))
        sel = self.isChecked()
        p.setPen(QPen(QColor(t.cyan if sel else t.card_bd),
                      2.5 if sel else 1.0))
        p.drawRoundedRect(outer, 8, 8)

        # Mini card preview (upper portion)
        card_h = int(h * 0.60)
        card_r = QRectF(7, 7, w - 14, card_h - 6)
        p.setBrush(QBrush(QColor(t.card_bg)))
        p.setPen(QPen(QColor(t.card_bd), 0.8))
        p.drawRoundedRect(card_r, 4, 4)

        # Mini gauge arc inside the card
        arc_cx = card_r.left() + card_r.width() / 2
        arc_cy = card_r.top() + card_r.height() * 0.52
        arc_r2 = min(card_r.width(), card_r.height()) * 0.36
        arc_rect = QRectF(arc_cx - arc_r2, arc_cy - arc_r2,
                          arc_r2 * 2, arc_r2 * 2)
        # Track
        trk_col = QColor(t.card_bd); trk_col.setAlpha(200)
        p.setPen(QPen(trk_col, 3.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, int(225 * 16), int(-270 * 16))
        # Fill (70% at cyan color)
        p.setPen(QPen(QColor(t.cyan), 3.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect, int(225 * 16), int(-270 * 0.70 * 16))

        # Four accent color dots below arc
        dot_y  = card_r.bottom() - 6.0
        colors = [t.cyan, t.green, t.purple, t.amber]
        for i, col_hex in enumerate(colors):
            dx = arc_cx - 18 + i * 12
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(col_hex)))
            p.drawEllipse(QPointF(dx, dot_y), 3.5, 3.5)

        # Theme name at bottom
        f = QFont(); f.setPixelSize(10)
        if sel:
            f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QPen(QColor(t.txt_hi if sel else t.txt_mid)))
        p.drawText(QRectF(2, h - 19, w - 4, 17),
                   Qt.AlignmentFlag.AlignCenter, t.display_name)
        p.end()


# ── Settings Dialog ───────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None, preview_cb=None):
        super().__init__(parent)
        self.setWindowTitle("HeatSync Settings")
        self.setModal(True)
        self.setMinimumWidth(440)
        icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._settings          = dict(settings)
        self._original_settings = dict(settings)
        self._preview_cb        = preview_cb

        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Appearance tab ─────────────────────────────────────────────────
        ap = QWidget(); al = QVBoxLayout(ap)

        tg = QGroupBox("Theme")
        tg_lay = QGridLayout(tg)
        tg_lay.setSpacing(6)
        tg_lay.setContentsMargins(10, 14, 10, 10)
        self._theme_btn_grp: QButtonGroup = QButtonGroup(self)
        self._theme_btn_grp.setExclusive(True)
        self._theme_btns: dict[str, _ThemeSwatch] = {}
        cur_theme = settings.get("theme", "dark")
        # 5 columns × 2 rows
        _COLS = 5
        for idx, (key, th) in enumerate(THEMES.items()):
            btn = _ThemeSwatch(key, th, tg)
            self._theme_btn_grp.addButton(btn)
            self._theme_btns[key] = btn
            tg_lay.addWidget(btn, idx // _COLS, idx % _COLS)
        matched = self._theme_btns.get(cur_theme)
        if matched:
            matched.setChecked(True)
        elif self._theme_btns:
            next(iter(self._theme_btns.values())).setChecked(True)
        al.addWidget(tg)

        self._compact_cb = QCheckBox("Compact mode (smaller gauges, hide sparklines)")
        self._compact_cb.setChecked(settings.get("compact", False))
        al.addWidget(self._compact_cb)

        # Opacity
        op_grp = QGroupBox("Window Opacity"); op_lay = QHBoxLayout(op_grp)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(settings.get("opacity", 100))
        self._opacity_slider.setTickInterval(10)
        self._opacity_lbl = QLabel(f"{settings.get('opacity', 100)}%")
        self._opacity_lbl.setFixedWidth(36)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_lbl.setText(f"{v}%"))
        op_lay.addWidget(self._opacity_slider)
        op_lay.addWidget(self._opacity_lbl)
        al.addWidget(op_grp)

        al.addStretch()
        tabs.addTab(ap, "Appearance")

        # ── Gauges tab ────────────────────────────────────────────────────
        gp = QWidget(); gl = QVBoxLayout(gp)
        gauges_cfg = settings.get("gauges", {})
        self._gauge_cbs: dict[str, QCheckBox] = {}

        core_grp = QGroupBox("Core gauges"); cl = QVBoxLayout(core_grp)
        for key, label in [("cpu_usage", "CPU Usage"), ("cpu_temp", "CPU Temperature"),
                            ("gpu_usage", "GPU Usage"), ("gpu_temp", "GPU Temperature")]:
            cb = QCheckBox(label); cb.setChecked(gauges_cfg.get(key, True))
            self._gauge_cbs[key] = cb; cl.addWidget(cb)
        gl.addWidget(core_grp)

        opt_grp = QGroupBox("Optional gauges"); ol = QVBoxLayout(opt_grp)
        for key, label in [("network", "Network (Upload + Download Mbps)"),
                            ("battery", "Battery"),
                            ("fan",     "Fan RPMs"),
                            ("per_core","Per-core CPU")]:
            cb = QCheckBox(label); cb.setChecked(gauges_cfg.get(key, False))
            self._gauge_cbs[key] = cb; ol.addWidget(cb)
        gl.addWidget(opt_grp)

        gl.addStretch()
        tabs.addTab(gp, "Gauges")

        # ── Display tab ───────────────────────────────────────────────────
        dp = QWidget(); dl = QVBoxLayout(dp)
        dl.addWidget(QLabel("Move window to monitor:"))
        self._monitor_combo = QComboBox()
        screens = QApplication.screens()
        for i, scr in enumerate(screens):
            g = scr.geometry()
            self._monitor_combo.addItem(f"  {scr.name() or f'Screen {i+1}'}  ({g.width()}×{g.height()})")
        cur = settings.get("monitor", 0)
        self._monitor_combo.setCurrentIndex(min(cur, max(0, len(screens) - 1)))
        dl.addWidget(self._monitor_combo)

        # Refresh rate
        rr_grp = QGroupBox("Refresh Rate"); rr_lay = QHBoxLayout(rr_grp)
        self._refresh_combo = QComboBox()
        _refresh_opts = [("0.5 s", 500), ("1 s (default)", 1000),
                         ("2 s", 2000), ("5 s", 5000), ("10 s", 10000)]
        cur_ms = settings.get("refresh_ms", 1000)
        for label_txt, ms in _refresh_opts:
            self._refresh_combo.addItem(label_txt, ms)
        best_idx = 1
        for idx, (_, ms) in enumerate(_refresh_opts):
            if ms == cur_ms:
                best_idx = idx
                break
        self._refresh_combo.setCurrentIndex(best_idx)
        rr_lay.addWidget(self._refresh_combo)
        dl.addWidget(rr_grp)

        dl.addStretch()
        tabs.addTab(dp, "Display")

        # ── Startup tab ───────────────────────────────────────────────────
        sp = QWidget(); sl = QVBoxLayout(sp)
        self._autostart_cb = QCheckBox("Launch HeatSync automatically on login")
        self._autostart_cb.setChecked(settings.get("autostart", False))
        sl.addWidget(self._autostart_cb)
        sl.addStretch()
        tabs.addTab(sp, "Startup")

        # ── Data tab ──────────────────────────────────────────────────────
        ep = QWidget(); el = QVBoxLayout(ep)
        exp_cfg = settings.get("export", {})
        self._export_cb = QCheckBox("Enable data export")
        self._export_cb.setChecked(exp_cfg.get("enabled", False))
        el.addWidget(self._export_cb)

        pl = QHBoxLayout(); pl.addWidget(QLabel("Path:"))
        self._export_path = QLineEdit(exp_cfg.get("path", "~/.heatsync_data"))
        pl.addWidget(self._export_path); el.addLayout(pl)

        fg = QGroupBox("Format"); fl = QVBoxLayout(fg)
        self._fmt_csv  = QRadioButton("CSV (.csv)")
        self._fmt_json = QRadioButton("Newline-delimited JSON (.ndjson)")
        (self._fmt_json if exp_cfg.get("format") == "json"
         else self._fmt_csv).setChecked(True)
        fl.addWidget(self._fmt_csv); fl.addWidget(self._fmt_json)
        el.addWidget(fg)

        hl = QHBoxLayout(); hl.addWidget(QLabel("Keep history (hours):"))
        self._hours_spin = QSpinBox()
        self._hours_spin.setRange(1, 24)
        self._hours_spin.setValue(exp_cfg.get("max_hours", 1))
        hl.addWidget(self._hours_spin); hl.addStretch()
        el.addLayout(hl)
        el.addStretch()
        tabs.addTab(ep, "Data")

        # ── Alerts tab ────────────────────────────────────────────────────
        alp = QWidget(); all_ = QVBoxLayout(alp)
        self._alerts_master_cb = QCheckBox("Enable alerts")
        self._alerts_master_cb.setChecked(settings.get("alerts", True))
        all_.addWidget(self._alerts_master_cb)

        thr_cfg = {**_DEFAULT_SETTINGS["alert_thresholds"],
                   **settings.get("alert_thresholds", {})}
        aen_cfg = {**_DEFAULT_SETTINGS["alerts_enabled"],
                   **settings.get("alerts_enabled", {})}
        self._alert_en_cbs:    dict[str, QCheckBox] = {}
        self._alert_thr_spins: dict[str, QSpinBox]  = {}

        al_grp = QGroupBox("Per-metric thresholds")
        al_grp_lay = QVBoxLayout(al_grp); al_grp_lay.setSpacing(8)
        _alert_defs = [
            ("cpu_temp",  "CPU Temperature", "°C", 50, 120),
            ("gpu_temp",  "GPU Temperature", "°C", 50, 120),
            ("cpu_usage", "CPU Usage",        "%",  1, 100),
            ("gpu_usage", "GPU Usage",        "%",  1, 100),
        ]
        for key, label, suffix, lo, hi in _alert_defs:
            row = QHBoxLayout(); row.setSpacing(8)
            cb = QCheckBox(label); cb.setChecked(aen_cfg.get(key, True))
            cb.setMinimumWidth(160)
            self._alert_en_cbs[key] = cb
            spin = QSpinBox(); spin.setRange(lo, hi)
            spin.setValue(thr_cfg.get(key, 90))
            spin.setSuffix(suffix); spin.setFixedWidth(76)
            self._alert_thr_spins[key] = spin
            row.addWidget(cb)
            row.addWidget(QLabel("alert at:"))
            row.addWidget(spin)
            row.addStretch()
            al_grp_lay.addLayout(row)
        all_.addWidget(al_grp)
        all_.addStretch()
        tabs.addTab(alp, "Alerts")

        # ── Profiles tab ──────────────────────────────────────────────────
        pp = QWidget(); pl2 = QVBoxLayout(pp)
        profiles = settings.get("profiles", {})
        pl2.addWidget(QLabel("Saved profiles:"))
        self._profile_list = QComboBox()
        self._profile_list.addItem("(none)")
        for name in sorted(profiles.keys()):
            self._profile_list.addItem(name)
        active = settings.get("active_profile", "")
        idx = self._profile_list.findText(active) if active else 0
        self._profile_list.setCurrentIndex(max(0, idx))
        pl2.addWidget(self._profile_list)

        pbl = QHBoxLayout()
        load_btn = QLabel("<a href='load'>Load selected</a>")
        save_btn = QLabel("<a href='save'>Save as new…</a>")
        del_btn  = QLabel("<a href='del'>Delete selected</a>")
        for lbl in (load_btn, save_btn, del_btn):
            lbl.setOpenExternalLinks(False)
            lbl.setFont(_font(11))
            lbl.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
            pbl.addWidget(lbl)
        pbl.addStretch()
        pl2.addLayout(pbl)

        self._profile_name_edit = QLineEdit()
        self._profile_name_edit.setPlaceholderText("Profile name for 'Save as new…'")
        pl2.addWidget(self._profile_name_edit)
        pl2.addStretch()
        tabs.addTab(pp, "Profiles")

        # Connect profile actions
        def _load_profile():
            name = self._profile_list.currentText()
            if name == "(none)" or name not in profiles:
                return
            prof = profiles[name]
            for k, v in prof.items():
                if k == "gauges" and isinstance(v, dict):
                    for gk, gv in v.items():
                        if gk in self._gauge_cbs:
                            self._gauge_cbs[gk].setChecked(gv)
                elif k == "theme":
                    btn = self._theme_btns.get(str(v))
                    if btn:
                        btn.setChecked(True)
                    elif self._theme_btns:
                        self._theme_btns.get("dark",
                            next(iter(self._theme_btns.values()))).setChecked(True)
                elif k == "compact":
                    self._compact_cb.setChecked(bool(v))
                elif k == "opacity":
                    self._opacity_slider.setValue(int(v))
                elif k == "refresh_ms":
                    for ri in range(self._refresh_combo.count()):
                        if self._refresh_combo.itemData(ri) == int(v):
                            self._refresh_combo.setCurrentIndex(ri)
                            break
            self._settings["active_profile"] = name

        def _save_profile():
            name = self._profile_name_edit.text().strip()
            if not name:
                return
            snap = {
                "theme":        next(
                    (k for k, btn in self._theme_btns.items() if btn.isChecked()), "dark"),
                "compact":      self._compact_cb.isChecked(),
                "opacity":      self._opacity_slider.value(),
                "gauges":       {k: cb.isChecked() for k, cb in self._gauge_cbs.items()},
                "refresh_ms":   self._refresh_combo.currentData(),
            }
            profiles[name] = snap
            self._settings["profiles"] = profiles
            if self._profile_list.findText(name) < 0:
                self._profile_list.addItem(name)
            self._profile_list.setCurrentText(name)
            self._profile_name_edit.clear()

        def _del_profile():
            name = self._profile_list.currentText()
            if name == "(none)" or name not in profiles:
                return
            del profiles[name]
            self._settings["profiles"] = profiles
            idx2 = self._profile_list.currentIndex()
            self._profile_list.removeItem(idx2)

        load_btn.linkActivated.connect(lambda _: _load_profile())
        save_btn.linkActivated.connect(lambda _: _save_profile())
        del_btn.linkActivated.connect(lambda _: _del_profile())

        root.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # ── Wire up live-preview connections ──────────────────────────────
        for _btn in self._theme_btns.values():
            _btn.toggled.connect(lambda checked: checked and self._emit_preview())
        self._compact_cb.toggled.connect(lambda _: self._emit_preview())
        self._opacity_slider.valueChanged.connect(lambda _: self._emit_preview())
        self._refresh_combo.currentIndexChanged.connect(lambda _: self._emit_preview())
        for _cb in self._gauge_cbs.values():
            _cb.toggled.connect(lambda _: self._emit_preview())

    def get_settings(self) -> dict:
        d = dict(self._settings)
        d["theme"]      = next(
            (k for k, btn in self._theme_btns.items() if btn.isChecked()), "dark")
        d["compact"]    = self._compact_cb.isChecked()
        d["opacity"]    = self._opacity_slider.value()
        d["monitor"]    = self._monitor_combo.currentIndex()
        d["refresh_ms"] = self._refresh_combo.currentData()
        d["autostart"]  = self._autostart_cb.isChecked()

        gauges = dict(d.get("gauges", {}))
        for key, cb in self._gauge_cbs.items():
            gauges[key] = cb.isChecked()
        d["gauges"] = gauges

        exp = dict(d.get("export", {}))
        exp["enabled"]   = self._export_cb.isChecked()
        exp["path"]      = self._export_path.text().strip()
        exp["format"]    = "json" if self._fmt_json.isChecked() else "csv"
        exp["max_hours"] = self._hours_spin.value()
        d["export"] = exp

        d["alerts"]            = self._alerts_master_cb.isChecked()
        d["alert_thresholds"]  = {k: sp.value() for k, sp in self._alert_thr_spins.items()}
        d["alerts_enabled"]    = {k: cb.isChecked() for k, cb in self._alert_en_cbs.items()}

        d["profiles"]       = self._settings.get("profiles", {})
        d["active_profile"] = self._settings.get("active_profile", "")
        return d

    def _emit_preview(self):
        if self._preview_cb:
            self._preview_cb(self.get_settings())

    def reject(self):
        if self._preview_cb:
            self._preview_cb(self._original_settings)
        super().reject()
