@echo off
REM Claude Vitals - complete removal.
REM Quit the app from the tray first, or this will tell you to.
REM
REM Prefers the SYSTEM Python on purpose: running this from .venv\Scripts\
REM would mean the interpreter lives inside the folder it is trying to delete,
REM and Windows will not delete a running executable. uninstall.py needs only
REM the standard library, so system Python is enough.

setlocal
cd /d "%~dp0"

where python >nul 2>&1
if not errorlevel 1 (
    python uninstall.py --all
) else (
    if exist ".venv\Scripts\python.exe" (
        echo   Note: system Python not found, using the bundled environment.
        echo   The .venv folder cannot remove itself - delete this folder afterwards.
        echo.
        ".venv\Scripts\python.exe" uninstall.py --all
    ) else (
        echo   ERROR: no Python found. Just delete this folder.
    )
)

echo.
pause
