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
    """The production (Neon) case: baseline-shaped tables with data, but no alembic_version."""
    await _upgrade_to(engine, BASELINE_REVISION)
    async with engine.begin() as conn:
        await conn.execute(text("drop table alembic_version"))
        await conn.execute(text("insert into users (tg_id, full_name) values (1, 'Owner')"))

    await upgrade_database(engine)

    assert await _version(engine) == ScriptDirectory.from_config(make_config()).get_current_head()
    assert TABLES <= await _tables(engine)
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


async def _upgrade_to(engine, revision):
    from alembic import command

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.upgrade(make_config(c), revision))


async def test_0002_keeps_existing_rows_and_fills_defaults(engine):
    await _upgrade_to(engine, BASELINE_REVISION)
    async with engine.begin() as conn:
        for statement in (
            "insert into users (id, tg_id, full_name) values (1, 1, 'Owner')",
            "insert into bots (id, owner_id, name, token, is_active, webhook_set, onboarding_completed)"
            " values (1, 1, 'b', 'enc:x', 1, 0, 1)",
            "insert into menus (id, bot_id, title, message_text, is_start, position) values (1, 1, 'Bosh', 'Salom', 1, 0)",
            "insert into buttons (id, menu_id, text, position) values (1, 1, 'Narxlar', 0)",
            "insert into user_sessions (bot_id, tg_user_id, current_menu_id) values (1, 555, 1)",
        ):
            await conn.execute(text(statement))

    await upgrade_database(engine)

    async with engine.connect() as conn:
        row = (await conn.execute(text("select message_text, keyboard_mode, columns, media_type from menus"))).one()
        assert tuple(row) == ("Salom", "inline", 1, None)
        assert (await conn.execute(text("select kind from buttons"))).scalar() == "normal"
        session_row = (await conn.execute(text("select reply_keyboard_active, form_id from user_sessions"))).one()
        assert not session_row[0] and session_row[1] is None


async def test_new_tables_and_action_types_work_through_the_orm(engine):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from models.bots import Bot
    from models.button_actions import ActionType, ButtonAction
    from models.buttons import Button
    from models.forms import Form, FormField, FormSubmission
    from models.menus import Menu
    from models.users import User

    await upgrade_database(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = User(tg_id=1, full_name="Owner")
        session.add(user)
        await session.flush()
        bot = Bot(owner_id=user.id, name="b", token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789")
        session.add(bot)
        await session.flush()
        menu = Menu(bot_id=bot.id, title="Bosh", is_start=True, media_type="photo", media_file_id="AgAC", keyboard_mode="reply", columns=2)
        form = Form(bot_id=bot.id, title="Ariza", fields=[FormField(position=0, label="Ism", prompt="Ismingiz?")])
        session.add_all([menu, form])
        await session.flush()
        button = Button(menu_id=menu.id, text="Ariza", kind="normal")
        session.add(button)
        await session.flush()
        session.add(ButtonAction(button_id=button.id, action_type=ActionType.form, value=str(form.id)))
        session.add(FormSubmission(form_id=form.id, bot_id=bot.id, tg_user_id=9, answers=[{"label": "Ism", "value": "Ali"}]))
        await session.commit()

    async with maker() as session:
        action = (await session.execute(select(ButtonAction))).scalar_one()
        assert action.action_type is ActionType.form
        submission = (await session.execute(select(FormSubmission))).scalar_one()
        assert submission.answers[0]["value"] == "Ali" and submission.created_at is not None  # server default


async def test_downgrade_to_baseline_and_back(engine):
    from alembic import command

    await upgrade_database(engine)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(make_config(c), BASELINE_REVISION))
    assert "forms" not in await _tables(engine)
    await upgrade_database(engine)
    assert "forms" in await _tables(engine)
