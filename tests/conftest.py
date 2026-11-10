import os

# Must be set before any application module is imported.
os.environ.setdefault("TELEGRAM_TOKEN", "111111:test_constructor_token_not_real_xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key")


import pytest  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from core.migrations import upgrade_database  # noqa: E402
from helpers import FakeTG, OWNER, TOKEN  # noqa: E402
from engine import router  # noqa: E402
from models.bots import Bot  # noqa: E402
from models.users import User  # noqa: E402


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'engine.db'}")
    await upgrade_database(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    router._seen.clear()
    tg = FakeTG()

    async def fake_constructor_client(token):  # notifications fall back to the constructor bot
        return tg

    monkeypatch.setattr("engine.telegram_client.get_client", fake_constructor_client)

    async with maker() as session:
        owner = User(tg_id=OWNER, full_name="Owner")
        session.add(owner)
        await session.flush()
        bot = Bot(owner_id=owner.id, name="Shop", token=TOKEN)
        session.add(bot)
        await session.flush()
        await session.commit()
    async with maker() as session:
        bot = (await session.execute(select(Bot))).scalar_one()
        yield SimpleNamespace(maker=maker, tg=tg, bot=bot, session=session)
    await engine.dispose()
