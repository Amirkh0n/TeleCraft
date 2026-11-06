from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.pool import NullPool
from models.base import Base
import models
from core.config import settings

DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.CONNECTION_POOL_SIZE,
    max_overflow=settings.MAX_CONNECTIONS - settings.CONNECTION_POOL_SIZE,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_light_migrations()


async def _run_light_migrations():
    """Add missing columns to existing tables (lightweight SQLite/PG migration)"""
    from sqlalchemy import text

    migrations = [
        "ALTER TABLE bots ADD COLUMN webhook_url VARCHAR(500)",
        "ALTER TABLE bots ADD COLUMN webhook_set BOOLEAN DEFAULT 0",
    ]
    async with engine.begin() as conn:
        for statement in migrations:
            try:
                await conn.execute(text(statement))
            except Exception:
                # Column already exists — ok
                pass
