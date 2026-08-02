@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title ROK Bot

echo ======================================================
echo                  ROK BOT - RUN
echo ======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Khong tim thay .venv\Scripts\python.exe
    echo [INFO] Hay chay setup_env.bat truoc.
    exit /b 1
)

echo [INFO] Dang chay lenh:
echo   .venv\Scripts\python.exe main.py bot --serial zhkrinrsww7d6hbu
echo.

".venv\Scripts\python.exe" main.py bot --serial zhkrinrsww7d6hbu
exit /b %errorlevel%
