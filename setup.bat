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

REM --- Python -------------------------------------------------------------
REM Anyone who already has a suitable Python passes straight through and is
REM never prompted. Only if none is found do we offer to install one.
set "PYOK="
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYOK=1"
)

if not defined PYOK (
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\install_python.ps1"
    if errorlevel 2 (
        echo.
        pause
        exit /b 1
    )
    if errorlevel 1 (
        echo.
        pause
        exit /b 1
    )
    REM The installer put Python on PATH, but not in this already-running shell.
    for /f "delims=" %%P in ('powershell -NoProfile -Command "$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); (Get-Command python -ErrorAction SilentlyContinue).Source"') do set "PYEXE=%%P"
    if not defined PYEXE (
        echo   Python installed, but this window can't see it yet.
        echo   Close this window, open a new one, and run setup.bat again.
        echo.
        pause
        exit /b 1
    )
) else (
    set "PYEXE=python"
)

REM --- virtual environment ------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   Creating virtual environment...
    "%PYEXE%" -m venv .venv
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
