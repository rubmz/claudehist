@echo off
REM Setup script for Claude Code Session History (Windows)

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%.venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Install dependencies using venv pip directly
echo Installing Python dependencies...
"%VENV_PIP%" install PyQt6 PyWinCtl
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

REM Run setup (hook registration) using the venv Python
"%VENV_PYTHON%" "%SCRIPT_DIR%setup.py"

REM Install /history command to ~/.claude/commands/
set CLAUDE_COMMANDS_DIR=%USERPROFILE%\.claude\commands
if not exist "%CLAUDE_COMMANDS_DIR%" mkdir "%CLAUDE_COMMANDS_DIR%"

REM Read template, replace placeholders with Windows paths, write to commands dir
REM Also fix the launch command for Windows (no nohup, no /dev/null)
REM Strip trailing backslash from SCRIPT_DIR for clean path joining
set SCRIPT_DIR_CLEAN=%SCRIPT_DIR:~0,-1%
powershell -NoProfile -Command ^
    "$t = Get-Content '%SCRIPT_DIR%commands\history.md' -Raw;" ^
    "$t = $t -replace 'nohup (.+?) > /dev/null 2>&1 &', '$1';" ^
    "$t = $t -replace 'CLAUDEHIST_VENV_PLACEHOLDER/bin/python', '%VENV_DIR%\Scripts\python.exe';" ^
    "$t = $t -replace 'CLAUDEHIST_VENV_PLACEHOLDER', '%VENV_DIR%';" ^
    "$t = $t -replace 'CLAUDEHIST_DIR_PLACEHOLDER', '%SCRIPT_DIR_CLEAN%';" ^
    "$t = $t -replace '/', '\';" ^
    "Set-Content '%CLAUDE_COMMANDS_DIR%\history.md' $t -NoNewline"
echo Installed /history command to %CLAUDE_COMMANDS_DIR%\history.md

echo.
echo Virtual environment created at: %VENV_DIR%
echo To launch the GUI, use /history or /last from claude or run: %VENV_DIR%\Scripts\python %SCRIPT_DIR%review_gui.py

pause