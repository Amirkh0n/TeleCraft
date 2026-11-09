from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.pool import NullPool
import models  # noqa: F401  (registers all tables)
from core.config import settings
from core.db_url import parse_database_url

DATABASE_URL = settings.DATABASE_URL
db_config = parse_database_url(DATABASE_URL)

engine_options = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,  # also recovers connections dropped when a serverless DB suspends
    # Serverless Postgres (Neon) closes idle connections; recycle them well before that matters.
    "pool_recycle": 300 if db_config.is_postgres else 3600,
}
if db_config.connect_args:
    engine_options["connect_args"] = db_config.connect_args
if db_config.url.database != ":memory:":
    engine_options.update(
        pool_size=settings.CONNECTION_POOL_SIZE,
        max_overflow=max(0, settings.MAX_CONNECTIONS - settings.CONNECTION_POOL_SIZE),
    )

engine = create_async_engine(db_config.url, **engine_options)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_models():
    """Bring the schema up to date (Alembic), then protect any plaintext bot tokens."""
    from core.migrations import upgrade_database

    await upgrade_database(engine)
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
