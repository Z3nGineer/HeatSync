"""
heatsync/autostart.py — cross-platform autostart helpers.
"""

import os
import sys
import subprocess

from .constants import IS_WINDOWS, _SCRIPT_DIR


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
        if getattr(sys, "frozen", False):
            cmd = os.path.abspath(sys.executable)
        else:
            cmd = f"{os.path.abspath(sys.executable)} {os.path.abspath(sys.argv[0])}"
        with open(path, "w") as f:
            f.write(
                f"[Desktop Entry]\nType=Application\nName=HeatSync\n"
                f"Exec={cmd}\nHidden=false\nNoDisplay=false\n"
                f"X-GNOME-Autostart-enabled=true\n"
                f"StartupNotify=false\nStartupWMClass=heatsync\n"
                f"X-KDE-autostart-after=panel\n"
                f"X-KDE-Autostart-enabled=true\n"
            )
    else:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


_TASK_NAME = "HeatSync"


def _remove_legacy_run_key() -> None:
    """Delete the old HKCU\\...\\Run\\HeatSync entry from pre-Task-Scheduler installs."""
    import winreg  # type: ignore
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "HeatSync")
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass


def _autostart_windows(enable: bool) -> None:
    # HeatSync needs admin to read CPU temps via LHM/WinRing0. HKCU\...\Run
    # can't elevate, so we use a Task Scheduler logon task with RunLevel=Highest.
    # Creating/deleting such a task itself requires admin; run.bat self-elevates
    # to provide it.
    _remove_legacy_run_key()

    flags = 0x08000000  # CREATE_NO_WINDOW, suppresses schtasks console flash

    if enable:
        pythonw = os.path.join(_SCRIPT_DIR, ".venv", "Scripts", "pythonw.exe")
        script = os.path.join(_SCRIPT_DIR, "HeatSync.py")
        tr = f'"{pythonw}" "{script}"'
        subprocess.run(
            ["schtasks", "/Create", "/TN", _TASK_NAME, "/TR", tr,
             "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"],
            capture_output=True, timeout=10, creationflags=flags,
        )
    else:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
            capture_output=True, timeout=10, creationflags=flags,
        )


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
