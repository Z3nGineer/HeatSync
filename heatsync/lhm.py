"""
heatsync/lhm.py — LibreHardwareMonitor backend for Windows.

Uses the HardwareMonitor pip package (pythonnet + bundled LHM DLL) to read
hardware sensors directly, without requiring a separate LHM process.
Falls back gracefully if the package is not installed or fails to initialize.
"""

import sys

available = False

_computer = None
_HardwareType = None
_SensorType = None

if sys.platform == "win32":
    try:
        # pythonnet hosts the CLR on this thread and, if COM isn't initialized
        # yet, leaves it as MTA. Qt's later OleInitialize() needs STA and fails
        # with "Cannot change thread mode after it is set." Claim STA first.
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        from HardwareMonitor.Hardware import Computer, HardwareType, SensorType

        _HardwareType = HardwareType
        _SensorType = SensorType

        _computer = Computer()
        _computer.IsCpuEnabled = True
        _computer.IsGpuEnabled = True
        _computer.IsStorageEnabled = True
        _computer.IsMemoryEnabled = True
        _computer.Open()
        available = True
        print("[INFO] LibreHardwareMonitor backend initialized (bundled)")
    except Exception as exc:
        print(f"[INFO] LHM backend not available: {exc}")
        _computer = None


def _update_hardware():
    """Call Update() on every hardware node so sensor values refresh."""
    if _computer is None:
        return
    try:
        for hw in _computer.Hardware:
            hw.Update()
            for sub in hw.SubHardware:
                sub.Update()
    except Exception:
        pass


def _find_sensor(hw_types, sensor_type, name_contains=None):
    """Find first matching sensor value after updating hardware."""
    if _computer is None:
        return None
    try:
        for hw in _computer.Hardware:
            if hw.HardwareType not in hw_types:
                continue
            hw.Update()
            for sensor in hw.Sensors:
                if sensor.SensorType == sensor_type:
                    if name_contains is None or name_contains.lower() in (sensor.Name or "").lower():
                        if sensor.Value is not None:
                            return float(sensor.Value)
            for sub in hw.SubHardware:
                sub.Update()
                for sensor in sub.Sensors:
                    if sensor.SensorType == sensor_type:
                        if name_contains is None or name_contains.lower() in (sensor.Name or "").lower():
                            if sensor.Value is not None:
                                return float(sensor.Value)
    except Exception:
        pass
    return None


# ── Public sensor functions ─────────────────────────────────────────────────
# Each returns a value or None (meaning "not available, try another backend").

def cpu_temp():
    HT, ST = _HardwareType, _SensorType
    if HT is None:
        return None
    val = _find_sensor([HT.Cpu], ST.Temperature, "Package")
    if val is None:
        val = _find_sensor([HT.Cpu], ST.Temperature)
    return val


def gpu_usage():
    HT, ST = _HardwareType, _SensorType
    if HT is None:
        return None
    return _find_sensor([HT.GpuNvidia, HT.GpuAmd, HT.GpuIntel], ST.Load, "Core")


def gpu_temp():
    HT, ST = _HardwareType, _SensorType
    if HT is None:
        return None
    return _find_sensor([HT.GpuNvidia, HT.GpuAmd, HT.GpuIntel], ST.Temperature)


def gpu_power():
    HT, ST = _HardwareType, _SensorType
    if HT is None:
        return None
    return _find_sensor([HT.GpuNvidia, HT.GpuAmd, HT.GpuIntel], ST.Power)


def fans():
    """Returns [(name, rpm), ...] for all detected fans."""
    if _computer is None:
        return []
    ST = _SensorType
    result = []
    try:
        for hw in _computer.Hardware:
            hw.Update()
            for sensor in hw.Sensors:
                if sensor.SensorType == ST.Fan and sensor.Value and float(sensor.Value) > 0:
                    result.append((sensor.Name or "Fan", int(float(sensor.Value))))
            for sub in hw.SubHardware:
                sub.Update()
                for sensor in sub.Sensors:
                    if sensor.SensorType == ST.Fan and sensor.Value and float(sensor.Value) > 0:
                        result.append((sensor.Name or "Fan", int(float(sensor.Value))))
    except Exception:
        pass
    return result


def pawnio_installed() -> bool:
    """Return True if the PawnIO driver service is registered on this system.

    PawnIO is a Microsoft-signed kernel driver used by newer LHM builds to
    read CPU temperature MSRs on Windows 11 systems that have Memory
    Integrity / Core Isolation enabled (which blocks the older WinRing0
    driver). Without PawnIO, CPU temps return None on those systems.
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\PawnIO",
        ):
            return True
    except (FileNotFoundError, OSError):
        return False
    except Exception:
        return False


def nvme_temps():
    """Returns [(name, temp_C), ...] for storage drives."""
    if _computer is None:
        return []
    HT, ST = _HardwareType, _SensorType
    result = []
    try:
        for hw in _computer.Hardware:
            if hw.HardwareType != HT.Storage:
                continue
            hw.Update()
            for sensor in hw.Sensors:
                if sensor.SensorType == ST.Temperature and sensor.Value and float(sensor.Value) > 0:
                    result.append((sensor.Name or hw.Name or "Drive", float(sensor.Value)))
                    break  # one temp per drive
            if len(result) >= 2:
                break
    except Exception:
        pass
    return result
