#!/usr/bin/env python3
"""HeatSync — NZXT CAM-style system monitor"""
import sys, os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
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

from heatsync.mainwindow import main

# Re-export everything for backwards compatibility with `from HeatSync import X`
from heatsync import *  # noqa: F401, F403
from heatsync.constants import _get_cpu_name  # noqa: F401 (private, not picked up by *)
from heatsync.mainwindow import _Background  # noqa: F401
from heatsync.settings import _DEFAULT_SETTINGS, _load_settings, _save_settings  # noqa: F401

if __name__ == "__main__":
    main()
