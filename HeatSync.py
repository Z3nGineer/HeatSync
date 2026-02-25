#!/usr/bin/env python3
"""
HeatSync — NZXT CAM-style system monitor
Supports Linux (X11 + Wayland/KWin) and Windows.
"""

import sys
import os
import glob
import json
import math
import socket
import warnings
import subprocess
import shutil
import tempfile
import time
import platform
import csv as _csv
from collections import deque
from dataclasses import dataclass
from datetime import datetime

# ── Venv auto-reexec ─────────────────────────────────────────────────────────
_SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".heatsync.json")
if sys.platform == "win32":
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "Scripts", "python.exe")
else:
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "bin", "python")
    _VENV_PY_LEGACY = os.path.expanduser("~/.sysmon_venv/bin/python")
    if not os.path.exists(_VENV_PY) and os.path.exists(_VENV_PY_LEGACY):
        _VENV_PY = _VENV_PY_LEGACY

if (not getattr(sys, "frozen", False)
        and os.path.exists(_VENV_PY)
        and os.path.abspath(sys.executable) != os.path.abspath(_VENV_PY)):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

import psutil
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QSystemTrayIcon, QMenu,
    QDialog, QDialogButtonBox, QTabWidget, QGroupBox,
    QRadioButton, QCheckBox, QComboBox, QLineEdit, QSpinBox,
    QScrollArea, QGridLayout, QSlider, QMessageBox,
)
from PyQt6.QtCore  import Qt, QTimer, QRect, QRectF, QPointF, QPoint, QLoggingCategory
from PyQt6.QtGui   import (
    QPainter, QColor, QPen, QFont, QPainterPath,
    QLinearGradient, QRadialGradient, QBrush, QPalette,
    QIcon, QPixmap, QAction,
)

# ── Version ───────────────────────────────────────────────────────────────────
def _get_version() -> str:
    bases = ([sys._MEIPASS] if getattr(sys, 'frozen', False) else []) + [_SCRIPT_DIR]
    for base in bases:
        try:
            with open(os.path.join(base, "VERSION")) as f:
                v = f.read().strip()
                if v:
                    return f"v{v}" if not v.startswith("v") else v
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=3, cwd=_SCRIPT_DIR,
        )
        if r.returncode == 0:
            tag = r.stdout.strip()
            if tag:
                return tag
    except Exception:
        pass
    return "v1.0.69"

VERSION = _get_version()

# ── Platform flags ────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_WAYLAND = (sys.platform == "linux" and
              bool(os.environ.get("WAYLAND_DISPLAY") or
                   os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"))

# ── GPU init ──────────────────────────────────────────────────────────────────
GPU_HANDLE  = None
GPU_NAME    = "GPU Unavailable"
_AMD_DEV    = None
_AMD_HWMON  = None
_INTEL_DEV  = None
_INTEL_HWMON = None

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pynvml
    pynvml.nvmlInit()
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _n = pynvml.nvmlDeviceGetName(GPU_HANDLE)
    GPU_NAME = _n.decode() if isinstance(_n, bytes) else _n
except Exception:
    pass

if not GPU_HANDLE and sys.platform == "linux":
    def _gpu_name_from_sysfs(card: str, fallback: str) -> str:
        try:
            with open(os.path.join(card, "product_name")) as f:
                n = f.read().strip()
                if n: return n
        except Exception:
            pass
        try:
            with open(os.path.join(card, "uevent")) as f:
                slot = next((l.split("=",1)[1].strip() for l in f
                             if l.startswith("PCI_SLOT_NAME=")), None)
            if slot:
                r = subprocess.run(["lspci", "-s", slot],
                                   capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    parts = r.stdout.strip().split(":", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
        except Exception:
            pass
        return fallback

    _cards: list[tuple[str, str]] = []
    for _card in sorted(glob.glob("/sys/class/drm/card*/device")):
        try:
            with open(os.path.join(_card, "vendor")) as _f:
                _cards.append((_f.read().strip(), _card))
        except Exception:
            pass

    for _wanted in ("0x1002", "0x8086"):
        for _vendor, _card in _cards:
            if _vendor != _wanted:
                continue
            _hw = glob.glob(os.path.join(_card, "hwmon", "hwmon*"))
            _hwmon = _hw[0] if _hw else None
            if _wanted == "0x1002":
                _AMD_DEV, _AMD_HWMON = _card, _hwmon
                GPU_NAME = _gpu_name_from_sysfs(_card, "AMD GPU")
                print(f"[INFO] AMD GPU: {GPU_NAME}")
            else:
                _INTEL_DEV, _INTEL_HWMON = _card, _hwmon
                GPU_NAME = _gpu_name_from_sysfs(_card, "Intel GPU")
                print(f"[INFO] Intel GPU: {GPU_NAME}")
            break
        if _AMD_DEV or _INTEL_DEV:
            break
    else:
        print("[WARN] No supported GPU found (NVIDIA, AMD, or Intel)")

# ── Theme ─────────────────────────────────────────────────────────────────────
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

# Hardware vendor brand colors — never change with theme
NVIDIA_GREEN = "#76b900"
AMD_RED      = "#ed1c24"
INTEL_BLUE   = "#0071c5"

# Shorthand accent constants kept for default-arg use; always equal dark theme
CYAN   = "#00ccdd"
GREEN  = "#00e676"
PURPLE = "#9d6fff"
AMBER  = "#ffa040"
C_WARN = "#ff9800"
C_DANG = "#f44336"


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


# Gauge face text is always near-white — the face interior is always dark
_GAUGE_TXT    = "#dde4f0"
_GAUGE_TXT_MID = "#6878a0"


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


# ── CPU / GPU name helpers ────────────────────────────────────────────────────
def _get_cpu_name() -> str:
    if IS_WINDOWS:
        return platform.processor() or "CPU"
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"

def _cpu_vendor_color() -> str:
    name = _get_cpu_name().upper()
    if any(k in name for k in ("AMD", "RYZEN", "EPYC", "ATHLON", "THREADRIPPER")):
        return AMD_RED
    if any(k in name for k in ("INTEL", "CORE", "XEON", "PENTIUM", "CELERON", "I3", "I5", "I7", "I9")):
        return INTEL_BLUE
    return CYAN

def _gpu_vendor_color() -> str:
    if GPU_HANDLE:   return NVIDIA_GREEN
    if _AMD_DEV:     return AMD_RED
    if _INTEL_DEV:   return INTEL_BLUE
    return PURPLE

CPU_COLOR = _cpu_vendor_color()
GPU_COLOR = _gpu_vendor_color()

# ── Default settings + persistence ────────────────────────────────────────────
_DEFAULT_SETTINGS: dict = {
    "theme": "dark",
    "compact": False,
    "gauges": {
        "cpu_usage": True,  "cpu_temp": True,
        "gpu_usage": True,  "gpu_temp": True,
        "network":   False, "battery":  False,
        "fan":       False, "per_core": False,
    },
    "monitor":   0,
    "always_on_top": False,
    "alerts":    True,
    "autostart": False,
    "compact_pos": {"x": None, "y": None},
    "export": {
        "enabled":   False,
        "path":      "~/.heatsync_data",
        "format":    "csv",
        "max_hours": 1,
    },
    "history_window": {"x": None, "y": None, "w": 900, "h": 400},
    "opacity":        100,
    "refresh_ms":     1000,
    "profiles":       {},
    "active_profile": "",
    "gauge_colors":   {
        "cpu_usage": None,
        "cpu_temp":  None,
        "gpu_usage": None,
        "gpu_temp":  None,
        "network":   None,
        "battery":   None,
    },
}


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE) as f:
            stored = json.load(f)
    except Exception:
        stored = {}
    result = dict(_DEFAULT_SETTINGS)
    for k, v in stored.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    return result


def _save_settings(d: dict) -> None:
    try:
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass


# ── Sensors ───────────────────────────────────────────────────────────────────
psutil.cpu_percent()   # prime

def s_cpu_usage() -> float:
    return psutil.cpu_percent()

def s_cpu_temp() -> float:
    if IS_WINDOWS:
        try:
            import wmi  # type: ignore
            w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Temperature" and "CPU" in s.Name and "Package" in s.Name:
                    return float(s.Value)
        except Exception:
            pass
        return 0.0
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return 0.0
        _PREF: list[tuple[str, tuple[str, ...]]] = [
            ("k10temp",    ("Tctl", "Tdie", "Tccd1")),
            ("zenpower",   ("Tctl", "Tdie")),
            ("coretemp",   ("Package id 0", "Physical id 0")),
            ("cpu_thermal", ()),
            ("acpitz",     ()),
        ]
        for key, good_labels in _PREF:
            if key not in temps:
                continue
            entries = temps[key]
            if good_labels:
                hit = next((e.current for e in entries if e.label in good_labels), None)
                if hit is not None:
                    return hit
            if entries:
                return entries[0].current
        def _plausible(v: float) -> bool: return 20.0 <= v <= 120.0
        for prefer_cpu in (True, False):
            for key, entries in temps.items():
                if prefer_cpu and "cpu" not in key.lower():
                    continue
                for e in entries:
                    if _plausible(e.current):
                        return e.current
    except Exception:
        pass
    return 0.0

def s_gpu_usage() -> float:
    if GPU_HANDLE:
        try:
            return float(pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE).gpu)
        except Exception:
            return 0.0
    if _AMD_DEV:
        try:
            with open(os.path.join(_AMD_DEV, "gpu_busy_percent")) as f:
                return float(f.read().strip())
        except Exception:
            return 0.0
    if _INTEL_DEV:
        if _INTEL_HWMON:
            try:
                cur = float(open(os.path.join(_INTEL_HWMON, "freq0_input")).read().strip())
                mx  = float(open(os.path.join(_INTEL_HWMON, "freq0_max")).read().strip())
                if mx > 0:
                    return min(100.0, cur / mx * 100.0)
            except Exception:
                pass
        return 0.0
    return 0.0

def s_gpu_temp() -> float:
    if GPU_HANDLE:
        try:
            return float(pynvml.nvmlDeviceGetTemperature(
                GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:
            return 0.0
    if _AMD_DEV:
        if _AMD_HWMON:
            try:
                with open(os.path.join(_AMD_HWMON, "temp1_input")) as f:
                    return float(f.read().strip()) / 1000.0
            except Exception:
                pass
        try:
            temps = psutil.sensors_temperatures()
            if "amdgpu" in temps and temps["amdgpu"]:
                return temps["amdgpu"][0].current
        except Exception:
            pass
    if _INTEL_DEV:
        if _INTEL_HWMON:
            try:
                with open(os.path.join(_INTEL_HWMON, "temp1_input")) as f:
                    return float(f.read().strip()) / 1000.0
            except Exception:
                pass
        try:
            temps = psutil.sensors_temperatures()
            for key in ["i915", "xe", "intel_gpu"]:
                if key in temps and temps[key]:
                    return temps[key][0].current
        except Exception:
            pass
    return 0.0

def s_gpu_power() -> float:
    """Returns GPU power draw in watts, or 0.0 if unavailable."""
    if GPU_HANDLE:
        try:
            return pynvml.nvmlDeviceGetPowerUsage(GPU_HANDLE) / 1000.0
        except Exception:
            return 0.0
    if _AMD_HWMON:
        for name in ("power1_average", "power1_input"):
            try:
                with open(os.path.join(_AMD_HWMON, name)) as f:
                    return float(f.read().strip()) / 1_000_000.0
            except Exception:
                pass
    return 0.0


def s_gpu_vram():
    if GPU_HANDLE:
        try:
            m = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
            pct = m.used / m.total * 100 if m.total else 0
            return m.used >> 20, m.total >> 20, pct
        except Exception:
            return 0, 0, 0
    if _AMD_DEV:
        try:
            with open(os.path.join(_AMD_DEV, "mem_info_vram_used")) as f:
                used = int(f.read().strip())
            with open(os.path.join(_AMD_DEV, "mem_info_vram_total")) as f:
                total = int(f.read().strip())
            pct = used / total * 100 if total else 0
            return used >> 20, total >> 20, pct
        except Exception:
            pass
    if _INTEL_DEV:
        for uf, tf in (("mem_info_vram_used", "mem_info_vram_total"),
                       ("mem_info_gtt_used",  "mem_info_gtt_total")):
            up = os.path.join(_INTEL_DEV, uf)
            tp = os.path.join(_INTEL_DEV, tf)
            if os.path.exists(up) and os.path.exists(tp):
                try:
                    used  = int(open(up).read().strip())
                    total = int(open(tp).read().strip())
                    pct   = used / total * 100 if total else 0
                    return used >> 20, total >> 20, pct
                except Exception:
                    pass
    return 0, 0, 0

def s_ram():
    v = psutil.virtual_memory()
    return v.used / 1e9, v.total / 1e9, v.percent

def s_cpu_freq() -> float:
    f = psutil.cpu_freq()
    return f.current / 1000.0 if f else 0.0

def s_disk():
    path = "C:\\" if IS_WINDOWS else "/"
    d = psutil.disk_usage(path)
    return d.used / 1e9, d.total / 1e9, d.percent


def s_disk_all() -> list[tuple[str, float, float, float]]:
    """Returns [(mount_point, used_GB, total_GB, pct), ...] for physical drives."""
    results = []
    seen_devices: set[str] = set()
    try:
        partitions = psutil.disk_partitions(all=False)
        for p in partitions:
            if IS_WINDOWS:
                pass  # all=False filters virtual on Windows
            else:
                # Skip pseudo filesystems
                if p.fstype in ("", "squashfs", "tmpfs", "devtmpfs", "proc",
                                "sysfs", "cgroup", "cgroup2", "overlay",
                                "devpts", "mqueue", "hugetlbfs"):
                    continue
            dev = p.device
            if dev in seen_devices:
                continue
            seen_devices.add(dev)
            try:
                u = psutil.disk_usage(p.mountpoint)
                results.append((p.mountpoint, u.used / 1e9, u.total / 1e9, u.percent))
            except (PermissionError, OSError):
                pass
    except Exception:
        pass
    # Fallback: always include root if empty
    if not results:
        try:
            path = "C:\\" if IS_WINDOWS else "/"
            d = psutil.disk_usage(path)
            results.append((path, d.used / 1e9, d.total / 1e9, d.percent))
        except Exception:
            pass
    return results


def s_nvme_temps() -> list[tuple[str, float]]:
    """Returns [(device_name, temp_C), ...] for NVMe/SSD drives from hwmon."""
    result = []
    if IS_WINDOWS:
        return result
    try:
        for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
            name_file = os.path.join(hwmon, "name")
            try:
                with open(name_file) as f:
                    name = f.read().strip()
            except OSError:
                continue
            if name.startswith("nvme") or name.startswith("drivetemp"):
                for temp_file in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
                    try:
                        with open(temp_file) as f:
                            temp_c = float(f.read().strip()) / 1000.0
                        label_file = temp_file.replace("_input", "_label")
                        try:
                            with open(label_file) as f:
                                lbl = f.read().strip()
                        except OSError:
                            lbl = name
                        result.append((lbl or name, temp_c))
                        break  # one temp per drive
                    except (OSError, ValueError):
                        pass
    except Exception:
        pass
    return result


_ram_info_cache: tuple[str, int] | None = None

def s_ram_info() -> tuple[str, int]:
    """Returns (type_str, speed_MHz). Cached after first call."""
    global _ram_info_cache
    if _ram_info_cache is not None:
        return _ram_info_cache
    ram_type = "RAM"
    ram_speed = 0
    try:
        if not IS_WINDOWS:
            r = subprocess.run(
                ["dmidecode", "-t", "17"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("Type:") and "Unknown" not in line and "Other" not in line:
                        t = line.split(":", 1)[1].strip()
                        if t:
                            ram_type = t
                    elif line.startswith("Speed:") and "MHz" in line:
                        try:
                            ram_speed = int(line.split(":")[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                    if ram_type != "RAM" and ram_speed:
                        break
        else:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            val, _ = winreg.QueryValueEx(key, "~MHz")
            ram_speed = int(val)
    except Exception:
        pass
    _ram_info_cache = (ram_type, ram_speed)
    return _ram_info_cache


# ── New sensors ───────────────────────────────────────────────────────────────
_net_prev: dict = {}

def s_network() -> tuple[float, float]:
    """Returns (upload_Mbps, download_Mbps). First call returns (0.0, 0.0)."""
    global _net_prev
    now = time.monotonic()
    try:
        c = psutil.net_io_counters()
    except Exception:
        return 0.0, 0.0
    if not _net_prev:
        _net_prev = {"t": now, "sent": c.bytes_sent, "recv": c.bytes_recv}
        return 0.0, 0.0
    dt = now - _net_prev["t"]
    if dt <= 0:
        return 0.0, 0.0
    up   = max(0.0, (c.bytes_sent - _net_prev["sent"]) / dt * 8 / 1e6)
    down = max(0.0, (c.bytes_recv - _net_prev["recv"]) / dt * 8 / 1e6)
    _net_prev = {"t": now, "sent": c.bytes_sent, "recv": c.bytes_recv}
    return up, down

def s_battery() -> "tuple[float, bool] | None":
    """Returns (percent, is_charging) or None if no battery."""
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return float(b.percent), bool(b.power_plugged)
    except Exception:
        return None

def s_fans() -> "list[tuple[str, int]]":
    """Returns [(name, rpm), ...] sorted by name."""
    result: list[tuple[str, int]] = []
    try:
        fans = psutil.sensors_fans()
        if fans:
            for name, entries in fans.items():
                for e in entries:
                    label = e.label.strip() if e.label.strip() else name
                    result.append((label, int(e.current)))
            return result
    except Exception:
        pass
    if sys.platform == "linux":
        for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            try:
                with open(os.path.join(hwmon, "name")) as f:
                    name = f.read().strip()
            except Exception:
                name = os.path.basename(hwmon)
            for fan_input in sorted(glob.glob(os.path.join(hwmon, "fan*_input"))):
                try:
                    rpm = int(open(fan_input).read().strip())
                    if rpm > 0:
                        idx = os.path.basename(fan_input).replace("fan", "").replace("_input", "")
                        result.append((f"{name}/{idx}", rpm))
                except Exception:
                    pass
    return result

def s_cpu_per_core() -> "list[float]":
    """Returns [usage_pct, ...] per logical core."""
    return psutil.cpu_percent(percpu=True)  # type: ignore[return-value]


# ── Arc Gauge ─────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    _DEG_START = 240
    _DEG_SPAN  = -300
    _HALOS = ((10, 8), (7, 20), (5, 38))

    def __init__(self, label, unit, lo=0, hi=100, color=None, warn=75, danger=90,
                 is_temp=False, invert_warn=False, is_usage=False):
        super().__init__()
        self._label   = label
        self._unit    = unit
        self._lo, self._hi = lo, hi
        self._col     = QColor(color or _THEME.cyan)
        self._warn    = warn
        self._danger  = danger
        self._is_temp = is_temp
        self._is_usage = is_usage
        self._invert_warn = invert_warn
        self._target  = 0.0
        self._cur     = 0.0
        self._compact = False
        self.setMinimumSize(190, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        t = QTimer(self); t.timeout.connect(self._tick); t.start(15)

    def set_value(self, v):
        self._target = max(self._lo, min(self._hi, v))

    def set_color(self, hex_color: str):
        self._col = QColor(hex_color)
        self.update()

    def set_compact(self, compact: bool):
        self._compact = compact
        self.setMinimumSize(120 if compact else 190, 130 if compact else 210)
        self.updateGeometry()

    def _tick(self):
        delta = self._target - self._cur
        if abs(delta) > 0.02:
            self._cur += delta * 0.13
            self.update()
        elif self._cur != self._target:
            self._cur = self._target
            self.update()

    def _active_col(self):
        pct = max(0.0, min(1.0, (self._cur - self._lo) / max(self._hi - self._lo, 1e-9)))
        if self._is_temp:
            r = 255
            g = int(255 * (1.0 - pct) ** 0.6)
            b = int(255 * (1.0 - pct) ** 1.5)
            return QColor(r, g, b)
        v = self._cur
        if self._invert_warn:
            if v <= self._danger: return QColor(_THEME.c_dang)
            if v <= self._warn:   return QColor(_THEME.c_warn)
        else:
            if v >= self._danger: return QColor(_THEME.c_dang)
            if v >= self._warn:   return QColor(_THEME.c_warn)
        if self._is_usage:
            # Interpolate from near-white (#c8e8f4) at 0% to cyan (#00ccdd) at warn threshold
            t = min(1.0, pct / max(self._warn / self._hi, 0.01))
            r = int(200 * (1.0 - t))
            g = int(232 * (1.0 - t) + 204 * t)
            b = int(244 * (1.0 - t) + 221 * t)
            return QColor(r, g, b)
        return QColor(self._col)

    def paintEvent(self, _e):
        W, H   = self.width(), self.height()
        margin = 14 if self._compact else 22
        side   = min(W, H) - margin * 2
        rx, ry = (W - side) / 2, (H - side) / 2 - 8
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        cx, cy = rx + r2, ry + r2

        a0    = self._DEG_START * 16
        a_end = self._DEG_SPAN  * 16
        pct   = max(0.0, min(1.0, (self._cur - self._lo) / max(self._hi - self._lo, 1e-9)))
        a_val = int(a_end * pct)
        col   = self._active_col()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)

        light = (_THEME.name == "light")

        # Outer bezel
        bezel_rect = rect.adjusted(-5, -5, 5, 5)
        bezel_grad = QRadialGradient(cx, cy, r2 + 5)
        if light:
            bezel_grad.setColorAt(0,   QColor("#a8d0f0"))
            bezel_grad.setColorAt(0.75, QColor("#6aa8d8"))
            bezel_grad.setColorAt(1.0, QColor("#4888c0"))
        else:
            bezel_grad.setColorAt(0,   QColor("#141624"))
            bezel_grad.setColorAt(0.8, QColor("#09090f"))
            bezel_grad.setColorAt(1.0, QColor("#040406"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bezel_grad))
        p.drawEllipse(bezel_rect)
        rim_r, rim_g, rim_b, rim_a = (80, 160, 220, 200) if light else (80, 90, 130, 110)
        p.setPen(QPen(QColor(rim_r, rim_g, rim_b, rim_a), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(bezel_rect)
        trim = QColor(col); trim.setAlpha(35)
        p.setPen(QPen(trim, 1.0))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))

        # Gauge face — light: icy blue; dark: near-black
        face_grad = QRadialGradient(cx, cy - r2 * 0.15, r2)
        if light:
            face_grad.setColorAt(0,    QColor("#d8f0ff"))
            face_grad.setColorAt(0.55, QColor("#b0d8f8"))
            face_grad.setColorAt(1.0,  QColor("#80b8ee"))
        else:
            face_grad.setColorAt(0,    QColor("#0d1020"))
            face_grad.setColorAt(0.55, QColor("#080a13"))
            face_grad.setColorAt(1.0,  QColor("#030406"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(face_grad))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        hi = QRadialGradient(cx, cy - r2 * 0.55, r2 * 0.5)
        hi.setColorAt(0, QColor(255, 255, 255, 50 if light else 12))
        hi.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        vig = QRadialGradient(cx, cy, r2 * 0.72)
        vig.setColorAt(0,   QColor(0, 0, 0, 0))
        vig.setColorAt(0.6, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 30 if light else 70))
        p.setBrush(QBrush(vig))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        if pct > 0.02:
            atm = QRadialGradient(cx, cy, r2 * 0.96)
            ac0 = QColor(col); ac0.setAlpha(0)
            ac1 = QColor(col); ac1.setAlpha(int(pct * 60))
            atm.setColorAt(0.0,  ac0); atm.setColorAt(0.55, ac0)
            atm.setColorAt(0.82, ac1); atm.setColorAt(1.0,  ac0)
            p.setBrush(QBrush(atm)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Arc track
        inset    = 12
        trk_w    = 6
        arc_rect = rect.adjusted(inset, inset, -inset, -inset)
        arc_r2   = r2 - inset
        trk_dark = "#7ab8e0" if light else "#0d1020"
        trk = QPen(QColor(trk_dark), trk_w); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(arc_rect, a0, a_end)
        if pct < 0.99:
            hint_c = QColor(col); hint_c.setAlpha(35 if light else 22)
            hp = QPen(hint_c, trk_w - 2); hp.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(hp); p.drawArc(arc_rect, a0 + a_val, a_end - a_val)

        # Tick marks
        if not self._compact:
            t_outer = r2 - 2.5
            for i in range(21):
                t_val   = i / 20.0
                is_maj  = (i % 5 == 0)
                ang_rad = math.radians(self._DEG_START + self._DEG_SPAN * t_val)
                ca, sa  = math.cos(ang_rad), math.sin(ang_rad)
                t_len   = 6.5 if is_maj else 3.5
                t_inner = t_outer - t_len
                inactive = "#7880a0" if light else "#404560"
                if is_maj:
                    tc = QColor(col) if t_val <= pct + 0.03 else QColor(inactive)
                    tc.setAlpha(210 if light else 190); pw = 1.5
                else:
                    tc = QColor(inactive); tc.setAlpha(100 if light else 80); pw = 1.0
                p.setPen(QPen(tc, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx + t_outer * ca, cy - t_outer * sa),
                           QPointF(cx + t_inner * ca, cy - t_inner * sa))

        # Colored fill arc + glow
        if pct > 5e-3:
            for pw, al in self._HALOS:
                c = QColor(col); c.setAlpha(al)
                pk = QPen(c, pw); pk.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pk); p.drawArc(arc_rect, a0, a_val)
            pk = QPen(col, trk_w); pk.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pk); p.drawArc(arc_rect, a0, a_val)
            spec = QPen(QColor(255, 255, 255, 55), max(1.0, trk_w * 0.28))
            spec.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(spec); p.drawArc(arc_rect, a0, a_val)

            tip_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
            tip_x   = cx + arc_r2 * math.cos(tip_ang)
            tip_y   = cy - arc_r2 * math.sin(tip_ang)
            for dr, da in ((8, 18), (5, 60), (2.5, 240)):
                c = QColor(col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(tip_x, tip_y), dr, dr)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # Needle
        n_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
        n_r   = arc_r2 - trk_w / 2 - 1
        n_tx  = cx + n_r * math.cos(n_ang)
        n_ty  = cy - n_r * math.sin(n_ang)
        for dr, da in ((7, 30), (4.5, 80), (2.5, 200)):
            c = QColor(col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(cx, cy), dr, dr)
        p.setPen(QPen(QColor(col), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(n_tx, n_ty))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Value text — dark on light face, light on dark face
        gauge_txt = "#1a2040" if light else _GAUGE_TXT
        val_str = f"{self._cur:.0f}{self._unit}"
        fs = max(8 if self._compact else 10,
                 int(side * 0.22 * (4 / max(len(val_str), 4))))
        p.setFont(_font(fs, bold=True)); p.setPen(QColor(gauge_txt))
        p.drawText(QRectF(0, cy, W, side * 0.28), Qt.AlignmentFlag.AlignCenter, val_str)
        p.setFont(_font(max(7 if self._compact else 8, int(side * 0.085))))
        p.setPen(QColor(gauge_txt))
        p.drawText(QRectF(0, cy + side * 0.28, W, side * 0.14),
                   Qt.AlignmentFlag.AlignCenter, self._label)

        # Hub cap
        hub_col = "#90c8f0" if light else "#0d1020"
        p.setBrush(QBrush(QColor(hub_col)))
        p.setPen(QPen(QColor(col), 0.8))
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.end()


# ── Mini Arc Gauge (for per-core row) ─────────────────────────────────────────
class MiniArcGauge(QWidget):
    _DEG_START = 240
    _DEG_SPAN  = -300

    def __init__(self, label: str):
        super().__init__()
        self._label  = label
        self._target = 0.0
        self._cur    = 0.0
        self.setFixedSize(80, 90)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        t = QTimer(self); t.timeout.connect(self._tick); t.start(30)

    def set_value(self, v: float):
        self._target = max(0.0, min(100.0, v))

    def _tick(self):
        delta = self._target - self._cur
        if abs(delta) > 0.1:
            self._cur += delta * 0.15
            self.update()
        elif self._cur != self._target:
            self._cur = self._target; self.update()

    def paintEvent(self, _e):
        W, H   = self.width(), self.height()
        margin = 6
        side   = min(W, H - 16) - margin * 2
        rx     = (W - side) / 2
        ry     = margin
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        cx, cy = rx + r2, ry + r2
        pct    = self._cur / 100.0
        a0     = self._DEG_START * 16
        a_end  = self._DEG_SPAN  * 16
        a_val  = int(a_end * pct)

        # Choose color based on value
        if pct >= 0.9:    col = QColor(_THEME.c_dang)
        elif pct >= 0.75: col = QColor(_THEME.c_warn)
        else:             col = QColor(_THEME.cyan)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Face
        face = QRadialGradient(cx, cy, r2)
        face.setColorAt(0, QColor("#0d1020")); face.setColorAt(1, QColor("#030406"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(face))
        p.drawEllipse(rect)

        # Track
        inset    = 7
        arc_rect = rect.adjusted(inset, inset, -inset, -inset)
        trk = QPen(QColor("#0d1020"), 4); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(arc_rect, a0, a_end)

        # Fill
        if pct > 0.01:
            fill = QPen(col, 4); fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(fill); p.drawArc(arc_rect, a0, a_val)

        # Value text — gauge face is always dark so always use bright text
        p.setFont(_font(10, bold=True)); p.setPen(QColor(_GAUGE_TXT))
        p.drawText(QRectF(0, cy - 2, W, side * 0.4),
                   Qt.AlignmentFlag.AlignCenter, f"{self._cur:.0f}%")

        # Label
        p.setFont(_font(8)); p.setPen(QColor(_THEME.txt_mid))
        p.drawText(QRectF(0, ry + side + 2, W, 14),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


# ── Sparkline ─────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    def __init__(self, color=None, max_pts=90, unit="", warn=75, danger=90, colour_coded=True):
        super().__init__()
        self._base_col   = QColor(color or _THEME.cyan)
        self._col        = QColor(self._base_col)
        self._hist: deque = deque(maxlen=max_pts)
        self._unit       = unit
        self._hover_x    = -1.0
        self._warn       = warn
        self._danger     = danger
        self._colour_coded = colour_coded
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def _current_color(self) -> QColor:
        if not self._colour_coded or not self._hist:
            return self._base_col
        v = self._hist[-1]
        if v >= self._danger:
            return QColor(C_DANG)
        if v >= self._warn:
            return QColor(C_WARN)
        return self._base_col

    def push(self, v):
        self._hist.append(v)
        self._col = self._current_color()
        self.update()

    def mouseMoveEvent(self, e):
        if len(self._hist) < 2: return
        self._hover_x = e.position().x(); self.update()

    def leaveEvent(self, e):
        self._hover_x = -1.0; self.update(); super().leaveEvent(e)

    def paintEvent(self, _e):
        if len(self._hist) < 2: return
        W, H = self.width(), self.height()
        px, py = 3, 6
        vals = list(self._hist)
        hi   = max(max(vals), 1.0)
        n    = len(vals)
        fx   = lambda i: px + i / (n - 1) * (W - 2 * px)
        fy   = lambda v: H - py - v / hi * (H - 2 * py)
        pts  = [QPointF(fx(i), fy(v)) for i, v in enumerate(vals)]

        line = QPainterPath(); line.moveTo(pts[0])
        for i in range(1, n):
            mid = (pts[i-1].x() + pts[i].x()) / 2
            line.cubicTo(QPointF(mid, pts[i-1].y()), QPointF(mid, pts[i].y()), pts[i])

        area = QPainterPath(line)
        area.lineTo(QPointF(pts[-1].x(), H)); area.lineTo(QPointF(pts[0].x(), H))
        area.closeSubpath()

        grad = QLinearGradient(0, 0, 0, H)
        top  = QColor(self._col); top.setAlpha(55)
        bot  = QColor(self._col); bot.setAlpha(0)
        grad.setColorAt(0, top); grad.setColorAt(1, bot)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(area, QBrush(grad))
        p.setPen(QPen(self._col, 1.7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)
        tip = pts[-1]
        for dr, da in ((7, 18), (4.5, 60), (2.5, 240)):
            c = QColor(self._col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(tip, dr, dr)

        if self._hover_x >= 0:
            mx = max(pts[0].x(), min(pts[-1].x(), self._hover_x))
            hp, hval = pts[-1], vals[-1]
            for i in range(len(pts) - 1):
                x0, x1 = pts[i].x(), pts[i + 1].x()
                if x0 <= mx <= x1:
                    t    = (mx - x0) / (x1 - x0) if x1 > x0 else 0.0
                    hy   = pts[i].y()  + t * (pts[i + 1].y()  - pts[i].y())
                    hval = vals[i]     + t * (vals[i + 1]      - vals[i])
                    hp   = QPointF(mx, hy)
                    break
            vc = QColor(self._col); vc.setAlpha(40)
            p.setPen(QPen(vc, 1, Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(hp.x(), py), QPointF(hp.x(), H))
            for dr, da in ((6, 25), (3.5, 80), (2, 220)):
                c = QColor(self._col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(hp, dr, dr)

            label = f"{hval:.1f}{self._unit}"
            p.setFont(_font(10, bold=True))
            fm  = p.fontMetrics()
            pad = 4
            bw  = fm.horizontalAdvance(label) + pad * 2
            bh  = fm.height() + pad * 2
            off = 10
            bx  = hp.x() + off if hp.x() + off + bw < W else max(0.0, hp.x() - bw - off)
            by  = max(2.0, min(hp.y() - bh - 6, float(H - bh - 2)))
            bg  = QColor(_THEME.card_bg); bg.setAlpha(210)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bg))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            bc = QColor(self._col); bc.setAlpha(160)
            p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            p.setPen(QColor(_THEME.txt_hi))
            p.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        p.end()


# ── Compact Bar ───────────────────────────────────────────────────────────────
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
        self._val_lbs:  list[QLabel] = []   # for non-temp sections
        self._seps:     list[QFrame] = []
        # Separate pct / temp labels for CPU and GPU
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
        self._clk_lbl = QLabel("–")
        self._clk_lbl.setFont(_font(12, bold=True))
        self._clk_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._clk_lbl, 1)

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
        self._clk_lbl.setText(now.strftime(f"{hour}:%M:%S %p   %a %d %b %Y"))
        self._clk_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")

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
                # Single click — start drag (compositor-native)
                h = self.window().windowHandle()
                if h: h.startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._last_press_ms = 0.0   # reset so next single-click drags normally
            self.window().toggle_dock()
        super().mouseDoubleClickEvent(e)

    def _apply_theme_styles(self):
        for lb in self._name_lbs:
            lb.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
        for lb in self._val_lbs:
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        for sep in self._seps:
            sep.setStyleSheet(f"background: {_THEME.card_bd};")
        self._clk_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
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


# ── Monitor Card ──────────────────────────────────────────────────────────────
class MonitorCard(QFrame):
    _R = 18.0

    def __init__(self, label, unit, lo=0, hi=100, color=None,
                 warn=75, danger=90, is_temp=False, invert_warn=False, is_usage=False,
                 resource_key=""):
        super().__init__()
        col = color or _THEME.cyan
        self._accent = QColor(col)
        self._warn   = warn
        self._danger = danger
        self._resource_key = resource_key  # e.g. "cpu_usage", "gpu_temp"
        self.gauge   = ArcGauge(label, unit, lo, hi, col, warn, danger,
                                is_temp=is_temp, invert_warn=invert_warn, is_usage=is_usage)
        self.spark   = Sparkline(CYAN, unit=unit, warn=warn, danger=danger,
                                 colour_coded=True)  # sparklines always cyan, colour-coded

        self._sep = QFrame(); self._sep.setFixedHeight(1)
        self._sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none; border-radius: 0;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 10); lay.setSpacing(8)
        lay.addWidget(self.gauge, 1)
        lay.addWidget(self._sep)
        lay.addWidget(self.spark)

        self.setMinimumHeight(300)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(28); self._shadow.setOffset(0, 5)
        self._apply_shadow()
        self.setGraphicsEffect(self._shadow)

        # Stats tracking
        self._stat_min   = float("inf")
        self._stat_max   = float("-inf")
        self._stat_sum   = 0.0
        self._stat_count = 0

    def push(self, v):
        self.gauge.set_value(v)
        self.spark.push(v)
        # Update running stats
        if v < self._stat_min: self._stat_min = v
        if v > self._stat_max: self._stat_max = v
        self._stat_sum   += v
        self._stat_count += 1

    def set_color(self, hex_color: str):
        self._accent = QColor(hex_color)
        self.gauge.set_color(hex_color)

    def reset_stats(self):
        self._stat_min   = float("inf")
        self._stat_max   = float("-inf")
        self._stat_sum   = 0.0
        self._stat_count = 0

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        unit = self.gauge._unit

        # Stats section
        if self._stat_count > 0:
            avg = self._stat_sum / self._stat_count
            menu.addAction(
                f"Min: {self._stat_min:.1f}{unit}  |  "
                f"Avg: {avg:.1f}{unit}  |  "
                f"Max: {self._stat_max:.1f}{unit}"
            ).setEnabled(False)
        else:
            menu.addAction("No data yet").setEnabled(False)

        menu.addSeparator()
        reset_act = menu.addAction("Reset min/avg/max")

        # Top processes (CPU/RAM only)
        top_act = None
        key = self._resource_key
        if key in ("cpu_usage", "cpu_temp"):
            top_act = menu.addAction("Top CPU processes…")
        elif key in ("gpu_usage", "gpu_temp"):
            top_act = menu.addAction("Top GPU processes (nvidia-smi)…")

        chosen = menu.exec(event.globalPos())
        if chosen == reset_act:
            self.reset_stats()
        elif top_act and chosen == top_act:
            self._show_top_processes(key)

    def _show_top_processes(self, key: str):
        lines = []
        try:
            if key in ("cpu_usage", "cpu_temp"):
                procs = sorted(
                    psutil.process_iter(["pid", "name", "cpu_percent"]),
                    key=lambda p: p.info.get("cpu_percent") or 0, reverse=True,
                )[:8]
                lines.append("Top CPU processes:")
                for pr in procs:
                    pct = pr.info.get("cpu_percent") or 0
                    nm  = (pr.info.get("name") or "?")[:22]
                    lines.append(f"  {nm:<22}  {pct:5.1f}%")
            elif key in ("gpu_usage", "gpu_temp"):
                r = subprocess.run(
                    ["nvidia-smi",
                     "--query-compute-apps=pid,process_name,used_memory",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3,
                )
                if r.returncode == 0:
                    lines.append("GPU processes (nvidia-smi):")
                    for row in r.stdout.strip().splitlines():
                        parts = [x.strip() for x in row.split(",")]
                        if len(parts) >= 3:
                            lines.append(f"  PID {parts[0]}  {parts[1][:20]}  {parts[2]} MiB")
                else:
                    lines.append("nvidia-smi not available.")
        except Exception as ex:
            lines.append(f"Error: {ex}")
        msg = QMessageBox(self)
        msg.setWindowTitle("Process Details")
        msg.setText("\n".join(lines) if lines else "No data.")
        msg.exec()

    def set_compact(self, compact: bool):
        self.gauge.set_compact(compact)
        self.spark.setVisible(not compact)
        self._sep.setVisible(not compact)
        self.setMinimumHeight(155 if compact else 300)
        self.updateGeometry()

    def _apply_shadow(self):
        alpha = 60 if _THEME.name == "light" else 160
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def _apply_theme_styles(self):
        self._sep.setStyleSheet(
            f"background: {_THEME.card_bd}; border: none; border-radius: 0;")
        self._apply_shadow()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1); R = self._R

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_THEME.card_bg)))
        p.drawRoundedRect(r, R, R)

        top_grad = QLinearGradient(0, r.y(), 0, r.y() + 90)
        if _THEME.name == "light":
            top_grad.setColorAt(0, QColor(200, 215, 245, 60))
        else:
            top_grad.setColorAt(0, QColor("#181c2e"))   # original dark blue-grey tint
        top_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(top_grad)); p.drawRoundedRect(r, R, R)

        bot_grad = QLinearGradient(0, r.bottom() - 50, 0, r.bottom())
        bot_grad.setColorAt(0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1, QColor(0, 0, 0, 15 if _THEME.name == "light" else 50))
        p.setBrush(QBrush(bot_grad)); p.drawRoundedRect(r, R, R)

        sheen = QLinearGradient(0, r.y(), 0, r.y() + 28)
        sheen.setColorAt(0, QColor(255, 255, 255, 60 if _THEME.name == "light" else 16))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen)); p.drawRoundedRect(r, R, R)

        border_grad = QLinearGradient(0, r.y(), 0, r.bottom())
        if _THEME.name == "light":
            border_grad.setColorAt(0, QColor(_THEME.card_bd).lighter(110))
            border_grad.setColorAt(1, QColor(_THEME.card_bd))
        else:
            border_grad.setColorAt(0, QColor("#2e3248"))   # original medium blue border
            border_grad.setColorAt(1, QColor("#181b28"))
        p.setPen(QPen(QBrush(border_grad), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, R, R)
        p.end()


# ── Fan Row ───────────────────────────────────────────────────────────────────
class FanRow(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(36)
        self.setStyleSheet("background: transparent;")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 0, 4, 0)
        self._lay.setSpacing(24)
        self._labels: dict[str, QLabel] = {}
        self._no_fan = QLabel("No fans detected")
        self._no_fan.setFont(_font(11))
        self._no_fan.setStyleSheet(f"color: {_THEME.txt_lo}; background: transparent;")
        self._lay.addWidget(self._no_fan)
        self._lay.addStretch()

    def update_fans(self, fans: "list[tuple[str, int]]"):
        if not fans:
            self._no_fan.setVisible(True)
            for lb in self._labels.values(): lb.setVisible(False)
            return
        self._no_fan.setVisible(False)
        existing = set(self._labels.keys())
        new_keys = {name for name, _ in fans}
        for key in existing - new_keys:
            self._labels[key].deleteLater(); del self._labels[key]
        for name, rpm in fans:
            if name not in self._labels:
                lb = QLabel()
                lb.setFont(_font(11))
                lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
                self._labels[name] = lb
                self._lay.insertWidget(self._lay.count() - 1, lb)
            self._labels[name].setText(f"⊛ {name}  {rpm:,} RPM")
            self._labels[name].setVisible(True)

    def _apply_theme_styles(self):
        self._no_fan.setStyleSheet(f"color: {_THEME.txt_lo}; background: transparent;")
        for lb in self._labels.values():
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")


# ── Per-core Row ──────────────────────────────────────────────────────────────
class PerCoreRow(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(6)
        self._gauges: list[MiniArcGauge] = []
        self._core_count = 0

    def _ensure_gauges(self, count: int):
        if count == self._core_count:
            return
        for g in self._gauges:
            g.deleteLater()
        self._gauges.clear()
        cols = min(count, 8)
        for i in range(count):
            g = MiniArcGauge(f"C{i}")
            self._gauges.append(g)
            self._grid.addWidget(g, i // cols, i % cols)
        self._core_count = count
        h = 90 * math.ceil(count / max(cols, 1)) + 10
        self.setFixedHeight(int(h))

    def update_values(self, values: "list[float]"):
        self._ensure_gauges(len(values))
        for g, v in zip(self._gauges, values):
            g.set_value(v)


# ── Network Panel ─────────────────────────────────────────────────────────────
class NetworkPanel(QFrame):
    """Compact upload/download panel — two rows with value + sparkline."""
    _R = 14.0

    def __init__(self):
        super().__init__()
        self.setFixedHeight(96)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(18); self._shadow.setOffset(0, 4)
        self._apply_shadow()
        self.setGraphicsEffect(self._shadow)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 8); outer.setSpacing(0)

        self._rows: list[tuple[QLabel, QLabel, QLabel, Sparkline]] = []
        for arrow, label_text in [("↑", "UPLOAD"), ("↓", "DOWNLOAD")]:
            row = QHBoxLayout(); row.setSpacing(10)

            arr_lbl = QLabel(arrow)
            arr_lbl.setFont(_font(18, bold=True))
            arr_lbl.setFixedWidth(20)
            arr_lbl.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")

            name_lbl = QLabel(label_text)
            name_lbl.setFont(_font(10))
            name_lbl.setFixedWidth(62)
            name_lbl.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")

            spark = Sparkline(CYAN, max_pts=90, unit=" Mb/s")
            spark.setFixedHeight(38)

            val_lbl = QLabel("0 Mb/s")
            val_lbl.setFont(_font(13, bold=True))
            val_lbl.setFixedWidth(90)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")

            row.addWidget(arr_lbl)
            row.addWidget(name_lbl)
            row.addWidget(spark, 1)
            row.addWidget(val_lbl)
            self._rows.append((arr_lbl, name_lbl, val_lbl, spark))

            wrap = QWidget(); wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            wrap.setLayout(row)

            if not self._rows or len(self._rows) == 1:
                outer.addWidget(wrap, 1)
            else:
                sep = QFrame(); sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
                self._sep = sep
                outer.addWidget(sep)
                outer.addWidget(wrap, 1)

    def update_network(self, up: float, down: float):
        for (arr, name, val, spark), value in zip(self._rows, (up, down)):
            val.setText(f"{value:.1f} Mb/s")
            spark.push(value)

    def _apply_shadow(self):
        alpha = 50 if _THEME.name == "light" else 140
        self._shadow.setColor(QColor(0, 0, 0, alpha))

    def _apply_theme_styles(self):
        for arr, name, val, spark in self._rows:
            arr.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
            name.setStyleSheet(f"color: {_THEME.txt_mid}; background: transparent;")
            val.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        if hasattr(self, "_sep"):
            self._sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
        self._apply_shadow()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(_THEME.card_bg)))
        p.drawRoundedRect(r, self._R, self._R)
        # Subtle top sheen
        sheen = QLinearGradient(0, r.y(), 0, r.y() + 24)
        sheen.setColorAt(0, QColor(255, 255, 255, 14)); sheen.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(QBrush(sheen)); p.drawRoundedRect(r, self._R, self._R)
        p.setPen(QPen(QBrush(QLinearGradient(0, r.y(), 0, r.bottom())), 1.5))
        border = QLinearGradient(0, r.y(), 0, r.bottom())
        border.setColorAt(0, QColor(_THEME.card_bd).lighter(110))
        border.setColorAt(1, QColor(_THEME.card_bd))
        p.setPen(QPen(QBrush(border), 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R)
        p.end()


# ── Status Bar ────────────────────────────────────────────────────────────────
class StatusBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0); lay.setSpacing(0)
        self._lbs: dict[str, QLabel] = {}
        for i, key in enumerate(("RAM", "Swap", "VRAM", "CPU Freq", "Threads", "Disk", "GPU Power", "NVMe")):
            if i > 0:
                lay.addStretch(1)
            lb = QLabel(f"{key}: –")
            lb.setFont(_font(11))
            lb.setMinimumWidth(0)
            lb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
            self._lbs[key] = lb; lay.addWidget(lb)

        # CPU / GPU hardware names — right-aligned, vendor colored
        lay.addStretch(2)
        cpu_col = _cpu_vendor_color()
        gpu_col = GPU_COLOR
        self._hw_cpu = QLabel(_get_cpu_name())
        self._hw_gpu = QLabel(GPU_NAME)
        for lb, col in ((self._hw_cpu, cpu_col), (self._hw_gpu, gpu_col)):
            lb.setFont(_font(10))
            lb.setMinimumWidth(0)
            lb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lb.setStyleSheet(f"color: {col}; background: transparent;")
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1); sep.setFixedHeight(16)
        sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")
        self._hw_sep = sep
        lay.addWidget(self._hw_cpu); lay.addSpacing(8)
        lay.addWidget(sep);          lay.addSpacing(8)
        lay.addWidget(self._hw_gpu)

    def _apply_theme_styles(self):
        for lb in self._lbs.values():
            lb.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._hw_cpu.setStyleSheet(f"color: {_cpu_vendor_color()}; background: transparent;")
        self._hw_gpu.setStyleSheet(f"color: {GPU_COLOR}; background: transparent;")
        self._hw_sep.setStyleSheet(f"background: {_THEME.card_bd}; border: none;")

    def refresh(self):
        used_r, tot_r, pct_r = s_ram()
        ram_type, ram_speed = s_ram_info()
        ram_info = f"  {ram_type} {ram_speed}MHz" if ram_speed else (f"  {ram_type}" if ram_type != "RAM" else "")
        self._lbs["RAM"].setText(f"RAM  {used_r:.1f} / {tot_r:.0f} GB  ({pct_r:.0f}%){ram_info}")
        sw = psutil.swap_memory()
        self._lbs["Swap"].setText(f"Swap  {sw.used/1e9:.1f} / {sw.total/1e9:.1f} GB" if sw.total else "Swap  N/A")
        used_v, tot_v, pct_v = s_gpu_vram()
        self._lbs["VRAM"].setText(
            f"VRAM  {used_v:,} / {tot_v:,} MB  ({pct_v:.0f}%)" if tot_v else "VRAM  N/A")
        self._lbs["CPU Freq"].setText(f"CPU Freq  {s_cpu_freq():.2f} GHz")
        self._lbs["Threads"].setText(f"Threads  {psutil.cpu_count(logical=True)}")

        # Multi-disk: show up to 3 mounts compactly
        disks = s_disk_all()
        if disks:
            parts = []
            for mount, used, total, pct in disks[:3]:
                base = os.path.basename(mount.rstrip("/")) or mount
                short = base if len(base) <= 10 else base[:10]
                parts.append(f"{short} {used:.0f}/{total:.0f}GB")
            self._lbs["Disk"].setText("Disk  " + "  ".join(parts))
        else:
            self._lbs["Disk"].setText("Disk  N/A")

        pwr = s_gpu_power()
        self._lbs["GPU Power"].setText(f"GPU  {pwr:.0f} W" if pwr > 0 else "GPU Power  N/A")

        # NVMe temperatures
        nvme = s_nvme_temps()
        if nvme:
            parts = [f"{name} {temp:.0f}°C" for name, temp in nvme[:2]]
            self._lbs["NVMe"].setText("NVMe  " + "  ".join(parts))
        else:
            self._lbs["NVMe"].setText("NVMe  N/A")


# ── Window control button ─────────────────────────────────────────────────────
class _WinBtn(QWidget):
    def __init__(self, symbol, color, callback):
        super().__init__()
        self._symbol = symbol; self._color = QColor(color)
        self._dim = QColor(color).darker(140); self._cb = callback
        self._hovered = False; self.setFixedSize(16, 16)
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
        p.drawEllipse(0, 0, 16, 16)
        if self._hovered:
            p.setFont(_font(9, bold=True)); p.setPen(QColor(0, 0, 0, 210))
            p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, self._symbol)
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


# ── Vendor keywords ───────────────────────────────────────────────────────────
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


def _make_clock_pixmap(size: int = 14) -> QPixmap:
    px = QPixmap(size, size); px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(_THEME.txt_hi)
    cx = cy = size / 2.0; r = cx - 1.0
    p.setPen(QPen(col, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)
    cap = Qt.PenCapStyle.RoundCap
    p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, cap))
    p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.35, cy - r * 0.35))  # hour
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.65))              # minute
    p.end(); return px


def _make_calendar_pixmap(size: int = 14) -> QPixmap:
    px = QPixmap(size, size); px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(_THEME.txt_hi)
    p.setPen(QPen(col, 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(1, 2, size - 2, size - 3), 1.5, 1.5)
    p.drawLine(QPoint(1, 5), QPoint(size - 1, 5))
    # binding nubs at top
    p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPoint(4, 1), QPoint(4, 4))
    p.drawLine(QPoint(size - 4, 1), QPoint(size - 4, 4))
    # 3×2 dot grid in body
    for row in range(2):
        for col_i in range(3):
            xp = 4 + col_i * ((size - 6) // 2)
            yp = 8 + row * 3
            p.drawPoint(QPointF(xp, yp))
    p.end(); return px


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
        self._title_label.setFont(_font(17, bold=True))
        self._title_label.setStyleSheet(
            f"color: {_THEME.cyan}; letter-spacing: 3px; background: transparent;")
        self._title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._ver_label = QLabel(VERSION)
        self._ver_label.setFont(_font(10))
        self._ver_label.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
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

        lay.addWidget(self._title_label); lay.addSpacing(6)
        lay.addWidget(self._ver_label)
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
        self._ver_label.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._time_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._date_lbl.setStyleSheet(f"color: {_THEME.txt_hi}; background: transparent;")
        self._clk_icon.setPixmap(_make_clock_pixmap(14))
        self._cal_icon.setPixmap(_make_calendar_pixmap(14))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            now = time.monotonic() * 1000
            dt, self._last_press_ms = now - self._last_press_ms, now
            if dt > QApplication.doubleClickInterval():
                if self._win._docked:
                    self._press_pos = e.position()
                else:
                    h = self._win.windowHandle()
                    if h: h.startSystemMove()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None
                and self._win._docked
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
            return   # CompactBar draws its own background; window is transparent
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(_THEME.bg)))
        p.drawRoundedRect(r, self._R, self._R)
        p.setPen(QPen(QColor(_THEME.card_bd), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R); p.end()


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
        close_btn = _WinBtn("✕", "#ff5f57", self.hide)
        hdr.addWidget(self._title_lbl); hdr.addStretch(); hdr.addWidget(close_btn)
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


# ── Settings Dialog ───────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HeatSync Settings")
        self.setModal(True)
        self.setMinimumWidth(440)
        icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._settings = dict(settings)

        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Appearance tab ─────────────────────────────────────────────────
        ap = QWidget(); al = QVBoxLayout(ap)

        tg = QGroupBox("Theme"); tl = QVBoxLayout(tg)
        self._theme_dark   = QRadioButton("Dark")
        self._theme_light  = QRadioButton("Light")
        self._theme_system = QRadioButton("Follow system")
        t = settings.get("theme", "dark")
        if t == "light":    self._theme_light.setChecked(True)
        elif t == "system": self._theme_system.setChecked(True)
        else:               self._theme_dark.setChecked(True)
        tl.addWidget(self._theme_dark)
        tl.addWidget(self._theme_light)
        tl.addWidget(self._theme_system)
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

        # ── Gauge colors ──────────────────────────────────────────────────
        _PALETTE = [
            ("#00ccdd", "Cyan"),
            ("#00e676", "Green"),
            ("#9d6fff", "Purple"),
            ("#2979ff", "Blue"),
            ("#ff6d00", "Orange"),
            ("#f9a825", "Gold"),
            ("#ff4081", "Pink"),
            ("#76b900", "NVIDIA Green"),
        ]
        _DEFAULTS = {
            "cpu_usage": CYAN,  "cpu_temp": CPU_COLOR,
            "gpu_usage": CYAN,  "gpu_temp": GPU_COLOR,
            "network":   CYAN,  "battery":  GREEN,
        }
        gc_cfg = settings.get("gauge_colors", {})
        self._gauge_color_picks: dict[str, str] = {}   # key → chosen hex
        self._swatch_btns: dict[str, list[QLabel]] = {}  # key → list of swatch labels

        col_grp = QGroupBox("Gauge Colours"); col_lay = QVBoxLayout(col_grp)
        col_lay.setSpacing(6)

        def _refresh_swatches(key: str, selected_hex: str):
            """Visually update border on all swatches for this key."""
            for bi, btn in enumerate(self._swatch_btns.get(key, [])):
                sel = (_PALETTE[bi][0].lower() == selected_hex.lower())
                bd = "2px solid white" if sel else "2px solid transparent"
                btn.setStyleSheet(
                    f"background:{_PALETTE[bi][0]}; border-radius:11px; border:{bd};")

        def _make_swatch_row(key: str, label: str):
            row = QHBoxLayout(); row.setSpacing(4)
            lbl = QLabel(f"{label}:"); lbl.setFixedWidth(110)
            lbl.setFont(_font(10))
            row.addWidget(lbl)
            cur = gc_cfg.get(key) or _DEFAULTS.get(key, CYAN)
            self._gauge_color_picks[key] = cur
            btns: list[QLabel] = []
            for pi, (hex_c, tip) in enumerate(_PALETTE):
                btn = QLabel()
                btn.setFixedSize(22, 22)
                btn.setToolTip(tip)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                selected = (hex_c.lower() == cur.lower())
                border = "2px solid white" if selected else "2px solid transparent"
                btn.setStyleSheet(
                    f"background:{hex_c}; border-radius:11px; border:{border};")
                def _make_click(k, h):
                    def handler(_e):
                        self._gauge_color_picks[k] = h
                        _refresh_swatches(k, h)
                    return handler
                btn.mousePressEvent = _make_click(key, hex_c)
                btns.append(btn)
                row.addWidget(btn)
            self._swatch_btns[key] = btns
            row.addStretch()
            col_lay.addLayout(row)

        for key, lbl in [("cpu_usage", "CPU Usage"),
                          ("cpu_temp",  "CPU Temp"),
                          ("gpu_usage", "GPU Usage"),
                          ("gpu_temp",  "GPU Temp"),
                          ("network",   "Network"),
                          ("battery",   "Battery")]:
            _make_swatch_row(key, lbl)

        reset_lbl = QLabel("<a href='reset'>Reset all to defaults</a>")
        reset_lbl.setOpenExternalLinks(False)
        reset_lbl.setFont(_font(10))
        reset_lbl.setStyleSheet(f"color: {_THEME.cyan}; background: transparent;")
        def _reset_colors():
            for k, h in _DEFAULTS.items():
                self._gauge_color_picks[k] = h
                _refresh_swatches(k, h)
        reset_lbl.linkActivated.connect(lambda _: _reset_colors())
        col_lay.addWidget(reset_lbl)
        gl.addWidget(col_grp)
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
        # Select closest
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
        self._profile_load_btn  = QComboBox()  # placeholder, actually a QLabel + btn
        load_btn  = QLabel("<a href='load'>Load selected</a>")
        save_btn  = QLabel("<a href='save'>Save as new…</a>")
        del_btn   = QLabel("<a href='del'>Delete selected</a>")
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
            # Patch current settings with profile overrides
            for k, v in prof.items():
                if k == "gauges" and isinstance(v, dict):
                    for gk, gv in v.items():
                        if gk in self._gauge_cbs:
                            self._gauge_cbs[gk].setChecked(gv)
                elif k == "theme":
                    if v == "light":   self._theme_light.setChecked(True)
                    elif v == "system": self._theme_system.setChecked(True)
                    else:               self._theme_dark.setChecked(True)
                elif k == "compact":
                    self._compact_cb.setChecked(bool(v))
                elif k == "opacity":
                    self._opacity_slider.setValue(int(v))
            self._settings["active_profile"] = name

        def _save_profile():
            name = self._profile_name_edit.text().strip()
            if not name:
                return
            snap = {
                "theme":   ("light" if self._theme_light.isChecked()
                            else "system" if self._theme_system.isChecked()
                            else "dark"),
                "compact": self._compact_cb.isChecked(),
                "opacity": self._opacity_slider.value(),
                "gauges":  {k: cb.isChecked() for k, cb in self._gauge_cbs.items()},
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

    def get_settings(self) -> dict:
        d = dict(self._settings)
        d["theme"]      = ("light" if self._theme_light.isChecked()
                           else "system" if self._theme_system.isChecked()
                           else "dark")
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

        # Gauge colors
        d["gauge_colors"] = dict(self._gauge_color_picks)

        # Profiles: carry through any changes made via the profile tab buttons
        d["profiles"]       = self._settings.get("profiles", {})
        d["active_profile"] = self._settings.get("active_profile", "")
        return d


# ── Autostart ─────────────────────────────────────────────────────────────────
def _set_autostart(enable: bool) -> None:
    try:
        if IS_WINDOWS:
            _autostart_windows(enable)
        elif sys.platform == "darwin":
            _autostart_macos(enable)
        else:
            _autostart_linux(enable)
    except Exception as e:
        print(f"[WARN] Autostart {'enable' if enable else 'disable'} failed: {e}")


def _autostart_linux(enable: bool) -> None:
    cfg_dir = os.path.expanduser("~/.config/autostart")
    path    = os.path.join(cfg_dir, "heatsync.desktop")
    if enable:
        os.makedirs(cfg_dir, exist_ok=True)
        exe = sys.executable if not getattr(sys, "frozen", False) else os.path.abspath(sys.executable)
        script = os.path.abspath(__file__)
        cmd = exe if getattr(sys, "frozen", False) else f"{exe} {script}"
        with open(path, "w") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName=HeatSync\n"
                    f"Exec={cmd}\nHidden=false\nNoDisplay=false\n"
                    f"X-GNOME-Autostart-enabled=true\n")
    else:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _autostart_windows(enable: bool) -> None:
    import winreg  # type: ignore
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
    try:
        if enable:
            exe = os.path.abspath(sys.executable)
            winreg.SetValueEx(key, "HeatSync", 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, "HeatSync")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _autostart_macos(enable: bool) -> None:
    agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_path = os.path.join(agents_dir, "com.heatsync.plist")
    if enable:
        os.makedirs(agents_dir, exist_ok=True)
        exe = os.path.abspath(sys.executable)
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.heatsync</string>\n'
            f'  <key>ProgramArguments</key><array><string>{exe}</string></array>\n'
            '  <key>RunAtLoad</key><true/>\n'
            '</dict></plist>\n'
        )
        with open(plist_path, "w") as f:
            f.write(plist)
        subprocess.run(["launchctl", "load", plist_path],
                       capture_output=True, timeout=5)
    else:
        try:
            subprocess.run(["launchctl", "unload", plist_path],
                           capture_output=True, timeout=5)
            os.unlink(plist_path)
        except FileNotFoundError:
            pass


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

        # Load settings (also seeds _THEME before any widget is created)
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

        # Compact mode text strip (shown instead of full UI)
        self._compact_bar = CompactBar(
            on_normal_mode=self._exit_compact_mode,
            on_settings=self._open_settings,
        )
        self._compact_bar.setVisible(False)
        root.addWidget(self._compact_bar)

        # Dynamic gauge row
        self._gauge_row_widget = QWidget()
        self._gauge_row_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._gauge_row = QHBoxLayout(self._gauge_row_widget)
        self._gauge_row.setSpacing(12)
        self._gauge_row.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._gauge_row_widget, 1)

        # Optional rows
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

        # Build initial gauge layout
        self._rebuild_gauge_row(self._settings)
        # Apply compact sizing if settings say compact (must be after rebuild)
        self._apply_compact_geometry(self._settings.get("compact", False))

        # Apply opacity from settings
        self._apply_opacity(self._settings.get("opacity", 100))

        # Refresh timer
        refresh_ms = self._settings.get("refresh_ms", 1000)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(refresh_ms)
        self._refresh()

        # Background version check (once per session)
        QTimer.singleShot(5000, self._check_version_bg)

        # DataLogger
        self._reconfigure_logger(self._settings)

        # System tray
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
        self._alert_ticks:   dict[str, int]   = {}  # consecutive danger ticks
        self._alert_notified: dict[str, float] = {}  # monotonic time of last notify

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
        global _THEME
        t = s.get("theme", "dark")
        if t == "light":
            _THEME = LIGHT_THEME
        elif t == "system":
            dark = QApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
            _THEME = DARK_THEME if dark else LIGHT_THEME
        else:
            _THEME = DARK_THEME
        if s.get("always_on_top", False):
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    def _on_system_color_scheme(self, scheme):
        """Called by Qt when the desktop color scheme changes."""
        if self._settings.get("theme", "dark") == "system":
            from PyQt6.QtCore import Qt as _Qt
            dark = (scheme == _Qt.ColorScheme.Dark)
            apply_theme(DARK_THEME if dark else LIGHT_THEME)

    def _apply_settings_live(self, s: dict):
        """Apply all settings after a SettingsDialog accept."""
        old_theme = self._settings.get("theme", "dark")
        old_export = self._settings.get("export", {})
        self._settings = s
        _save_settings(s)   # persist immediately — don't wait for window move/close

        # Theme
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

        # Refresh rate
        new_ms = s.get("refresh_ms", 1000)
        if new_ms != self._refresh_timer.interval():
            self._refresh_timer.setInterval(new_ms)

        # Rebuild gauge row then apply sizing
        self._rebuild_gauge_row(s)
        self._apply_compact_geometry(s.get("compact", False))

        # Monitor
        self._move_to_monitor(s.get("monitor", 0))

        # Autostart
        _set_autostart(s.get("autostart", False))

        # Data logger
        new_export = s.get("export", {})
        if new_export != old_export:
            self._reconfigure_logger(s)

        # History window rebuild if open
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
        """Copy a formatted snapshot of current metrics to the clipboard."""
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
            # RAM
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
        """30-second high-speed benchmark logging at 100ms, exports CSV."""
        if self._bench_timer and self._bench_timer.isActive():
            self._stop_benchmark()
            return
        # Create temp logger at 100ms
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
        """Silent background version check — only notifies if newer available."""
        if self._version_checked:
            return
        self._version_checked = True
        threading.Thread(target=self._do_version_check,
                         args=(False,), daemon=True).start()

    def _check_version_manual(self):
        """Manual version check triggered from tray menu."""
        threading.Thread(target=self._do_version_check,
                         args=(True,), daemon=True).start()

    def _do_version_check(self, manual: bool):
        """Runs in background thread."""
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
            h = 46 + 20   # compact bar + root margins (top 8 + bottom 12)
            self.setMinimumSize(600, h)
            if self.width() < 600 or self.height() != h:
                self.resize(max(self.width(), 700), h)
        else:
            self.setMinimumSize(880, 520)
            if self.height() < 520:
                self.resize(max(self.width(), 880), 540)

    def _rebuild_gauge_row(self, s: dict):
        # Detach all widgets (don't delete — reuse to preserve sparkline history)
        while self._gauge_row.count():
            item = self._gauge_row.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        compact = s.get("compact", False)
        gauges  = s.get("gauges", _DEFAULT_SETTINGS["gauges"])

        # In compact mode: hide everything except the compact bar
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

        # (key, label, unit, lo, hi, color, warn, danger, is_temp, invert_warn, is_usage)
        card_defs = [
            ("cpu_usage", "CPU USAGE", "%",   0, 100, CYAN,      70, 90,  False, False, True),
            ("cpu_temp",  "CPU TEMP",  "°C",  0, 105, CPU_COLOR, 80, 95,  True,  False, False),
            ("gpu_usage", "GPU USAGE", "%",   0, 100, CYAN,      70, 90,  False, False, True),
            ("gpu_temp",  "GPU TEMP",  "°C",  0,  95, GPU_COLOR, 75, 88,  True,  False, False),
        ]
        gc = s.get("gauge_colors", {})
        for key, label, unit, lo, hi, color, warn, danger, is_temp, inv, is_usage in card_defs:
            if not gauges.get(key, True):
                continue
            eff_color = gc.get(key) or color  # use custom color if set
            if key not in self._cards:
                self._cards[key] = MonitorCard(label, unit, lo, hi, eff_color,
                                               warn, danger, is_temp=is_temp,
                                               invert_warn=inv, is_usage=is_usage,
                                               resource_key=key)
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

        # Store last metrics for snapshot export
        self._last_metrics = dict(metrics)

        # DataLogger
        if self._logger and metrics:
            self._logger.record(metrics)
            if time.monotonic() - self._logger._last_flush > 60:
                self._logger.flush()

        # History window live update
        if self._history_win and self._history_win.isVisible():
            for key, val in metrics.items():
                self._history_win.update_metric(key, val)

        # Tray icon level
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

        # Threshold alerts
        if self._settings.get("alerts", True) and self._tray:
            alert_defs = [
                ("cpu_temp",  metrics.get("cpu_temp",  0), 95,  "CPU Temperature"),
                ("gpu_temp",  metrics.get("gpu_temp",  0), 88,  "GPU Temperature"),
                ("cpu_usage", metrics.get("cpu_usage", 0), 90,  "CPU Usage"),
                ("gpu_usage", metrics.get("gpu_usage", 0), 90,  "GPU Usage"),
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
        dlg = SettingsDialog(self._settings, parent=self)
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
            # Preserve current live settings
            for key in ("theme", "compact", "gauges", "monitor", "autostart",
                        "export", "always_on_top", "alerts"):
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
        if self._docked and self._dock_info:
            dock_x = self._dock_info.get("dock_x", p.x())
            dock_y = self._dock_info.get("dock_y", p.y())
            if abs(p.x() - dock_x) > 50 or abs(p.y() - dock_y) > 50:
                self._docked = False
                cw = self.centralWidget()
                if isinstance(cw, _Background):
                    cw.set_squared(False)
                self._title_bar.dock_btn.set_active(False)
                # Restore pre-dock size so window isn't full-width after drag
                if self._pre_dock_geom is not None:
                    self.resize(self._pre_dock_geom.width(),
                                self._pre_dock_geom.height())

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
                # Restore pre-dock size so dragging off dock can resize correctly
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
        # Always dock to whichever screen the window is currently on
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
        # Force all gauge cards to repaint after resize
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

    # Apply initial palette (theme resolved from settings inside MainWindow.__init__)
    app.setPalette(_make_palette(_THEME))

    win = MainWindow()
    # Re-apply palette now that settings have been loaded
    app.setPalette(_make_palette(_THEME))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
