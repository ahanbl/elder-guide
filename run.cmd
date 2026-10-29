@echo off
cd /d "%~dp0"
set "PY=C:\Users\blahan\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   ============================================================
echo    Elder Guide - annotation demo
echo    After it starts, open:  http://127.0.0.1:8765
echo    Stop: press Ctrl+C or close this window
echo   ============================================================
echo.

start "" http://127.0.0.1:8765
"%PY%" app.py

echo.
echo   Server stopped.
pause
