@echo off
title Build RoKBot EXE
chcp 65001 > nul

echo ======================================================
echo           ROK AUTO FARM BOT - EXE COMPILER
echo ======================================================
echo.

:: 1. Check virtual environment
if not exist .venv (
    echo [ERROR] .venv not found.
    echo [INFO] Run setup_env_py311.bat first.
    pause
    exit /b 1
)

:: 2. Check Python version.
echo [INFO] Checking Python version in .venv...
.venv\Scripts\python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if %errorlevel% neq 0 (
    echo [ERROR] .venv is not Python 3.12.
    echo [INFO] Run setup_env.bat to recreate .venv.
    pause
    exit /b 1
)

:: 3. Ensure PyInstaller is installed
echo [INFO] Checking PyInstaller...
.venv\Scripts\pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    .venv\Scripts\python -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

:: 4. Build EXE
echo [INFO] Building RoKBot.exe...
echo This may take a few minutes because Paddle and OpenCV are heavy.
.venv\Scripts\pyinstaller --clean --distpath . RoKBot.spec
if %errorlevel% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

:: 5. Clean temporary build folders
echo.
echo [INFO] Cleaning temporary folders...
if exist build (
    rd /s /q build
)
if exist dist (
    rd /s /q dist
)

echo.
echo [SUCCESS] RoKBot.exe created in the project root.
echo.
echo To run on another machine, copy:
echo   - assets/
echo   - scenarios/
echo   - data/
echo   - RoKBot.exe
echo   - devices.yaml
echo   - account.txt
echo.
echo Do not copy .venv, build, or dist.
echo.
pause
