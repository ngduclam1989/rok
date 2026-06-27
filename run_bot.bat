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

:: Kiem tra xem nguoi dung da truyen serial hoac yeu cau interactive chua
echo "%*" | findstr /i "\--serial \-s" >nul
if %errorlevel% equ 0 (
    echo [INFO] Nguoi dung da chi dinh thiet bi qua doi so.
    echo [INFO] Dang chay lenh:
    echo   .venv\Scripts\python.exe main.py bot %*
    echo.
    ".venv\Scripts\python.exe" main.py bot %*
) else (
    :: Tu dong tim thiet bi dau tien de chay khong can hoi
    set AUTO_SERIAL=
    for /f "usebackq tokens=*" %%i in (`".venv\Scripts\python.exe" -c "from core.config_io import first_device_serial; from pathlib import Path; print(first_device_serial(Path('devices.yaml')) or '')" 2^>nul`) do (
        set "AUTO_SERIAL=%%i"
    )

    if not "%AUTO_SERIAL%"=="" (
        echo [INFO] Tu dong phat hien va chon thiet bi: %AUTO_SERIAL%
        echo [INFO] Dang chay lenh:
        echo   .venv\Scripts\python.exe main.py bot --serial %AUTO_SERIAL% %*
        echo.
        ".venv\Scripts\python.exe" main.py bot --serial %AUTO_SERIAL% %*
    ) else (
        echo [WARN] Khong phat hien thay thiet bi ADB nao dang ket noi.
        echo [INFO] Dang chay lenh:
        echo   .venv\Scripts\python.exe main.py bot %*
        echo.
        ".venv\Scripts\python.exe" main.py bot %*
    )
)

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
