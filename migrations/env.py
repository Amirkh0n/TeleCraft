"""Alembic environment.

Two ways it runs:
* at application startup (core.migrations): an already open sync connection is passed in
  through ``config.attributes["connection"]``; nothing else is created here.
* from the command line (``alembic revision --autogenerate`` / ``alembic upgrade head``):
  an async engine is built from DATABASE_URL.
"""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import models  # noqa: F401  (registers every table on Base.metadata)
from core.db_url import parse_database_url
from core.config import settings
from models.base import Base

config = context.config
target_metadata = Base.metadata
db_config = parse_database_url(settings.DATABASE_URL)


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
        render_as_batch=db_config.is_sqlite,  # SQLite cannot ALTER most things in place
    )


def _run(connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_with_new_engine() -> None:
    engine = create_async_engine(db_config.url, poolclass=NullPool, connect_args=db_config.connect_args)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; run against a database.")

_connection = config.attributes.get("connection")
if _connection is not None:
    _run(_connection)
else:
    asyncio.run(_run_with_new_engine())
