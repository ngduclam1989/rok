@echo off
title RoK Auto Farm Bot
chcp 65001 > nul
echo ======================================================
echo           KHỞI CHẠY BOT ROK (AUTO FARM)
echo ======================================================
echo.
echo Đang kết nối và khởi chạy bot (RoKBot.exe)...
echo.

:: Gọi trực tiếp file EXE đã biên dịch để chạy kịch bản tuần tự
RoKBot.exe fleet --sequential

echo.
echo Bot đã dừng hoặc gặp sự cố. Bấm phím bất kỳ để thoát...
pause > nul
