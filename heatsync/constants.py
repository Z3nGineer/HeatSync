"""
heatsync/constants.py — platform flags, version, GPU init, colour constants.
"""

import sys
import os
import glob
import subprocess
import warnings
import platform

# ── Script directory & settings file ─────────────────────────────────────────
_SCRIPT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".heatsync.json")

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
    return "v1.0.75"

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
_WIN_GPU    = False   # True when a non-NVIDIA GPU was detected on Windows via WMI

pynvml = None  # may be set below

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pynvml as _pynvml
    pynvml = _pynvml
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

if not GPU_HANDLE and not _AMD_DEV and not _INTEL_DEV and IS_WINDOWS:
    try:
        import wmi as _wmi  # type: ignore
        _w = _wmi.WMI()
        for _ctrl in _w.Win32_VideoController():
            _name = (_ctrl.Name or "").strip()
            if not _name or "Microsoft Basic" in _name:
                continue
            GPU_NAME = _name
            _WIN_GPU = True
            print(f"[INFO] Windows GPU (WMI): {GPU_NAME}")
            break
    except Exception:
        pass

# ── Hardware vendor brand colors ──────────────────────────────────────────────
NVIDIA_GREEN = "#76b900"
AMD_RED      = "#ed1c24"
INTEL_BLUE   = "#0071c5"

# ── Shorthand accent constants ────────────────────────────────────────────────
CYAN   = "#00ccdd"
GREEN  = "#00e676"
PURPLE = "#9d6fff"
AMBER  = "#ffa040"
C_WARN = "#ff9800"
C_DANG = "#f44336"
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
    if _WIN_GPU:
        n = GPU_NAME.upper()
        if "INTEL" in n: return INTEL_BLUE
        if "AMD" in n or "RADEON" in n: return AMD_RED
    return PURPLE

CPU_COLOR = _cpu_vendor_color()
GPU_COLOR = _gpu_vendor_color()
