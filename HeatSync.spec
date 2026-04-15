# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_all

# Pull in the HardwareMonitor package's bundled .NET DLLs
# (LibreHardwareMonitorLib.dll, HidSharp.dll, etc.) plus its python-side
# data files so LHM works inside the frozen .exe on Windows.
_hm_datas, _hm_binaries, _hm_hidden = ([], [], [])
if sys.platform == "win32":
    _hm_datas, _hm_binaries, _hm_hidden = collect_all('HardwareMonitor')

a = Analysis(
    ['HeatSync.py'],
    pathex=[],
    binaries=_hm_binaries,
    datas=[('assets', 'assets'), ('VERSION', '.'), ('heatsync', 'heatsync')] + _hm_datas,
    hiddenimports=_hm_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# console=False: don't attach a console window to the GUI app.
# uac_admin=True (Windows only): bake admin elevation into the manifest so
#   LibreHardwareMonitor can read CPU temp MSRs via WinRing0. Without this
#   the .exe launches but CPU temps never populate.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='HeatSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=(sys.platform == "win32"),
    icon='assets/icon.png',
)
