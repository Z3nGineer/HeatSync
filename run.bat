@echo off
:: LibreHardwareMonitor needs admin to read Ryzen/Intel CPU temp MSRs via WinRing0.
:: Self-elevate if we aren't already elevated, then launch pythonw detached.
net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~dp0run.bat' -Verb RunAs"
    exit /b
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0HeatSync.py"
