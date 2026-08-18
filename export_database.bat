@echo off
REM =========================================================================
REM Kathmandu School Van Tracking & Safety System - 1-Click Database Exporter
REM Run this before zipping the project to ensure all users and trips are saved!
REM =========================================================================

echo Checking PHP runtime...
where php >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set PHP_EXE=php
) else if exist "C:\xampp\php\php.exe" (
    set PHP_EXE=C:\xampp\php\php.exe
) else (
    echo [ERROR] PHP executable not found.
    pause
    exit /b 1
)

echo Exporting complete live database with all users, trips, and telemetry...
"%PHP_EXE%" "%~dp0scripts\export_database.php"

if %ERRORLEVEL% equ 0 (
    echo.
    echo Database exported successfully to database\full_database_dump.sql!
    echo You can now zip the project folder and send it to your friend.
) else (
    echo.
    echo [ERROR] Export failed. Make sure MySQL is running in XAMPP.
)

pause
