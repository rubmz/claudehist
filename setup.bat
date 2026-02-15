@echo off
REM Setup script for Claude Code Session History (Windows)

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%.venv

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m virtualenv "%VENV_DIR%"
)

REM Activate and install dependencies
call "%VENV_DIR%\Scripts\activate.bat"
echo Installing Python dependencies...
pip install PyQt6 PyWinCtl

REM Run setup (hook registration) using the venv Python
python "%SCRIPT_DIR%setup.py"

echo.
echo Virtual environment created at: %VENV_DIR%
echo To launch the GUI, run:
echo   %VENV_DIR%\Scripts\python %SCRIPT_DIR%review_gui.py
