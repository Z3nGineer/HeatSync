"""
heatsync/shortcuts.py — cross-platform desktop shortcut creation.
"""

import os
import sys
import subprocess

from .constants import IS_WINDOWS, _SCRIPT_DIR


def _create_shortcuts() -> None:
    try:
        if IS_WINDOWS:
            _shortcuts_windows()
        elif sys.platform == "darwin":
            _shortcuts_macos()
        else:
            _shortcuts_linux()
    except Exception as e:
        print(f"[WARN] Shortcut creation failed: {e}")


def _shortcuts_linux() -> None:
    apps_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(apps_dir, exist_ok=True)
    path = os.path.join(apps_dir, "heatsync.desktop")

    icon = os.path.join(_SCRIPT_DIR, "assets", "icon.png")

    if getattr(sys, "frozen", False):
        cmd = os.path.abspath(sys.executable)
    else:
        cmd = f"{os.path.abspath(sys.executable)} {os.path.abspath(sys.argv[0])}"

    with open(path, "w") as f:
        f.write(
            f"[Desktop Entry]\nType=Application\nName=HeatSync\n"
            f"Comment=System hardware monitor\n"
            f"Exec={cmd}\nIcon={icon}\n"
            f"Terminal=false\nCategories=System;Monitor;\n"
            f"StartupNotify=false\nStartupWMClass=heatsync\n"
        )


def _shortcuts_windows() -> None:
    run_bat = os.path.join(_SCRIPT_DIR, "run.bat")
    icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")

    targets = []
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop):
        targets.append(os.path.join(desktop, "HeatSync.lnk"))

    start_menu = os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"
    )
    if os.path.isdir(start_menu):
        targets.append(os.path.join(start_menu, "HeatSync.lnk"))

    for lnk_path in targets:
        ps = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{lnk_path}"); '
            f'$s.TargetPath = "{run_bat}"; '
            f'$s.WorkingDirectory = "{_SCRIPT_DIR}"; '
            f'$s.Description = "HeatSync System Monitor"; '
            f'$s.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=10,
        )


def _shortcuts_macos() -> None:
    apps_dir = os.path.expanduser("~/Applications")
    os.makedirs(apps_dir, exist_ok=True)
    launcher = os.path.join(apps_dir, "HeatSync")

    run_sh = os.path.join(_SCRIPT_DIR, "run.sh")
    with open(launcher, "w") as f:
        f.write(f"#!/bin/bash\nexec bash \"{run_sh}\"\n")
    os.chmod(launcher, 0o755)
