@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "HERMES_PY=%USERPROFILE%\.hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "!HERMES_PY!" (
    set "HERMES_PY=%LOCALAPPDATA%\hermes-agent\venv\Scripts\python.exe"
)
if not exist "!HERMES_PY!" (
    rem Prefer the py launcher: a bare "python" can be the Microsoft Store stub.
    set "HERMES_PY=python"
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "HERMES_PY=%%P"
)

"!HERMES_PY!" install.py --interactive
if errorlevel 1 (
    echo.
    echo Installation did not finish. If Python is missing, install Hermes Desktop first.
)
echo.
pause
