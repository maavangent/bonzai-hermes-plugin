@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "HERMES_PY=%USERPROFILE%\.hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "!HERMES_PY!" (
    set "HERMES_PY=%LOCALAPPDATA%\hermes-agent\venv\Scripts\python.exe"
)
if not exist "!HERMES_PY!" (
    set "HERMES_PY=python"
)

"!HERMES_PY!" install.py --interactive
echo.
pause
