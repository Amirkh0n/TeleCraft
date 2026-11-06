#!/usr/bin/env python3
"""
TeleCraft Webhook Server Startup Script
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from core.logger import logger
from core.database import init_models
from core.config import settings
from app.main import app


async def main():
    """Main startup function"""
    print("\n" + "="*60)
    print("🚀 TeleCraft Webhook Server")
    print("="*60 + "\n")

    # Initialize database
    try:
        print("Initializing database...")
        await init_models()
        print("✅ Database initialized successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        print(f"❌ Database initialization failed: {e}")
        sys.exit(1)

    print(f"\n✅ Configuration loaded:")
    print(f"   - WEBHOOK_HOST: {settings.WEBHOOK_HOST}")
    print(f"   - WEBHOOK_PORT: {settings.WEBHOOK_PORT}")
    print(f"   - LOG_LEVEL: {settings.LOG_LEVEL}")
    print(f"   - DEBUG: {settings.DEBUG}")
    print()

    print("Starting Webhook Server...\n")
    print(f"📡 Server will be available at: http://{settings.WEBHOOK_HOST}:{settings.WEBHOOK_PORT}")
    print(f"📊 Health check: http://{settings.WEBHOOK_HOST}:{settings.WEBHOOK_PORT}/health")
    print(f"📈 Metrics: http://{settings.WEBHOOK_HOST}:{settings.WEBHOOK_PORT}/metrics\n")
    print("="*60)
    print("🤖 Press Ctrl+C to stop")
    print("="*60 + "\n")

    try:
        import uvicorn
        uvicorn.run(
            app,
            host=settings.WEBHOOK_HOST,
            port=settings.WEBHOOK_PORT,
            reload=settings.DEBUG
        )
    except KeyboardInterrupt:
        print("\n\n👋 Webhook server stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
