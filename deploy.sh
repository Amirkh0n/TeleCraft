#!/bin/bash

# TeleCraft Deployment Script for Render/Heroku/Cloud Run

echo "🚀 Deploying TeleCraft..."

# Set environment variables (should be set via Render dashboard or Heroku config)
export TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-your_constructor_bot_token}"
export BOT_TOKENS="${BOT_TOKENS:-}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./constructor.db}"
export WEBHOOK_HOST="${WEBHOOK_HOST:-0.0.0.0}"
export WEBHOOK_PORT="${WEBHOOK_PORT:-8000}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export DEBUG="${DEBUG:-False}"
export TESTING="${TESTING:-False}"
export MAX_CONNECTIONS="${MAX_CONNECTIONS:-20}"
export CONNECTION_POOL_SIZE="${CONNECTION_POOL_SIZE:-10}"
export RATE_LIMIT_REQUESTS="${RATE_LIMIT_REQUESTS:-100}"
export RATE_LIMIT_WINDOW="${RATE_LIMIT_WINDOW:-60}"
export ADMIN_IDS="${ADMIN_IDS:-}"

echo "✅ Environment variables configured"

# Check if running in container
if [ -f /.dockerenv ]; then
    echo "🐳 Running in Docker container"
else
    echo "💻 Running locally"
fi

# Run migrations if needed
echo "🔧 Running database migrations..."
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# Start the application
echo "🎯 Starting TeleCraft..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
