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
            "token_hash": "ALTER TABLE bots ADD COLUMN token_hash VARCHAR(64)",
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
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_bots_token_hash ON bots (token_hash)")
        )
    await protect_bot_tokens()


async def protect_bot_tokens() -> int:
    """Encrypt plaintext bot tokens and (re)compute lookup hashes. Safe to run on every start."""
    from sqlalchemy import select
    from core.logger import get_logger
    from core.security import decrypt_token, token_hash, uses_primary_key
    from models.bots import Bot

    log = get_logger("database")
    changed = 0
    async with AsyncSessionLocal() as session:
        for bot in (await session.execute(select(Bot))).scalars().all():
            try:
                plain = decrypt_token(bot.token)
            except ValueError:
                log.error("Bot id=%s token cannot be decrypted; skipping (check ENCRYPTION_KEY)", bot.id)
                continue
            if uses_primary_key(bot.token) and bot.token_hash == token_hash(plain):
                continue
            bot.token_hash = None  # free the unique slot before re-writing
            await session.flush()
            bot.token = plain  # validator encrypts with the primary key and sets token_hash
            changed += 1
        await session.commit()
    if changed:
        log.info("Protected %s bot token(s)", changed)
    return changed
