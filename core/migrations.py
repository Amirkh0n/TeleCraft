"""Schema management on application start.

* New database: ``alembic upgrade head`` builds everything from the migration files.
* Database that already exists but was created before Alembic (``create_all`` + the old
  "light migrations"): it is brought to the baseline schema (missing columns/tables only,
  data untouched), then every newer migration applies normally.
* Alembic-managed database: ``alembic upgrade head`` applies anything new.

Schema changes after this point are NEVER made by hand here: add a migration
(``alembic revision --autogenerate -m "what changed"``), review it, commit it.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from core.logger import get_logger

logger = get_logger("migrations")

ROOT = Path(__file__).resolve().parent.parent
BASELINE_REVISION = "0001_baseline"

# Columns that older versions of the app added by hand. Only used to bring a pre-Alembic
# database up to the baseline schema; never extend this list, write a migration instead.
LEGACY_COLUMNS = {
    "bots": {
        "webhook_url": "ALTER TABLE bots ADD COLUMN webhook_url VARCHAR(500)",
        "webhook_set": "ALTER TABLE bots ADD COLUMN webhook_set BOOLEAN DEFAULT FALSE",
        "username": "ALTER TABLE bots ADD COLUMN username VARCHAR(255)",
        "onboarding_completed": "ALTER TABLE bots ADD COLUMN onboarding_completed BOOLEAN DEFAULT FALSE",
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


def make_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _bring_legacy_schema_to_baseline(connection: Connection) -> None:
    """Make an existing pre-Alembic database match the baseline schema (and nothing newer).

    Columns that older app versions added by hand are added first; then the baseline
    migration runs. It is idempotent, so it only creates tables/indexes that are missing.
    Later migrations then apply on top like on any other database.
    """
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table, columns in LEGACY_COLUMNS.items():
        if table not in existing_tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, statement in columns.items():
            if name not in existing:
                connection.execute(text(statement))


def _upgrade(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    config = make_config(connection)
    if "alembic_version" not in tables and "bots" in tables:
        logger.info("Existing database without Alembic history: adopting it as %s", BASELINE_REVISION)
        _bring_legacy_schema_to_baseline(connection)
        command.upgrade(config, BASELINE_REVISION)
    command.upgrade(config, "head")


async def upgrade_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
    logger.info("Database schema is up to date")
