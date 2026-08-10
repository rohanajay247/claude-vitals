@echo off
REM Double-click to start the usage bar. pythonw.exe means no console window
REM appears and nothing is left behind when this script exits.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "run.pyw"
