@echo off
setlocal EnableDelayedExpansion

REM =========================================================================
REM  Kathmandu School Van Tracking and Safety System (van-tracker-v2)
REM  Master 1-Click System Launcher
REM =========================================================================
title VanTracker v2 - Master Launcher
color 0A

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

echo =========================================================================
echo    Kathmandu School Van Tracking and Safety System (van-tracker-v2)
echo                  1-Click Full System Startup
echo =========================================================================
echo.

REM -------------------------------------------------------------------------
REM 1. Locate PHP Runtime
REM -------------------------------------------------------------------------
echo [1/4] Checking PHP runtime...
set "PHP_EXE="
where php >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PHP_EXE=php"
) else if exist "C:\xampp\php\php.exe" (
    set "PHP_EXE=C:\xampp\php\php.exe"
)

if "!PHP_EXE!"=="" (
    echo.
    echo [ERROR] PHP executable not found.
    echo Please install XAMPP or add PHP to your Windows PATH environment.
    echo.
    pause
    exit /b 1
)
echo    -- PHP found: !PHP_EXE!

REM -------------------------------------------------------------------------
REM 2. Locate / Setup Python Virtual Environment
REM -------------------------------------------------------------------------
echo [2/4] Checking Python Routing and ML Environment...
set "PYTHON_EXE="
if exist "%ROOT_DIR%routing-service\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%routing-service\.venv\Scripts\python.exe"
) else if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo    -- Creating Python virtual environment in routing-service\.venv...
        python -m venv "%ROOT_DIR%routing-service\.venv"
        set "PYTHON_EXE=%ROOT_DIR%routing-service\.venv\Scripts\python.exe"
        echo    -- Installing required Python packages...
        "!PYTHON_EXE!" -m pip install --upgrade pip
        "!PYTHON_EXE!" -m pip install -r "%ROOT_DIR%routing-service\requirements.txt" matplotlib seaborn
    )
)

if "!PYTHON_EXE!"=="" (
    echo.
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    echo.
    pause
    exit /b 1
)
echo    -- Python found: !PYTHON_EXE!

REM -------------------------------------------------------------------------
REM 3. Initialize / Check MySQL Database
REM -------------------------------------------------------------------------
echo [3/4] Initializing MySQL Database and Loading Datasets...
"!PHP_EXE!" "%ROOT_DIR%scripts\import_database.php"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] MySQL connection had an issue.
    echo Make sure MySQL is started in XAMPP on port 3306.
    echo.
)

REM -------------------------------------------------------------------------
REM 4. Launch Python Routing & ML Service (Port 5000)
REM -------------------------------------------------------------------------
echo [4/4] Starting Background Services...
echo    -- Launching Python Routing and Anomaly Detection Service (Port 5000)...
start "VanTracker - Python Routing and ML Engine" /D "%ROOT_DIR%routing-service" "!PYTHON_EXE!" app.py

REM Wait 2 seconds for Python service to start
ping 127.0.0.1 -n 3 >nul

REM -------------------------------------------------------------------------
REM 5. Launch Standalone PHP Web Server (Port 8000)
REM -------------------------------------------------------------------------
echo    -- Launching PHP Web Application Server (Port 8000)...
start "VanTracker - PHP Web Server" /D "%ROOT_DIR%" "!PHP_EXE!" -S 0.0.0.0:8000 -t web

REM Wait 1 second
ping 127.0.0.1 -n 2 >nul

REM -------------------------------------------------------------------------
REM 6. Open Web Browser & Display Credentials
REM -------------------------------------------------------------------------
echo    -- Opening Web Application in your default browser...
start http://127.0.0.1:8000/login.php

echo.
echo =========================================================================
echo                  ALL SERVICES ARE NOW RUNNING!
echo =========================================================================
echo.
echo   Web Application:    http://127.0.0.1:8000/login.php
echo   (Or via XAMPP):     http://localhost/van-tracker-v2/web/login.php
echo   Routing ML Service: http://127.0.0.1:5000/health
echo.
echo -------------------------------------------------------------------------
echo   Pre-configured Login Accounts:
echo -------------------------------------------------------------------------
echo   [Admin Account]  Email: admin@example.com     Password: admin123
echo   [Driver Account] Email: prashant@example.com  Password: driver123
echo   [Parent Account] Email: mandi@example.com     Password: parent123
echo   [Parent Account] Email: jun@example.com       Password: parent123
echo   [Parent Account] Email: shyam@example.com     Password: parent123
echo -------------------------------------------------------------------------
echo.
echo Leave this window open while using the application.
echo To shut down: Close this window and the two server windows.
echo.
pause
