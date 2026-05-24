@echo off
title RoK Auto Farm Bot
chcp 65001 > nul
echo ======================================================
echo           KHỞI CHẠY BOT ROK (AUTO FARM)
echo ======================================================
echo.
echo Đang kết nối và khởi chạy bot, vui lòng đợi...
echo.

:: Gọi trực tiếp Python trong thư mục .venv mà không cần kích hoạt (activate) venv
call .venv\Scripts\python main.py bot --serial 127.0.0.1:5555 --resource cycle

echo.
echo Bot đã dừng hoặc gặp sự cố. Bấm phím bất kỳ để thoát...
pause > nul
