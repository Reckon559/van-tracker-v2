@echo off
REM =========================================================================
REM Kathmandu School Van Tracking & Safety System - 1-Click Database Setup
REM =========================================================================

echo [1/2] Checking PHP runtime...
where php >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set PHP_EXE=php
) else if exist "C:\xampp\php\php.exe" (
    set PHP_EXE=C:\xampp\php\php.exe
) else (
    echo [ERROR] PHP executable not found. Please install XAMPP or add PHP to your PATH.
    pause
    exit /b 1
)

echo [2/2] Initializing MySQL Database and Importing Full Data...
"%PHP_EXE%" "%~dp0scripts\import_database.php"

if %ERRORLEVEL% equ 0 (
    echo.
    echo =========================================================================
    echo Database setup completed successfully!
    echo You can now open http://localhost/van-tracker-v2/web in your browser.
    echo =========================================================================
) else (
    echo.
    echo [ERROR] Database setup failed. Make sure MySQL is running in XAMPP.
)

pause
