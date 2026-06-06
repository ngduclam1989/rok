@echo off
title Build RoKBot EXE
chcp 65001 > nul

echo ======================================================
echo           ROK AUTO FARM BOT - EXE COMPILER (ROOT)
echo ======================================================
echo.

:: 1. Kiểm tra thư mục môi trường ảo
if not exist .venv (
    echo [ERROR] Không tìm thấy thư mục .venv! Hãy chạy setup_and_run.bat trước để cài đặt môi trường.
    pause
    exit /b 1
)

:: 2. Đảm bảo PyInstaller đã được cài đặt trong .venv
echo [INFO] Kiểm tra PyInstaller trong môi trường ảo...
.venv\Scripts\pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Đang cài đặt PyInstaller vào môi trường ảo...
    .venv\Scripts\python -m pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Không thể cài đặt PyInstaller!
        pause
        exit /b 1
    )
)

:: 3. Chạy PyInstaller để build EXE trực tiếp tại thư mục gốc (ngang hàng main.py)
echo [INFO] Bắt đầu build EXE trực tiếp tại thư mục gốc...
echo Quá trình này có thể mất vài phút vì các thư viện Paddle và OpenCV khá nặng...
.venv\Scripts\pyinstaller --clean --distpath . RoKBot.spec
if %errorlevel% neq 0 (
    echo [ERROR] Build EXE thất bại!
    pause
    exit /b 1
)

:: 4. Dọn dẹp thư mục tạm build và dist (nếu có) để giữ thư mục gốc sạch sẽ
echo.
echo [INFO] Đang dọn dẹp các thư mục tạm thời để tránh rác...
if exist build (
    rd /s /q build
)
if exist dist (
    rd /s /q dist
)

echo.
echo [SUCCESS] Đã tạo thành công RoKBot.exe trực tiếp tại thư mục gốc!
echo.
echo [INFO] Để chạy bot ở máy khác, bạn chỉ cần copy các mục sau sang máy mới:
echo        - Thư mục: assets/
echo        - Thư mục: scenarios/
echo        - Thư mục: data/
echo        - File chạy: RoKBot.exe (nằm ở thư mục gốc)
echo        - File cấu hình: devices.yaml và account.txt
echo.
echo        * LƯU Ý: Không cần copy .venv, build, dist, hoặc bất kỳ file nào khác! *
echo.
pause
