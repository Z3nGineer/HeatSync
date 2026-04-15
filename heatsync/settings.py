"""
heatsync/settings.py — default settings schema, load/save functions.
"""

import json

from .constants import _SETTINGS_FILE

# ── Default settings ──────────────────────────────────────────────────────────
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
    "alert_thresholds": {
        "cpu_temp":  95,
        "gpu_temp":  95,
        "cpu_usage": 95,
        "gpu_usage": 100,  # effectively off — GPU usage at 100% is normal
    },
    "alerts_enabled": {
        "cpu_temp":  True,
        "gpu_temp":  True,
        "cpu_usage": False,  # off — high CPU usage is normal during gaming/compile/AI
        "gpu_usage": False,  # off — high GPU usage is normal during gaming/AI
    },
    "locked_to_top": False,
    "first_run_done": False,
    "pawnio_prompt_shown": False,
}

_GEOMETRY_KEYS = frozenset({
    "x", "y", "w", "h", "docked",
    "dock_x", "dock_y", "dock_w",
    "pre_dock_w", "pre_dock_h",
    "compact_pos",
})
_VALID_REFRESH_MS = {500, 1000, 2000, 5000, 10000}


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE) as f:
            stored = json.load(f)
    except Exception:
        stored = {}
    result = dict(_DEFAULT_SETTINGS)
    _allowed = frozenset(_DEFAULT_SETTINGS.keys()) | _GEOMETRY_KEYS
    for k, v in stored.items():
        if k not in _allowed:
            continue  # strip unknown top-level keys
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    # Clamp / validate scalar settings
    result["opacity"]    = max(20, min(100, int(result.get("opacity", 100))))
    result["refresh_ms"] = (result.get("refresh_ms", 1000)
                            if result.get("refresh_ms", 1000) in _VALID_REFRESH_MS
                            else 1000)
    result["monitor"]    = max(0, int(result.get("monitor", 0)))
    return result


def _save_settings(d: dict) -> None:
    try:
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass
