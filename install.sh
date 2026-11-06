#!/bin/bash

# TeleCraft Installation Script
# This script will help you set up TeleCraft quickly

set -e

echo "🚀 TeleCraft Installation Script"
echo "================================="
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "🐧 Detected: Linux"
    IS_LINUX=1
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🍎 Detected: macOS"
    IS_MAC=1
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "🪟 Detected: Windows"
    IS_WINDOWS=1
else
    echo "❌ Unsupported operating system"
    exit 1
fi

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Step 1: Check Python version
print_info "Checking Python version..."
if [ "$IS_WINDOWS" -eq 1 ]; then
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
else
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
fi

PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    print_error "Python 3.11+ required. Found: $PYTHON_VERSION"
    print_info "Please install Python 3.11 or higher"
    exit 1
fi

print_success "Python $PYTHON_VERSION detected"

# Step 2: Create virtual environment
print_info "Creating virtual environment..."
if [ "$IS_WINDOWS" -eq 1 ]; then
    python -m venv venv
else
    python3 -m venv venv
fi
print_success "Virtual environment created"

# Step 3: Activate virtual environment
print_info "Activating virtual environment..."
if [ "$IS_WINDOWS" -eq 1 ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi
print_success "Virtual environment activated"

# Step 4: Install dependencies
print_info "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
print_success "Dependencies installed"

# Step 5: Setup environment
print_info "Setting up environment..."
if [ -f ".env" ]; then
    print_info ".env file already exists, skipping..."
else
    print_info "Creating .env file..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_success ".env file created from template"
    else
        # Create minimal .env
        cat > .env << EOF
TELEGRAM_TOKEN=
DATABASE_URL=sqlite+aiosqlite:///./constructor.db
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=json
MAX_CONNECTIONS=20
CONNECTION_POOL_SIZE=10
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
DEBUG=False
TESTING=False
EOF
        print_success ".env file created"
    fi
fi

# Step 6: Initialize database
print_info "Initializing database..."
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
print_success "Database initialized"

# Step 7: Create directories
print_info "Creating necessary directories..."
mkdir -p data logs
print_success "Directories created"

# Step 8: Setup completion
echo ""
echo "================================="
print_success "Installation completed successfully!"
echo "================================="
echo ""
echo "📋 Next Steps:"
echo "1. Edit .env file and add your TELEGRAM_TOKEN"
echo "2. Run the constructor bot: python run_constructor.py"
echo "3. Run the webhook server: uvicorn app.main:app --reload"
echo ""
print_info "For more information, see QUICKSTART.md"
echo ""
