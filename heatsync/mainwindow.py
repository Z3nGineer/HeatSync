"""
heatsync/mainwindow.py — _Background, MainWindow, entry-point main().
"""

import os
import sys
import json
import socket
import shutil
import tempfile
import time
import threading
from datetime import datetime

import psutil

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy,
    QGraphicsOpacityEffect, QSystemTrayIcon, QMenu, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QLoggingCategory, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush

from .constants import (
    IS_WINDOWS, IS_WAYLAND, VERSION,
    _SCRIPT_DIR, _SETTINGS_FILE,
    CYAN, GREEN, CPU_COLOR, GPU_COLOR,
)
from .theme import (
    _THEME, DARK_THEME, LIGHT_THEME,
    apply_theme, _make_palette, _make_tray_icon,
)
from .settings import (
    _DEFAULT_SETTINGS, _load_settings, _save_settings,
)
from .sensors import (
    s_cpu_usage, s_cpu_temp, s_gpu_usage, s_gpu_temp,
    s_gpu_power, s_ram, s_disk, s_network, s_battery,
    s_fans, s_cpu_per_core,
)
from .widgets import MonitorCard, NetworkPanel, FanRow, PerCoreRow
from .titlebar import TitleBar, ResizeGrip
from .statusbar import StatusBar
from .compact import CompactBar
from .dialogs import DataLogger, HistoryWindow, SettingsDialog
from .autostart import _set_autostart


# ── Rounded window background ─────────────────────────────────────────────────
class _Background(QWidget):
    _R = 16.0
    _compact = False

    def set_squared(self, squared):
        self._R = 0.0 if squared else 16.0; self.update()

    def set_compact(self, compact: bool):
        self._compact = compact; self.update()

    def paintEvent(self, _e):
        if self._compact:
            return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(_THEME.bg)))
        p.drawRoundedRect(r, self._R, self._R)
        p.setPen(QPen(QColor(_THEME.card_bd), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R); p.end()


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeatSync")

        if IS_WAYLAND:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(880, 520)
        self.resize(1080, 540)

        self._tray            = None
        self._docked          = False
        self._pre_dock_geom   = None
        self._dock_info       = None
        self._last_pos        = None
        self._tray_level      = "normal"
        self._history_win: HistoryWindow | None = None
        self._logger:      DataLogger    | None = None
        self._cards:       dict[str, MonitorCard] = {}
        self._benchmark_action = None
        self._bench_timer      = None
        self._bench_logger:    DataLogger | None = None
        self._bench_end_ts:    float = 0.0
        self._last_metrics:    dict  = {}
        self._version_checked  = False
        self._last_gauge_settings: dict = {}

        self._settings = _load_settings()
        self._apply_settings_pre_ui(self._settings)
        self._restore_pos()

        cw = _Background()
        self.setCentralWidget(cw)

        root = QVBoxLayout(cw)
        root.setContentsMargins(14, 8, 14, 12); root.setSpacing(8)

        self._title_bar = TitleBar(
            self, cpu_color=CPU_COLOR, gpu_color=GPU_COLOR,
            on_settings=self._open_settings,
            on_history=self._open_history,
        )
        root.addWidget(self._title_bar)

        self._div1 = QFrame(); self._div1.setFixedHeight(1)
        self._div1.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
        root.addWidget(self._div1)

        self._compact_bar = CompactBar(
            on_normal_mode=self._exit_compact_mode,
            on_settings=self._open_settings,
        )
        self._compact_bar.setVisible(False)
        root.addWidget(self._compact_bar)

        self._gauge_row_widget = QWidget()
        self._gauge_row_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._gauge_row = QHBoxLayout(self._gauge_row_widget)
        self._gauge_row.setSpacing(12)
        self._gauge_row.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._gauge_row_widget, 1)

        self._net_panel = NetworkPanel()
        self._net_panel.setVisible(False)
        root.addWidget(self._net_panel)

        self._fan_row = FanRow()
        self._fan_row.setVisible(False)
        root.addWidget(self._fan_row)

        self._per_core_row = PerCoreRow()
        self._per_core_row.setVisible(False)
        root.addWidget(self._per_core_row)

        self._div2 = QFrame(); self._div2.setFixedHeight(1)
        self._div2.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
        root.addWidget(self._div2)

        self._bot_bar = QWidget()
        self._bot_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        bot = QHBoxLayout(self._bot_bar); bot.setContentsMargins(0, 0, 0, 0); bot.setSpacing(0)
        self._sb = StatusBar()
        bot.addWidget(self._sb, 1); bot.addWidget(ResizeGrip(self))
        root.addWidget(self._bot_bar)

        self._rebuild_gauge_row(self._settings)
        self._apply_compact_geometry(self._settings.get("compact", False))
        self._apply_opacity(self._settings.get("opacity", 100))

        refresh_ms = self._settings.get("refresh_ms", 1000)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(refresh_ms)
        self._refresh()

        QTimer.singleShot(5000, self._check_version_bg)

        self._reconfigure_logger(self._settings)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            self._tray.setIcon(_make_tray_icon())
            self._tray.setToolTip(f"HeatSync {VERSION}")
            menu = QMenu()
            self._tray_toggle_action = menu.addAction("Hide HeatSync")
            self._tray_toggle_action.triggered.connect(self._toggle_visibility)
            menu.addSeparator()
            self._tray_aot_action = menu.addAction("Always on Top")
            self._tray_aot_action.setCheckable(True)
            self._tray_aot_action.setChecked(self._settings.get("always_on_top", False))
            self._tray_aot_action.triggered.connect(self._toggle_always_on_top)
            menu.addSeparator()
            menu.addAction("History…").triggered.connect(self._open_history)
            menu.addAction("Settings…").triggered.connect(self._open_settings)
            menu.addSeparator()
            menu.addAction("Copy Snapshot").triggered.connect(self._copy_snapshot)
            self._benchmark_action = menu.addAction("Benchmark Mode (30s)")
            self._benchmark_action.triggered.connect(self._start_benchmark)
            menu.addSeparator()
            menu.addAction("Check for Updates…").triggered.connect(self._check_version_manual)
            menu.addSeparator()
            menu.addAction("Quit").triggered.connect(QApplication.instance().quit)
            menu.aboutToShow.connect(self._update_tray_menu)
            self._tray.setContextMenu(menu)
            self._tray.show()
        else:
            self._tray = None
            print("[INFO] No system tray available — close button will quit.")

        if IS_WAYLAND:
            QTimer.singleShot(600, self._kwin_skip_taskbar)

        QApplication.instance().aboutToQuit.connect(self._on_quit)

        # Alert state
        self._alert_ticks:   dict[str, int]   = {}
        self._alert_notified: dict[str, float] = {}

        # Auto-follow system theme
        try:
            hints = QApplication.instance().styleHints()
            hints.colorSchemeChanged.connect(self._on_system_color_scheme)
        except Exception:
            pass

    # ── Settings helpers ───────────────────────────────────────────────────
    def _apply_opacity(self, opacity: int):
        cw = self.centralWidget()
        if opacity >= 100:
            cw.setGraphicsEffect(None)
        else:
            eff = QGraphicsOpacityEffect(cw)
            eff.setOpacity(opacity / 100.0)
            cw.setGraphicsEffect(eff)

    def _apply_settings_pre_ui(self, s: dict):
        """Apply theme from settings before any widgets are created."""
        import heatsync.theme as _theme_mod
        t = s.get("theme", "dark")
        if t == "light":
            _theme_mod._THEME = LIGHT_THEME
        elif t == "system":
            dark = QApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
            _theme_mod._THEME = DARK_THEME if dark else LIGHT_THEME
        else:
            _theme_mod._THEME = DARK_THEME
        if s.get("always_on_top", False):
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    def _on_system_color_scheme(self, scheme):
        if self._settings.get("theme", "dark") == "system":
            from PyQt6.QtCore import Qt as _Qt
            dark = (scheme == _Qt.ColorScheme.Dark)
            apply_theme(DARK_THEME if dark else LIGHT_THEME)

    def _apply_settings_live(self, s: dict):
        old_theme   = self._settings.get("theme", "dark")
        old_export  = self._settings.get("export", {})
        old_monitor = self._settings.get("monitor", 0)
        self._settings = s
        _save_settings(s)

        t = s.get("theme", "dark")
        if t == "light":   new_theme = LIGHT_THEME
        elif t == "system":
            dark = QApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
            new_theme = DARK_THEME if dark else LIGHT_THEME
        else:              new_theme = DARK_THEME
        if t != old_theme:
            apply_theme(new_theme)
            self._div1.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
            self._div2.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")

        self._apply_opacity(s.get("opacity", 100))
        apply_theme(_THEME)

        new_ms = s.get("refresh_ms", 1000)
        if new_ms != self._refresh_timer.interval():
            self._refresh_timer.setInterval(new_ms)

        self._rebuild_gauge_row(s)
        self._apply_compact_geometry(s.get("compact", False))

        new_monitor = s.get("monitor", 0)
        if new_monitor != old_monitor:
            self._move_to_monitor(new_monitor)

        _set_autostart(s.get("autostart", False))

        new_export = s.get("export", {})
        if new_export != old_export:
            self._reconfigure_logger(s)

        if self._history_win and self._history_win.isVisible():
            self._history_win._build_sparklines(s)

    def _reconfigure_logger(self, s: dict):
        if self._logger:
            self._logger.close()
            self._logger = None
        exp = s.get("export", {})
        if exp.get("enabled", False):
            self._logger = DataLogger(
                exp.get("path", "~/.heatsync_data"),
                exp.get("format", "csv"),
                exp.get("max_hours", 1),
            )

    # ── Snapshot export ────────────────────────────────────────────────────
    def _copy_snapshot(self):
        lines = [f"HeatSync Snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        m = self._last_metrics
        if not m:
            lines.append("(No data yet)")
        else:
            labels = {
                "cpu_usage": "CPU Usage", "cpu_temp": "CPU Temp",
                "gpu_usage": "GPU Usage", "gpu_temp": "GPU Temp",
                "net_up":    "Net Upload", "net_down": "Net Download",
                "battery":   "Battery",
            }
            units = {
                "cpu_usage": "%", "cpu_temp": "°C",
                "gpu_usage": "%", "gpu_temp": "°C",
                "net_up":    " Mbps", "net_down": " Mbps",
                "battery":   "%",
            }
            for key, lbl in labels.items():
                if key in m:
                    lines.append(f"  {lbl:<18} {m[key]:.1f}{units.get(key, '')}")
            try:
                u, t, p = s_ram()
                lines.append(f"  {'RAM':<18} {u:.1f} / {t:.0f} GB  ({p:.0f}%)")
            except Exception:
                pass
        QApplication.clipboard().setText("\n".join(lines))
        if self._tray:
            self._tray.showMessage("HeatSync", "Snapshot copied to clipboard.",
                                   QSystemTrayIcon.MessageIcon.Information, 2000)

    # ── Benchmark mode ─────────────────────────────────────────────────────
    def _start_benchmark(self):
        if self._bench_timer and self._bench_timer.isActive():
            self._stop_benchmark()
            return
        bench_path = os.path.join(os.path.expanduser("~"),
                                  f"heatsync_bench_{int(time.time())}.csv")
        self._bench_logger = DataLogger(bench_path, "csv", max_hours=1)
        self._bench_end_ts = time.monotonic() + 30.0
        self._bench_timer  = QTimer(self)
        self._bench_timer.timeout.connect(self._bench_tick)
        self._bench_timer.start(100)
        if self._benchmark_action:
            self._benchmark_action.setText("Stop Benchmark")
        if self._tray:
            self._tray.showMessage("HeatSync", "Benchmark started (30s @ 100ms).",
                                   QSystemTrayIcon.MessageIcon.Information, 2000)

    def _bench_tick(self):
        if time.monotonic() >= self._bench_end_ts:
            self._stop_benchmark()
            return
        metrics = {
            "cpu_usage": s_cpu_usage(),
            "cpu_temp":  s_cpu_temp(),
            "gpu_usage": s_gpu_usage(),
            "gpu_temp":  s_gpu_temp(),
            "gpu_power": s_gpu_power(),
        }
        if self._bench_logger:
            self._bench_logger.record(metrics)

    def _stop_benchmark(self):
        if self._bench_timer:
            self._bench_timer.stop()
            self._bench_timer = None
        csv_path = ""
        if self._bench_logger:
            self._bench_logger.flush()
            csv_path = os.path.join(self._bench_logger._path, "heatsync_data.csv")
            self._bench_logger.close()
            self._bench_logger = None
        if self._benchmark_action:
            self._benchmark_action.setText("Benchmark Mode (30s)")
        if self._tray and csv_path:
            self._tray.showMessage("HeatSync", f"Benchmark saved:\n{csv_path}",
                                   QSystemTrayIcon.MessageIcon.Information, 4000)

    # ── Version checker ────────────────────────────────────────────────────
    def _check_version_bg(self):
        if self._version_checked:
            return
        self._version_checked = True
        threading.Thread(target=self._do_version_check,
                         args=(False,), daemon=True).start()

    def _check_version_manual(self):
        threading.Thread(target=self._do_version_check,
                         args=(True,), daemon=True).start()

    def _do_version_check(self, manual: bool):
        try:
            import urllib.request, urllib.error
            url = "https://raw.githubusercontent.com/mackm/HeatSync/main/VERSION"
            with urllib.request.urlopen(url, timeout=5) as resp:
                remote = resp.read().decode().strip()
            if not remote:
                if manual and self._tray:
                    QTimer.singleShot(0, lambda: self._tray.showMessage(
                        "HeatSync", "Could not read remote version.",
                        QSystemTrayIcon.MessageIcon.Warning, 3000))
                return
            remote_v = remote.lstrip("v")
            local_v  = VERSION.lstrip("v")
            if remote_v != local_v:
                msg = f"Update available: v{remote_v} (you have {VERSION})"
            else:
                msg = f"HeatSync is up to date ({VERSION})" if manual else ""
            if msg and self._tray:
                _msg = msg
                QTimer.singleShot(0, lambda: self._tray.showMessage(
                    "HeatSync", _msg,
                    QSystemTrayIcon.MessageIcon.Information, 5000))
        except Exception:
            if manual and self._tray:
                QTimer.singleShot(0, lambda: self._tray.showMessage(
                    "HeatSync", "Version check failed (no internet?).",
                    QSystemTrayIcon.MessageIcon.Warning, 3000))

    def _apply_compact_geometry(self, compact: bool):
        if compact:
            h = 46 + 20
            self.setMinimumSize(600, h)
            if self.width() < 600 or self.height() != h:
                self.resize(max(self.width(), 700), h)
        else:
            self.setMinimumSize(880, 520)
            if self.height() < 520:
                self.resize(max(self.width(), 880), 540)

    def _rebuild_gauge_row(self, s: dict):
        compact = s.get("compact", False)

        _gauge_key = {
            "compact":      compact,
            "gauges":       s.get("gauges", {}),
            "gauge_colors": s.get("gauge_colors", {}),
        }
        if _gauge_key == self._last_gauge_settings:
            return
        self._last_gauge_settings = dict(_gauge_key)

        while self._gauge_row.count():
            item = self._gauge_row.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        gauges = s.get("gauges", _DEFAULT_SETTINGS["gauges"])

        cw = self.centralWidget()
        if isinstance(cw, _Background):
            cw.set_compact(compact)
        self._compact_bar.setVisible(compact)
        self._title_bar.setVisible(not compact)
        self._div1.setVisible(not compact)
        self._gauge_row_widget.setVisible(not compact)
        self._div2.setVisible(not compact)
        self._bot_bar.setVisible(not compact)

        if compact:
            self._net_panel.setVisible(False)
            self._fan_row.setVisible(False)
            self._per_core_row.setVisible(False)
            return

        card_defs = [
            ("cpu_usage", "CPU USAGE", "%",   0, 100, CYAN,      70, 90,  False, False, True),
            ("cpu_temp",  "CPU TEMP",  "°C",  0, 105, CPU_COLOR, 80, 95,  True,  False, False),
            ("gpu_usage", "GPU USAGE", "%",   0, 100, CYAN,     200, 200, False, False, True),
            ("gpu_temp",  "GPU TEMP",  "°C",  0,  95, GPU_COLOR, 75, 88,  True,  False, False),
        ]
        gc = s.get("gauge_colors", {})
        for key, label, unit, lo, hi, color, warn, danger, is_temp, inv, is_usage in card_defs:
            if not gauges.get(key, True):
                continue
            eff_color = gc.get(key) or color
            if key not in self._cards:
                self._cards[key] = MonitorCard(label, unit, lo, hi, eff_color,
                                               warn, danger, is_temp=is_temp,
                                               invert_warn=inv, is_usage=is_usage,
                                               resource_key=key,
                                               on_set_threshold=self._on_set_threshold)
            else:
                self._cards[key].set_color(eff_color)
            self._gauge_row.addWidget(self._cards[key])

        self._net_panel.setVisible(gauges.get("network", False))

        if gauges.get("battery", False):
            if s_battery() is not None:
                bat_color = gc.get("battery") or GREEN
                if "battery" not in self._cards:
                    self._cards["battery"] = MonitorCard(
                        "BATTERY", "%", 0, 100, bat_color, 20, 10, invert_warn=True,
                        resource_key="battery")
                else:
                    self._cards["battery"].set_color(bat_color)
                self._gauge_row.addWidget(self._cards["battery"])

        self._fan_row.setVisible(gauges.get("fan", False))
        self._per_core_row.setVisible(gauges.get("per_core", False))

    # ── Refresh ────────────────────────────────────────────────────────────
    def _refresh(self):
        s      = self._settings
        gauges = s.get("gauges", {})
        metrics: dict[str, float] = {}

        def _push(key: str, value: float):
            if key in self._cards:
                self._cards[key].push(value)
            metrics[key] = value

        if gauges.get("cpu_usage", True):  _push("cpu_usage", s_cpu_usage())
        if gauges.get("cpu_temp",  True):  _push("cpu_temp",  s_cpu_temp())
        if gauges.get("gpu_usage", True):  _push("gpu_usage", s_gpu_usage())
        if gauges.get("gpu_temp",  True):  _push("gpu_temp",  s_gpu_temp())

        if s.get("compact", False):
            up, dn = s_network()
            ram_u, ram_t, _ = s_ram()
            disk_u, disk_t, _ = s_disk()
            self._compact_bar.update_values(
                metrics.get("cpu_usage", 0), metrics.get("cpu_temp", 0),
                metrics.get("gpu_usage", 0), metrics.get("gpu_temp", 0),
                ram_used=ram_u, ram_tot=ram_t,
                net_up=up, net_down=dn,
                disk_used=disk_u, disk_tot=disk_t,
            )

        if gauges.get("network", False):
            up, down = s_network()
            self._net_panel.update_network(up, down)
            metrics["net_up"] = up; metrics["net_down"] = down

        if gauges.get("battery", False):
            bat = s_battery()
            if bat is not None:
                _push("battery", bat[0])

        if gauges.get("fan", False) and self._fan_row.isVisible():
            self._fan_row.update_fans(s_fans())

        if gauges.get("per_core", False) and self._per_core_row.isVisible():
            self._per_core_row.update_values(s_cpu_per_core())

        self._sb.refresh()

        self._last_metrics = dict(metrics)

        if self._logger and metrics:
            self._logger.record(metrics)
            if time.monotonic() - self._logger._last_flush > 60:
                self._logger.flush()

        if self._history_win and self._history_win.isVisible():
            for key, val in metrics.items():
                self._history_win.update_metric(key, val)

        load_vals = [metrics.get(k, 0) for k in ("cpu_usage", "gpu_usage") if k in metrics]
        temp_vals_pct = [
            metrics.get("cpu_temp", 0) / 95.0 * 100,
            metrics.get("gpu_temp", 0) / 88.0 * 100,
        ]
        combined = max((load_vals or [0]) + temp_vals_pct)
        level = "danger" if combined > 90 else ("warn" if combined > 75 else "normal")
        if level != self._tray_level and self._tray:
            self._tray_level = level
            self._tray.setIcon(_make_tray_icon(level))

        if self._settings.get("alerts", True) and self._tray:
            _thr = {**_DEFAULT_SETTINGS["alert_thresholds"],
                    **self._settings.get("alert_thresholds", {})}
            alert_defs = [
                ("cpu_temp",  metrics.get("cpu_temp",  0), _thr["cpu_temp"],  "CPU Temperature"),
                ("gpu_temp",  metrics.get("gpu_temp",  0), _thr["gpu_temp"],  "GPU Temperature"),
                ("cpu_usage", metrics.get("cpu_usage", 0), _thr["cpu_usage"], "CPU Usage"),
                ("gpu_usage", metrics.get("gpu_usage", 0), _thr["gpu_usage"], "GPU Usage"),
            ]
            now = time.monotonic()
            for key, val, threshold, label in alert_defs:
                if val >= threshold:
                    self._alert_ticks[key] = self._alert_ticks.get(key, 0) + 1
                else:
                    self._alert_ticks[key] = 0
                if (self._alert_ticks.get(key, 0) >= 10 and
                        now - self._alert_notified.get(key, 0) > 300):
                    self._alert_notified[key] = now
                    self._tray.showMessage(
                        "HeatSync Alert",
                        f"{label} has been critically high for 10+ seconds",
                        QSystemTrayIcon.MessageIcon.Warning, 5000)

    # ── Settings / History dialogs ─────────────────────────────────────────
    def _exit_compact_mode(self):
        s = dict(self._settings); s["compact"] = False
        _save_settings(s)
        self._apply_settings_live(s)

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, parent=self,
                             preview_cb=self._apply_settings_live)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_s = dlg.get_settings()
            self._apply_settings_live(new_s)
            self._save_pos()

    def _open_history(self):
        if self._history_win is None:
            self._history_win = HistoryWindow(self._settings)
            if self._logger:
                self._history_win.populate_from_logger(self._logger)
        self._history_win.show()
        self._history_win.raise_()

    # ── Monitor support ────────────────────────────────────────────────────
    def _move_to_monitor(self, idx: int):
        screens = QApplication.screens()
        if 0 <= idx < len(screens):
            geom = screens[idx].availableGeometry()
            self.move(geom.topLeft() + QPoint(50, 50))

    # ── Geometry persistence ───────────────────────────────────────────────
    def _restore_pos(self):
        self._pending_restore = None
        d = self._settings
        if d.get("x") is not None and d.get("y") is not None:
            self._pending_restore = d
        if d.get("docked") and d.get("dock_x") is not None:
            self._dock_info = {
                "dock_x": d["dock_x"],
                "dock_y": d["dock_y"],
                "dock_w": d.get("dock_w"),
            }

    def _save_pos(self):
        try:
            d = _load_settings()
            g = self.geometry()
            px, py = (self._last_pos if self._last_pos else (g.x(), g.y()))
            compact = self._settings.get("compact", False)
            if compact:
                d["compact_pos"] = {"x": px, "y": py}
            else:
                d.update({"x": px, "y": py, "w": g.width(), "h": g.height(),
                          "docked": self._docked})
                if self._docked and self._dock_info:
                    d.update(self._dock_info)
                    if self._pre_dock_geom is not None:
                        d["pre_dock_w"] = self._pre_dock_geom.width()
                        d["pre_dock_h"] = self._pre_dock_geom.height()
            for key in ("theme", "compact", "gauges", "monitor", "autostart",
                        "export", "always_on_top", "alerts", "opacity",
                        "refresh_ms", "profiles", "active_profile",
                        "gauge_colors", "alert_thresholds"):
                d[key] = self._settings.get(key, d.get(key))
            if self._history_win:
                self._history_win.save_geometry(d)
            _save_settings(d)
        except Exception:
            pass

    def _on_quit(self):
        if self._logger:
            self._logger.close()
        self._save_pos()

    def _on_set_threshold(self, key: str, value: int):
        s = dict(self._settings)
        thr = dict(s.get("alert_thresholds", _DEFAULT_SETTINGS["alert_thresholds"]))
        thr[key] = value
        s["alert_thresholds"] = thr
        self._settings = s
        _save_settings(s)

    # ── Resize / move / show events ────────────────────────────────────────
    def resizeEvent(self, e):
        super().resizeEvent(e)
        mw, mh = self.minimumWidth(), self.minimumHeight()
        if self.width() < mw or self.height() < mh:
            self.resize(max(self.width(), mw), max(self.height(), mh))

    def moveEvent(self, event):
        super().moveEvent(event)
        p = event.pos()
        if p.x() == 0 and p.y() == 0:
            return
        self._last_pos = (p.x(), p.y())

    def showEvent(self, event):
        super().showEvent(event)
        d = self._pending_restore
        if not d:
            return
        self._pending_restore = None
        self._apply_state(d, first_show=True)

    def _apply_state(self, d, first_show=True):
        docked = d.get("docked", False)
        x, y   = d.get("x"), d.get("y")
        w, h   = d.get("w"), d.get("h")
        dock_x = d.get("dock_x", x)
        dock_y = d.get("dock_y", y)
        dock_w = d.get("dock_w", w)
        delay  = 700 if first_show else 500

        def apply():
            compact = self._settings.get("compact", False)
            if compact:
                cp = d.get("compact_pos", {})
                cx, cy = cp.get("x"), cp.get("y")
                if cx is not None and cy is not None:
                    if IS_WAYLAND:
                        self._kwin_move(cx, cy)
                    else:
                        self.move(cx, cy)
                    self._last_pos = (cx, cy)
                return
            if docked:
                dw = dock_w or w or self.width()
                dh = h or self.height()
                pre_w = d.get("pre_dock_w") or 1080
                pre_h = d.get("pre_dock_h") or 540
                self._pre_dock_geom = QRect(int(dock_x or 0), int(dock_y or 0), pre_w, pre_h)
                if IS_WAYLAND:
                    self._kwin_set_geometry(dock_x, dock_y, dw, dh)
                else:
                    self.resize(dw, dh); self.move(dock_x, dock_y)
                if not self._docked:
                    self._docked = True
                    cw = self.centralWidget()
                    if isinstance(cw, _Background): cw.set_squared(True)
                    self._title_bar.dock_btn.set_active(True)
            else:
                if w and h:
                    self.resize(w, h)
                if x is not None and y is not None:
                    if IS_WAYLAND:
                        if w and h: self._kwin_set_geometry(x, y, w, h)
                        else: self._kwin_move(x, y)
                    else:
                        self.move(x, y)
                    self._last_pos = (x, y)

        QTimer.singleShot(delay if IS_WAYLAND else 0, apply)

    def _toggle_always_on_top(self, checked: bool):
        s = dict(self._settings); s["always_on_top"] = checked
        _save_settings(s); self._settings = s
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags); self.show()

    def _update_tray_menu(self):
        self._tray_toggle_action.setText(
            "Hide HeatSync" if self.isVisible() else "Show HeatSync")
        if hasattr(self, "_tray_aot_action"):
            self._tray_aot_action.setChecked(self._settings.get("always_on_top", False))

    def closeEvent(self, e):
        if self._tray and self._tray.isVisible():
            self._save_pos(); self.hide(); e.ignore()
        else:
            self._save_pos(); e.accept()

    def _toggle_visibility(self):
        if self.isVisible():
            self._save_pos(); self.hide()
        else:
            self.show(); self.raise_(); self.activateWindow()
            if IS_WAYLAND:
                QTimer.singleShot(400, self._kwin_skip_taskbar)
                try:
                    with open(_SETTINGS_FILE) as f:
                        self._apply_state(json.load(f), first_show=False)
                except Exception:
                    pass

    # ── KWin scripting ─────────────────────────────────────────────────────
    def _kwin_run(self, js: str, tag: str = "hs") -> bool:
        if not IS_WAYLAND: return False
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if not qdbus: return False
        plugin = f"{tag}_{os.getpid()}_{int(time.monotonic() * 1000) & 0xFFFFFF}"
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as fh:
                fh.write(js); tmp = fh.name
            import subprocess
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.loadScript", tmp, plugin],
                           capture_output=True, timeout=3)
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", plugin],
                           capture_output=True, timeout=3)
            os.unlink(tmp)
            return True
        except Exception as e:
            print(f"[WARN] KWin script failed ({tag}): {e}")
            return False

    def _kwin_skip_taskbar(self):
        self._kwin_run(
            "var wins = workspace.windowList();"
            "for (var i = 0; i < wins.length; i++) {"
            "  if (wins[i].resourceClass === 'heatsync') {"
            "    wins[i].skipTaskbar = true; wins[i].skipPager = true; break;"
            "  }}", tag="hs_skiptb")

    def _kwin_move(self, x: int, y: int) -> bool:
        return self._kwin_run(
            f"var wins = workspace.windowList();"
            f"for (var i = 0; i < wins.length; i++) {{"
            f"  if (wins[i].resourceClass === 'heatsync') {{"
            f"    var g = wins[i].frameGeometry;"
            f"    wins[i].frameGeometry = {{x:{x}, y:{y}, width:g.width, height:g.height}};"
            f"    break; }}}}", tag="hs_move")

    def _kwin_set_geometry(self, x: int, y: int, w: int, h: int) -> bool:
        return self._kwin_run(
            f"var wins = workspace.windowList();"
            f"for (var i = 0; i < wins.length; i++) {{"
            f"  if (wins[i].resourceClass === 'heatsync') {{"
            f"    wins[i].frameGeometry = {{x:{x}, y:{y}, width:{w}, height:{h}}};"
            f"    break; }}}}", tag="hs_geom")

    # ── Dock toggle ────────────────────────────────────────────────────────
    def toggle_dock(self, via_drag: bool = False):
        cw      = self.centralWidget()
        compact = self._settings.get("compact", False)
        cur_screen = QApplication.screenAt(self.frameGeometry().center()) or self.screen()
        if not self._docked:
            self._pre_dock_geom = self.geometry()
            ag = cur_screen.availableGeometry()
            tx, ty = ag.x(), ag.y()
            dw, dh = ag.width(), self.height()
            self._dock_info = {"dock_x": tx, "dock_y": ty, "dock_w": dw}
            if IS_WAYLAND:
                self.resize(dw, dh)
                QTimer.singleShot(250, lambda: self._kwin_set_geometry(tx, ty, dw, dh))
            else:
                self.resize(dw, dh); self.move(tx, ty)
            self._docked = True
            if isinstance(cw, _Background): cw.set_squared(True)
        else:
            if self._pre_dock_geom is not None:
                pw = self._pre_dock_geom.width()
                ph = self.height() if compact else self._pre_dock_geom.height()
                if not via_drag:
                    px, py = self._pre_dock_geom.x(), self._pre_dock_geom.y()
                    if IS_WAYLAND:
                        self.resize(pw, ph)
                        QTimer.singleShot(250, lambda: self._kwin_set_geometry(px, py, pw, ph))
                    else:
                        self.resize(pw, ph); self.move(px, py)
                else:
                    self.resize(pw, ph)
            self._docked = False
            if isinstance(cw, _Background): cw.set_squared(False)
        if not compact:
            self._title_bar.dock_btn.set_active(self._docked)
        for card in self._cards.values():
            card.update()
        self._gauge_row_widget.updateGeometry()


# ── Single-instance lock ──────────────────────────────────────────────────────
_LOCK_SOCK = None

def _acquire_instance_lock() -> bool:
    global _LOCK_SOCK
    try:
        if sys.platform == "linux":
            _LOCK_SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _LOCK_SOCK.bind("\0heatsync_instance_v1")
        else:
            _LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _LOCK_SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            _LOCK_SOCK.bind(("127.0.0.1", 47321))
        return True
    except OSError:
        return False


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    if not _acquire_instance_lock():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName("HeatSync")
    if IS_WAYLAND:
        app.setDesktopFileName("heatsync")
        QLoggingCategory.setFilterRules("qt.qpa.services.warning=false")
    app.setStyle("Fusion")

    app.setPalette(_make_palette(_THEME))

    win = MainWindow()
    app.setPalette(_make_palette(_THEME))
    win.show()
    sys.exit(app.exec())
