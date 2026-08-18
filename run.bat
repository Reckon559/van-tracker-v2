@echo off
REM =========================================================================
REM  Kathmandu School Van Tracking & Safety System (van-tracker-v2)
REM  1-Click Full System Launcher (Database + Python ML Engine + Web Server)
REM =========================================================================
title VanTracker v2 - Master Launcher
color 0A

echo =========================================================================
echo    Kathmandu School Van Tracking & Safety System (van-tracker-v2)
echo                  1-Click Full System Startup
echo =========================================================================
echo.

REM -------------------------------------------------------------------------
REM 1. Locate PHP Runtime
REM -------------------------------------------------------------------------
echo [1/4] Checking PHP runtime...
set PHP_EXE=
where php >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set PHP_EXE=php
) else if exist "C:\xampp\php\php.exe" (
    set PHP_EXE=C:\xampp\php\php.exe
)

if "%PHP_EXE%"=="" (
    echo [ERROR] PHP executable not found.
    echo Please install XAMPP or add PHP to your Windows PATH environment.
    pause
    exit /b 1
)
echo    -- PHP found: %PHP_EXE%

REM -------------------------------------------------------------------------
REM 2. Locate / Setup Python Virtual Environment
REM -------------------------------------------------------------------------
echo [2/4] Checking Python Routing & ML Environment...
set PYTHON_EXE=
if exist "%~dp0routing-service\.venv\Scripts\python.exe" (
    set PYTHON_EXE=%~dp0routing-service\.venv\Scripts\python.exe
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set PYTHON_EXE=%~dp0.venv\Scripts\python.exe
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo    -- Creating Python virtual environment in routing-service\.venv...
        python -m venv "%~dp0routing-service\.venv"
        set PYTHON_EXE=%~dp0routing-service\.venv\Scripts\python.exe
        echo    -- Installing required Python packages (Flask, OSMnx, Scikit-learn)...
        "%PYTHON_EXE%" -m pip install --upgrade pip
        "%PYTHON_EXE%" -m pip install -r "%~dp0routing-service\requirements.txt" matplotlib seaborn
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
echo    -- Python found: %PYTHON_EXE%

REM -------------------------------------------------------------------------
REM 3. Initialize / Check MySQL Database
REM -------------------------------------------------------------------------
echo [3/4] Initializing MySQL Database & Loading Complete Datasets...
"%PHP_EXE%" "%~dp0scripts\import_database.php"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] MySQL import had issues.
    echo Please ensure MySQL is running in XAMPP on port 3306.
    echo Press any key to continue attempting to launch services...
    pause
)

REM -------------------------------------------------------------------------
REM 4. Launch Python Routing & ML Service (Port 5000)
REM -------------------------------------------------------------------------
echo [4/4] Starting Background Services...
echo    -- Launching Python Routing & Anomaly Detection Service (Port 5000)...
start "VanTracker - Python Routing & ML Engine" cmd /k "cd /d "%~dp0routing-service" && "%PYTHON_EXE%" app.py"

REM Wait 2 seconds for Python service to bind port
timeout /t 2 /nobreak >nul

REM -------------------------------------------------------------------------
REM 5. Launch Standalone PHP Web Server (Port 8000)
REM -------------------------------------------------------------------------
echo    -- Launching PHP Web Application Server (Port 8000)...
start "VanTracker - PHP Web Server" cmd /k "cd /d "%~dp0" && "%PHP_EXE%" -S 127.0.0.1:8000 -t web"

REM Wait 1 second
timeout /t 1 /nobreak >nul

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
echo To shut down the application:
echo Close the two opened server terminal windows ("Python Routing & ML Engine" and "PHP Web Server").
echo.
pause
