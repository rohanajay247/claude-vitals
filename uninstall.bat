@echo off
REM Claude Vitals - complete removal.
REM Quit the app from the tray first, or this will tell you to.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" uninstall.py --all
) else (
    python uninstall.py --all
)

echo.
pause
