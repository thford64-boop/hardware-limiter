@echo off
:: ============================================================
::  Hardware Tier Performance Limiter — Launcher
::  run_limiter.bat
::
::  Automatically re-launches as Administrator if needed.
::  Requires Python 3.8+
:: ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Hardware Tier Limiter

:: ---- Check for admin, auto-elevate if needed ---------------
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [!] Requesting Administrator privileges...
    echo      (Required for power plan and registry changes)
    echo.
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && run_limiter.bat' -Verb RunAs"
    exit /b
)

echo.
echo  +----------------------------------------------------------+
echo  ^|      HARDWARE TIER PERFORMANCE LIMITER                  ^|
echo  ^|      Running as Administrator                           ^|
echo  +----------------------------------------------------------+
echo.

:: ---- Check Python ------------------------------------------
set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if "!PYTHON_CMD!"=="" where python3 >nul 2>&1 && set PYTHON_CMD=python3
if "!PYTHON_CMD!"=="" (
    echo  [ERROR] Python not found on PATH.
    pause
    exit /b 1
)

:: ---- Parse optional argument --------------------------------
if "%1"=="--restore" (
    echo  Restoring original hardware profile...
    !PYTHON_CMD! limiter.py --restore
    pause
    exit /b 0
)

if "%1"=="--status" (
    !PYTHON_CMD! limiter.py --status
    pause
    exit /b 0
)

:: ---- Run interactive menu -----------------------------------
!PYTHON_CMD! limiter.py

endlocal
