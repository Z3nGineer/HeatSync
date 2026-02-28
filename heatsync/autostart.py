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
