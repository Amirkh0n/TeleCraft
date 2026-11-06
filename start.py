#!/usr/bin/env python3
"""
TeleCraft Startup Script
Simple startup script to run TeleCraft without Docker
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.database import init_models
from core.logger import logger
from constructor.bot import run_constructor_bot
from core.config import settings


async def initialize_database():
    """Initialize the database"""
    try:
        logger.info("Initializing database...")
        await init_models()
        logger.info("Database initialized successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        return False


async def main():
    """Main startup function"""
    print("\n" + "="*60)
    print("🚀 TeleCraft Startup")
    print("="*60 + "\n")

    # Initialize database
    if not await initialize_database():
        print("\n❌ Database initialization failed. Please check the error above.")
        sys.exit(1)

    print(f"\n✅ Configuration loaded:")
    print(f"   - TELEGRAM_TOKEN: {'*' * 10} (set)")
    print(f"   - WEBHOOK_PORT: {settings.WEBHOOK_PORT}")
    print(f"   - LOG_LEVEL: {settings.LOG_LEVEL}")
    print(f"   - DEBUG: {settings.DEBUG}")
    print()

    print("Starting TeleCraft...\n")
    print("The constructor bot will start in the console.")
    print("To start the webhook server, run another terminal with:")
    print("   uvicorn app.main:app --reload\n")
    print("="*60)
    print("🤖 Press Ctrl+C to stop")
    print("="*60 + "\n")

    try:
        # Start the constructor bot
        run_constructor_bot(settings.TELEGRAM_TOKEN)
    except KeyboardInterrupt:
        print("\n\n👋 TeleCraft stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
