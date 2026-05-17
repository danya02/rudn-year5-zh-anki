@echo off
REM start.bat — Bootstrap launcher for the Chinese Anki Pipeline (Windows).
REM Run this once (or any time); it sets up a virtualenv and launches the wizard.

cd /d "%~dp0"

REM Check for Python
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install it from https://python.org and rerun this script.
    pause
    exit /b 1
)

REM Create virtualenv if missing
if not exist ".venv\" (
    echo Setting up Python environment (first run only) ...
    python -m venv .venv
)

REM Activate and install / upgrade deps
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

REM Launch the wizard
python pipeline.py wizard

pause
