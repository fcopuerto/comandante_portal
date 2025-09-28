@echo off
REM Build script for Windows PyInstaller distribution
REM Usage: run in a Developer Command Prompt or regular cmd with Python on PATH.

SETLOCAL ENABLEDELAYEDEXPANSION

REM ---- Configuration ----
SET APP_NAME=CobaltaXMonitor
SET ENTRY=main.py
SET DATA_TRANSLATIONS=translations;translations
REM Hidden imports to avoid runtime import errors
SET HIDDEN_IMPORTS=--hidden-import telethon --hidden-import cryptography --hidden-import paramiko

REM Clean previous build
IF EXIST build RMDIR /S /Q build
IF EXIST dist RMDIR /S /Q dist
IF EXIST %APP_NAME%.spec DEL %APP_NAME%.spec

ECHO Installing build dependencies (pyinstaller)...
python -m pip install --upgrade pip >NUL 2>&1
python -m pip install pyinstaller >NUL 2>&1
IF ERRORLEVEL 1 (
  ECHO Failed to install PyInstaller.
  EXIT /B 1
)

ECHO Building one-folder distribution...
pyinstaller --noconfirm --clean --name %APP_NAME% ^
  --add-data "%DATA_TRANSLATIONS%" ^
  %HIDDEN_IMPORTS% ^
  %ENTRY%
IF ERRORLEVEL 1 (
  ECHO Build failed.
  EXIT /B 1
)

ECHO.
ECHO One-folder build output: dist\%APP_NAME%\%APP_NAME%.exe
ECHO.
CHOICE /M "Also build one-file executable?"
IF ERRORLEVEL 2 GOTO END

ECHO Building one-file distribution...
pyinstaller --noconfirm --clean --onefile --name %APP_NAME%-single ^
  --add-data "%DATA_TRANSLATIONS%" ^
  %HIDDEN_IMPORTS% ^
  %ENTRY%
IF ERRORLEVEL 1 (
  ECHO One-file build failed.
  EXIT /B 1
)
ECHO Single-file build output: dist\%APP_NAME%-single.exe

:END
ECHO Done.
ENDLOCAL
