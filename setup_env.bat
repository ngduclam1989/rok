@echo off
setlocal
title Setup RoKBot Python Environment

set FORCE_CLEAN=0
if /I "%~1"=="--clean" set FORCE_CLEAN=1
if /I "%~1"=="/clean" set FORCE_CLEAN=1

echo ======================================================
echo        ROK BOT - PYTHON ENVIRONMENT SETUP
echo ======================================================
echo.
echo Usage:
echo   setup_env.bat          Check/create .venv
echo   setup_env.bat --clean  Remove .venv first, then recreate
echo.

py -3.12 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.12 is not installed or not registered with py launcher.
    echo.
    echo Install Python 3.12 x64 from:
    echo https://www.python.org/downloads/
    echo.
    echo During install, enable:
    echo   - Add python.exe to PATH
    echo   - Install launcher for all users
    echo.
    pause
    exit /b 1
)

if exist .venv (
    echo [WARN] Existing .venv found.
    echo [INFO] A copied .venv often contains old machine-specific paths.
    echo [INFO] For another PC, or after Python/dependency errors, recreate it.
    echo.
    if exist .venv\Scripts\python.exe (
        .venv\Scripts\python.exe --version
        .venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
        if %errorlevel% neq 0 (
            echo [WARN] Existing .venv is not Python 3.12. It must be recreated.
            set FORCE_CLEAN=1
        )
    ) else (
        echo [WARN] Existing .venv has no Python executable. It must be recreated.
        set FORCE_CLEAN=1
    )
    echo.
    if "%FORCE_CLEAN%"=="0" (
        choice /c YN /m "Recreate .venv now"
        if errorlevel 2 (
            echo [INFO] Keeping existing .venv. No changes made.
            exit /b 0
        )
    )
    echo [INFO] Removing old .venv...
    rmdir /s /q .venv
)

echo [INFO] Creating .venv with Python 3.12...
py -3.12 -m venv .venv
if %errorlevel% neq 0 exit /b %errorlevel%

echo [INFO] Upgrading pip tooling...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if %errorlevel% neq 0 exit /b %errorlevel%

echo [INFO] Installing project requirements...
.venv\Scripts\python.exe -m pip install --use-deprecated=legacy-resolver -r requirements.txt
if %errorlevel% neq 0 exit /b %errorlevel%

echo [INFO] Verifying imports...
.venv\Scripts\python.exe -c "import airtest, numpy, cv2, paddleocr, paddle; print('imports ok')"
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo [SUCCESS] Environment is ready.
echo Run:
echo   .venv\Scripts\python.exe main.py devices
echo   .venv\Scripts\python.exe main.py bot --serial YOUR_SERIAL --control-mode adb --max-iter 1
echo.
pause
