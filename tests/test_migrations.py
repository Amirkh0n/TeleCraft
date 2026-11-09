import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from core.migrations import BASELINE_REVISION, make_config, upgrade_database
from models.base import Base

import models  # noqa: F401

TABLES = set(Base.metadata.tables)


@pytest.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    yield eng
    await eng.dispose()


async def _tables(eng):
    async with eng.connect() as conn:
        return await conn.run_sync(lambda c: set(inspect(c).get_table_names()))


async def _version(eng):
    async with eng.connect() as conn:
        return (await conn.execute(text("select version_num from alembic_version"))).scalar()


def test_single_head_and_baseline_present():
    script = ScriptDirectory.from_config(make_config())
    assert script.get_heads() == [script.get_current_head()]  # no branching
    assert script.get_revision(BASELINE_REVISION) is not None


async def test_fresh_database_gets_every_table(engine):
    await upgrade_database(engine)
    assert TABLES <= await _tables(engine)
    assert await _version(engine) == ScriptDirectory.from_config(make_config()).get_current_head()


async def test_upgrade_is_idempotent(engine):
    await upgrade_database(engine)
    await upgrade_database(engine)
    assert TABLES <= await _tables(engine)


async def test_models_and_migrations_do_not_drift(engine):
    """Fails when a model changes but no migration was written."""
    await upgrade_database(engine)

    def diff(conn):
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == [], "Model changed: run `alembic revision --autogenerate`"


async def test_existing_pre_alembic_database_is_adopted_not_recreated(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # what the app did before Alembic
        await conn.execute(text("insert into users (tg_id, full_name) values (1, 'Owner')"))

    await upgrade_database(engine)

    assert await _version(engine) == ScriptDirectory.from_config(make_config()).get_current_head()
    async with engine.connect() as conn:
        assert (await conn.execute(text("select count(*) from users"))).scalar() == 1  # data kept


async def test_old_schema_missing_columns_is_repaired_and_keeps_data(engine):
    async with engine.begin() as conn:
        for statement in (
            "create table users (id integer primary key, tg_id bigint not null, full_name varchar(255))",
            "create table bots (id integer primary key, owner_id integer not null, name varchar(255) not null,"
            " token varchar(255) not null unique, is_active boolean default 1)",
            "create table menus (id integer primary key, bot_id integer not null, title varchar(255) not null,"
            " is_start boolean default 0)",
            "create table user_sessions (id integer primary key, bot_id integer not null,"
            " tg_user_id bigint not null, current_menu_id integer not null)",
            "insert into users (tg_id, full_name) values (1, 'Owner')",
            "insert into bots (owner_id, name, token) values (1, 'old bot', '123:abc')",
        ):
            await conn.execute(text(statement))

    await upgrade_database(engine)

    async with engine.connect() as conn:
        bot_columns = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("bots")})
        menu_columns = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("menus")})
        assert {"username", "webhook_url", "webhook_set", "onboarding_completed", "token_hash"} <= bot_columns
        assert {"message_text", "position"} <= menu_columns
        assert (await conn.execute(text("select name from bots"))).scalar() == "old bot"
    assert TABLES <= await _tables(engine)
