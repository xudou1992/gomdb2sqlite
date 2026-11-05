@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Install Python 3.8+ and make sure "python" works in cmd.
  pause
  exit /b 1
)
start "" pythonw gomdb2sqlite_gui.py
if errorlevel 1 python gomdb2sqlite_gui.py
