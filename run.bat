@echo off
setlocal
cd /d "%~dp0"
set "SRC=%~1"
if "%SRC%"=="" (
  echo Drag the folder that contains Magic.DB / Monster.DB / StdItems.DB here,
  echo then press Enter:
  set /p SRC=
)
if "%SRC%"=="" goto :eof
set "SRC=%SRC:"=%"
if not exist "%SRC%\StdItems.DB" (
  echo [ERROR] StdItems.DB not found in: %SRC%
  pause
  exit /b 1
)
python gomdb2sqlite.py --src "%SRC%" --out "%SRC%\REDM2.DB" --report "%SRC%\convert_report.txt"
echo.
echo Done. Output: %SRC%\REDM2.DB
pause
