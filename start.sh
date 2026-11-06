#!/bin/bash

# TeleCraft Startup Script for Linux/Mac

echo "========================================"
echo "🚀 TeleCraft Startup"
echo "========================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found!"
    echo "Copying .env.example to .env..."
    cp .env.example .env
    echo ""
    echo "Please edit .env file and add your TELEGRAM_TOKEN"
    echo ""
fi

# Create necessary directories
mkdir -p data logs

echo "Starting TeleCraft..."
echo ""
echo "Terminal 1 - Constructor Bot:"
echo "  python start.py"
echo ""
echo "Terminal 2 - Webhook Server:"
echo "  python webhook_start.py"
echo ""
read -p "Press Enter to continue..."

# Start constructor bot in new terminal
osascript -e 'tell application "Terminal" to do script "cd $(pwd) && python start.py"' 2>/dev/null || xterm -e "python start.py" &

# Wait a bit
sleep 3

# Start webhook server
echo "Starting Webhook Server..."
python webhook_start.py
