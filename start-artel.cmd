@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
    python artel.py up %*
) else (
    py -3 artel.py up %*
)
if errorlevel 1 pause
