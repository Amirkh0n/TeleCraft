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

engine_options = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
    "pool_recycle": 3600,
}
if not DATABASE_URL.endswith(":memory:"):
    engine_options.update(
        pool_size=settings.CONNECTION_POOL_SIZE,
        max_overflow=max(0, settings.MAX_CONNECTIONS - settings.CONNECTION_POOL_SIZE),
    )

engine = create_async_engine(DATABASE_URL, **engine_options)

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
    """Add known missing columns without hiding unrelated database errors."""
    from sqlalchemy import inspect, text

    migrations = {
        "bots": {
            "webhook_url": "ALTER TABLE bots ADD COLUMN webhook_url VARCHAR(500)",
            "webhook_set": "ALTER TABLE bots ADD COLUMN webhook_set BOOLEAN DEFAULT 0",
            "username": "ALTER TABLE bots ADD COLUMN username VARCHAR(255)",
            "onboarding_completed": "ALTER TABLE bots ADD COLUMN onboarding_completed BOOLEAN DEFAULT 0",
        },
        "menus": {
            "message_text": "ALTER TABLE menus ADD COLUMN message_text TEXT",
            "position": "ALTER TABLE menus ADD COLUMN position INTEGER DEFAULT 0",
        },
        "user_sessions": {
            "pending_admin_id": "ALTER TABLE user_sessions ADD COLUMN pending_admin_id BIGINT",
        },
    }
    async with engine.begin() as conn:
        for table_name, columns in migrations.items():
            existing = await conn.run_sync(
                lambda sync_conn, name=table_name: {
                    column["name"] for column in inspect(sync_conn).get_columns(name)
                }
            )
            for column_name, statement in columns.items():
                if column_name not in existing:
                    await conn.execute(text(statement))
