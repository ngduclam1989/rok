@echo off
title RoK Auto Farm Bot Installer & Runner
chcp 65001 > nul

echo ======================================================
echo           ROK AUTO FARM BOT - SETUP ^& RUN
echo ======================================================
echo.

:: 1. Kiểm tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Không tìm thấy Python trên hệ thống!
    echo Vui lòng tải và cài đặt Python (phiên bản khuyên dùng: 3.10 hoặc 3.11) tại:
    echo https://www.python.org/downloads/
    echo.
    echo Sau khi cài đặt xong, hãy mở lại file này.
    pause
    exit /b 1
)

:: 2. Khởi tạo virtual environment nếu chưa có
if not exist .venv (
    echo [INFO] Đang khởi tạo môi trường ảo (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Không thể tạo môi trường ảo .venv!
        pause
        exit /b 1
    )
    echo [SUCCESS] Đã tạo thành công .venv.
    echo.
    echo [INFO] Đang cài đặt/nâng cấp thư viện cần thiết.
    echo Quá trình này có thể mất vài phút (tải các thư viện Airtest, OpenCV, PaddleOCR, PaddlePaddle)...
    echo.
    
    :: Nâng cấp pip và cài đặt dependencies
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Cài đặt các thư viện thất bại! Vui lòng kiểm tra kết nối mạng.
        pause
        exit /b 1
    )
    echo.
    echo [SUCCESS] Đã cài đặt đầy đủ tất cả thư viện!
    echo ======================================================
    echo.
)

:: 3. Chạy bot tuần tự mặc định
echo [INFO] Bắt đầu chạy bot tuần tự...
.venv\Scripts\python main.py fleet --sequential

echo.
echo [INFO] Bot đã dừng. Bấm phím bất kỳ để thoát...
pause > nul
