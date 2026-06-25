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
    echo.
    pause
    exit /b 1
)

if not exist "devices.yaml" (
    echo [WARN] Khong tim thay devices.yaml. Bot se chay theo cau hinh/mac dinh neu co.
    echo.
)

echo [INFO] Dang chay lenh:
echo   .venv\Scripts\python.exe main.py bot %*
echo.

".venv\Scripts\python.exe" main.py bot %*
set EXIT_CODE=%errorlevel%

echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Bot thoat voi ma loi %EXIT_CODE%.
) else (
    echo [INFO] Bot da chay xong.
)
echo.
pause
exit /b %EXIT_CODE%
