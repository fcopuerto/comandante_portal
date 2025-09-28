@echo off
REM CobaltaX Server Monitor Setup Script for Windows
REM This script sets up and runs the server monitoring application

echo 🚀 CobaltaX Server Monitor Setup
echo 🌍 Multilanguage Support: English, Spanish, Catalan
echo =================================

REM Check if conda is available
where conda >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Error: Conda is not installed or not in PATH
    echo Please install Miniconda or Anaconda first
    pause
    exit /b 1
)

REM Navigate to project directory
cd /d "%~dp0"

REM Check if environment exists
conda env list | findstr "servers_cobaltax" >nul
if %ERRORLEVEL% NEQ 0 (
    echo 📦 Creating conda environment...
    conda env create -f environment.yml
    echo ✅ Environment created successfully
) else (
    echo ✅ Environment 'servers_cobaltax' already exists
)

REM Check if config needs to be updated
findstr "your_username your_password 192.168.1.100" config.py >nul
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ⚠️  IMPORTANT: Please update config.py with your server details before running!
    echo    - Edit server IP addresses
    echo    - Update SSH usernames and passwords
    echo    - Configure server names
    echo.
    pause
)

REM Activate environment and run application
echo 🔧 Activating environment and starting application...
call conda activate servers_cobaltax

echo 🎯 Starting Server Monitor...
python server_monitor.py

pause