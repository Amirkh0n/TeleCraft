@echo off
REM TeleCraft Startup Script for Windows

echo ========================================
echo 🚀 TeleCraft Startup
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
    echo.
) else (
    echo Virtual environment exists, activating...
    call venv\Scripts\activate.bat
    echo.
)

REM Check if .env file exists
if not exist ".env" (
    echo Warning: .env file not found!
    echo Copying .env.example to .env...
    copy .env.example .env
    echo.
    echo Please edit .env file and add your TELEGRAM_TOKEN
    echo.
)

REM Create necessary directories
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo Starting TeleCraft...
echo.
echo Terminal 1 - Constructor Bot:
echo   python start.py
echo.
echo Terminal 2 - Webhook Server:
echo   python webhook_start.py
echo.
echo Press any key to continue...
pause >nul

REM Start constructor bot in a new window
start "TeleCraft Constructor" python start.py

REM Wait a bit for constructor bot to start
timeout /t 3 /nobreak >nul

REM Start webhook server
echo Starting Webhook Server...
python webhook_start.py
