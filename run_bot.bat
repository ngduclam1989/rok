@echo off
title RoK Auto Farm Bot
echo ======================================================
echo           STARTING ROK AUTO FARM BOT
echo ======================================================
echo.
echo Connecting and launching RoKBot.exe...
echo.

RoKBot.exe fleet --sequential

echo.
echo Bot stopped or encountered an error. Press any key to exit...
pause > nul
