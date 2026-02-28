"""
heatsync/sensors.py — all hardware sensor functions.
"""

import sys
import os
import glob
import subprocess
import time

import psutil

from .constants import (
    IS_WINDOWS,
    GPU_HANDLE, _AMD_DEV, _AMD_HWMON, _INTEL_DEV, _INTEL_HWMON, _WIN_GPU,
    pynvml,
)

# Prime the CPU percent measurement
psutil.cpu_percent()


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
    if IS_WINDOWS and _WIN_GPU:
        try:
            import wmi  # type: ignore
            w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Load" and "GPU" in s.Name and "Core" in s.Name:
                    return float(s.Value)
        except Exception:
            pass
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
    if IS_WINDOWS and _WIN_GPU:
        try:
            import wmi  # type: ignore
            w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Temperature" and "GPU" in s.Name:
                    return float(s.Value)
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


def s_gpu_power_limit() -> float:
    """Returns GPU TDP power limit in watts (pynvml), or 0.0 if unavailable."""
    if GPU_HANDLE:
        try:
            return pynvml.nvmlDeviceGetPowerManagementLimit(GPU_HANDLE) / 1000.0
        except Exception:
            return 0.0
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
