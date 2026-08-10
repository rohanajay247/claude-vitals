@echo off
REM Claude Vitals - first-time setup.
REM Creates a private virtual environment and installs the dependencies.
REM Safe to re-run; it will simply reuse what already exists.

setlocal
cd /d "%~dp0"

echo.
echo   Claude Vitals - setup
echo   =====================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python was not found on your PATH.
    echo.
    echo   Install Python 3.10 or newer from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Fail early and clearly on an unsupported version rather than mid-install.
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo   ERROR: Claude Vitals needs Python 3.10 or newer.
    python -c "import sys; print('   You have: ' + sys.version.split()[0])"
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo   Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo   ERROR: could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo   Virtual environment already exists.
)

echo   Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo   ERROR: could not install dependencies. Are you online?
    pause
    exit /b 1
)

echo   Creating Desktop and Start menu shortcuts...
".venv\Scripts\python.exe" install_shortcuts.py

echo.
echo   Setup complete.
echo.
echo   Start Claude Vitals from the Desktop icon, the Start menu,
echo   or by double-clicking start.bat.
echo.
pause
