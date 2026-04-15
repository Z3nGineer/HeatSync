@echo off
:: HeatSync installer for Windows
setlocal enabledelayedexpansion

echo === HeatSync Installer ===

:: Create virtual environment
echo [1/3] Creating Python virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create venv. Make sure Python 3.10+ is installed.
    pause
    exit /b 1
)
echo       Virtual environment created at .venv\

:: Install dependencies
echo [2/3] Installing dependencies...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt -q
echo       Dependencies installed.

:: Autostart is configured on first launch via Task Scheduler (needs admin,
:: which run.bat supplies by self-elevating). Just scrub any legacy
:: HKCU\...\Run entry from a previous install.
echo [3/3] Cleaning up legacy autostart entry (if any)...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "HeatSync" /f >nul 2>&1

echo.
echo === Done! ===
echo Run HeatSync with:  run.bat  (will prompt for admin)
echo First launch creates the scheduled task for autostart.
pause
