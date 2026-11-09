from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import webhook.handler as handler
from core.config import settings
from core.security import token_hash, webhook_secret
from models.base import Base
from models.bots import Bot
from models.users import User

TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789"
HEADER = "X-Telegram-Bot-Api-Secret-Token"


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = User(tg_id=1, full_name="Owner")
        session.add(user)
        await session.flush()
        session.add(Bot(owner_id=user.id, name="child", token=TOKEN, is_active=True))
        await session.commit()

    monkeypatch.setattr(handler, "AsyncSessionLocal", maker)
    monkeypatch.setattr(settings, "WEBHOOK_SECRET_ENFORCE", False)
    app = FastAPI()
    app.include_router(handler.router)
    with TestClient(app) as test_client:
        yield test_client
    await engine.dispose()


@pytest.fixture
def route_update():
    with patch.object(handler, "route_update", new=AsyncMock()) as mocked:
        yield mocked


def url():
    return f"/h/{token_hash(TOKEN)}"


def test_token_is_stored_encrypted():
    bot = Bot(owner_id=1, name="x", token=TOKEN)
    assert bot.token.startswith("enc:") and TOKEN not in bot.token
    assert bot.plain_token == TOKEN
    assert bot.token_hash == token_hash(TOKEN)


def test_valid_secret_is_processed(client, route_update):
    r = client.post(url(), json={"update_id": 1}, headers={HEADER: webhook_secret(TOKEN)})
    assert r.status_code == 200
    route_update.assert_awaited_once()


def test_wrong_secret_is_rejected(client, route_update):
    r = client.post(url(), json={"update_id": 1}, headers={HEADER: "wrong"})
    assert r.status_code == 403
    route_update.assert_not_awaited()


def test_missing_secret_allowed_until_enforced(client, route_update, monkeypatch):
    assert client.post(url(), json={"update_id": 1}).status_code == 200
    monkeypatch.setattr(settings, "WEBHOOK_SECRET_ENFORCE", True)
    assert client.post(url(), json={"update_id": 1}).status_code == 403


def test_unknown_bot_returns_404(client, route_update):
    assert client.post("/h/unknown", json={"update_id": 1}).status_code == 404
    route_update.assert_not_awaited()


def test_legacy_token_url_still_works(client, route_update):
    assert client.post(f"/webhooks/{TOKEN}", json={"update_id": 1}).status_code == 200
    route_update.assert_awaited_once()


def test_token_lookup_never_sends_plain_token_to_database():
    compiled = Bot.token_matches(TOKEN).compile()
    assert TOKEN not in str(compiled)
    assert TOKEN not in [str(value) for value in compiled.params.values()]
    assert token_hash(TOKEN) in compiled.params.values()
