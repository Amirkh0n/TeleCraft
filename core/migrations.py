"""Schema management on application start.

* New database: ``alembic upgrade head`` builds everything from the migration files.
* Database that already exists but was created before Alembic (``create_all`` + the old
  "light migrations"): missing columns/tables are added once, the schema is stamped as the
  baseline revision, and from then on only Alembic changes it.
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
from models.base import Base

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
    Base.metadata.create_all(connection)  # creates only tables that are missing
    inspector = inspect(connection)
    for table, columns in LEGACY_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, statement in columns.items():
            if name not in existing:
                connection.execute(text(statement))
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_bots_token_hash ON bots (token_hash)"))


def _upgrade(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    config = make_config(connection)
    if "alembic_version" not in tables and "bots" in tables:
        logger.info("Existing database without Alembic history: adopting it as %s", BASELINE_REVISION)
        _bring_legacy_schema_to_baseline(connection)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")


async def upgrade_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
    logger.info("Database schema is up to date")
