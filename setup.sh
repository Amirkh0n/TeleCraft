#!/bin/bash

# TeleCraft Setup Script for Render/Heroku/Cloud Run
# This script automatically configures and starts TeleCraft

set -e

echo "🚀 TeleCraft Auto-Setup Script"
echo "================================"
echo ""

# Function to print colored messages
print_success() {
    echo -e "\033[0;32m✅ $1\033[0m"
}

print_info() {
    echo -e "\033[1;33mℹ️  $1\033[0m"
}

# Function to get environment variable
get_env_var() {
    echo ${!1:-}
}

# Set environment variables from system or defaults
TELEGRAM_TOKEN=$(get_env_var TELEGRAM_TOKEN)
BOT_TOKENS=$(get_env_var BOT_TOKENS)
DATABASE_URL=$(get_env_var DATABASE_URL)
WEBHOOK_HOST=$(get_env_var WEBHOOK_HOST)
WEBHOOK_PORT=$(get_env_var WEBHOOK_PORT)
LOG_LEVEL=$(get_env_var LOG_LEVEL)
DEBUG=$(get_env_var DEBUG)
MAX_CONNECTIONS=$(get_env_var MAX_CONNECTIONS)
CONNECTION_POOL_SIZE=$(get_env_var CONNECTION_POOL_SIZE)
RATE_LIMIT_REQUESTS=$(get_env_var RATE_LIMIT_REQUESTS)
RATE_LIMIT_WINDOW=$(get_env_var RATE_LIMIT_WINDOW)

# Check if TELEGRAM_TOKEN is set
if [ -z "$TELEGRAM_TOKEN" ]; then
    print_error "TELEGRAM_TOKEN is not set!"
    print_info "Please set TELEGRAM_TOKEN in your environment or Render dashboard"
    exit 1
fi

# Set default values if not provided
DATABASE_URL=${DATABASE_URL:-sqlite+aiosqlite:///./constructor.db}
WEBHOOK_HOST=${WEBHOOK_HOST:-0.0.0.0}
WEBHOOK_PORT=${WEBHOOK_PORT:-8000}
LOG_LEVEL=${LOG_LEVEL:-INFO}
DEBUG=${DEBUG:-False}
MAX_CONNECTIONS=${MAX_CONNECTIONS:-20}
CONNECTION_POOL_SIZE=${CONNECTION_POOL_SIZE:-10}
RATE_LIMIT_REQUESTS=${RATE_LIMIT_REQUESTS:-100}
RATE_LIMIT_WINDOW=${RATE_LIMIT_WINDOW:-60}

print_info "TELEGRAM_TOKEN: $TELEGRAM_TOKEN"
print_info "WEBHOOK_HOST: $WEBHOOK_HOST"
print_info "WEBHOOK_PORT: $WEBHOOK_PORT"
print_info "DATABASE_URL: $DATABASE_URL"
print_info "LOG_LEVEL: $LOG_LEVEL"
print_success "Configuration loaded"

# Create environment file
cat > .env << EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
BOT_TOKENS=$BOT_TOKENS
DATABASE_URL=$DATABASE_URL
WEBHOOK_HOST=$WEBHOOK_HOST
WEBHOOK_PORT=$WEBHOOK_PORT
LOG_LEVEL=$LOG_LEVEL
LOG_FORMAT=json
MAX_CONNECTIONS=$MAX_CONNECTIONS
CONNECTION_POOL_SIZE=$CONNECTION_POOL_SIZE
RATE_LIMIT_REQUESTS=$RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW=$RATE_LIMIT_WINDOW
ADMIN_IDS=
DEBUG=$DEBUG
TESTING=False
EOF

print_success ".env file created"

# Initialize database
print_info "Initializing database..."
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
print_success "Database initialized"

# Create necessary directories
print_info "Creating necessary directories..."
mkdir -p data logs
print_success "Directories created"

# Check if we're in a container
if [ -f /.dockerenv ]; then
    print_success "Running in container environment"
else
    print_info "Running in non-container environment"
fi

# Start the application
print_info "Starting TeleCraft..."
echo ""
exec uvicorn app.main:app --host 0.0.0.0 --port $WEBHOOK_PORT
