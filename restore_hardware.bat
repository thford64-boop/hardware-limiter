@echo off
:: ============================================================
::  EMERGENCY RESTORE — undoes all limiter changes instantly
::  restore_hardware.bat
:: ============================================================

setlocal
cd /d "%~dp0"
title Restoring Hardware Profile...

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && restore_hardware.bat' -Verb RunAs"
    exit /b
)

echo.
echo  +----------------------------------------------------------+
echo  ^|  HARDWARE TIER ANALYSIS TOOL -- Emergency Restore       ^|
echo  +----------------------------------------------------------+
echo.
echo  Restoring your real hardware profile...
echo.

set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" where python3 >nul 2>&1 && set PYTHON_CMD=python3

if "%PYTHON_CMD%"=="" (
    echo  [ERROR] Python not found. Attempting manual power plan restore...
    echo.
    echo  Activating Balanced power plan manually...
    powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e
    echo  Done. Your CPU frequency cap has been removed.
) else (
    %PYTHON_CMD% limiter.py --restore
)

echo.
echo  +----------------------------------------------------------+
echo  ^|  Restore complete.                                       ^|
echo  +----------------------------------------------------------+
echo.
pause
endlocal
