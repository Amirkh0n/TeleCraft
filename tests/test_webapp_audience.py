"""Mini App API: broadcasts and required channels."""
from types import SimpleNamespace

from sqlalchemy import select

from engine import broadcast as bc
from helpers import OWNER
from models.audience import BotUser, RequiredChannel
from test_webapp_api import client, fake_child, sign  # noqa: F401  (fixtures)
from webapp import api_audience


async def users(env, n=2):
    for i in range(n):
        env.session.add(BotUser(bot_id=env.bot.id, tg_user_id=500 + i))
    await env.session.commit()


async def test_broadcast_lifecycle(client):  # noqa: F811
    env = client.env
    await users(env)
    base = f"/api/v1/bots/{env.bot.id}/broadcasts"
    created = await client.post(base, json={"text": "<b>Aksiya</b>", "button_text": "Ochish", "button_url": "https://a.uz"}, headers=client.hdr)
    assert created.status_code == 201 and created.json()["audience"] == 2 and created.json()["status"] == "draft"
    bid = created.json()["id"]

    edited = await client.patch(f"/api/v1/broadcasts/{bid}", json={"text": "Yangi"}, headers=client.hdr)
    assert edited.json()["text"] == "Yangi" and edited.json()["button_text"] == "Ochish"
    assert (await client.patch(f"/api/v1/broadcasts/{bid}", json={"text": "<b>x"}, headers=client.hdr)).status_code == 422
    assert (await client.patch(f"/api/v1/broadcasts/{bid}", json={"button_text": "Faqat yozuv"}, headers=client.hdr)).status_code == 422
    assert (await client.patch(f"/api/v1/broadcasts/{bid}", json={"button_text": "x", "button_url": "ftp://a"}, headers=client.hdr)).status_code == 422
    cleared = await client.patch(f"/api/v1/broadcasts/{bid}", json={"button_text": "", "button_url": ""}, headers=client.hdr)
    assert cleared.json()["button_text"] is None

    # sending: run the task body inline instead of in the background
    sent = await client.post(f"/api/v1/broadcasts/{bid}/send", headers=client.hdr)
    assert sent.status_code == 200 and sent.json()["status"] == "sending" and sent.json()["total"] == 2
    bc._tasks.clear()
    again = await client.post(f"/api/v1/broadcasts/{bid}/send", headers=client.hdr)
    assert again.status_code == 409
    assert (await client.patch(f"/api/v1/broadcasts/{bid}", json={"text": "late"}, headers=client.hdr)).status_code == 409

    cancelled = await client.post(f"/api/v1/broadcasts/{bid}/cancel", headers=client.hdr)
    assert cancelled.json()["status"] == "cancelled"
    listing = (await client.get(base, headers=client.hdr)).json()
    assert listing["items"][0]["id"] == bid and listing["audience"] == 2


async def test_send_needs_audience_and_content(client):  # noqa: F811
    env = client.env
    empty = (await client.post(f"/api/v1/bots/{env.bot.id}/broadcasts", json={}, headers=client.hdr)).json()
    assert (await client.post(f"/api/v1/broadcasts/{empty['id']}/send", headers=client.hdr)).status_code == 409  # nobody yet
    await users(env, 1)
    assert (await client.post(f"/api/v1/broadcasts/{empty['id']}/send", headers=client.hdr)).status_code == 409  # no content


async def test_broadcast_media_and_preview(client, monkeypatch):  # noqa: F811
    env = client.env
    fake_child(env, monkeypatch)
    sent = []

    class Child:
        async def send_message(self, **kw):
            sent.append(kw)
            return SimpleNamespace(message_id=1)

    async def get_client(token):
        return Child()

    monkeypatch.setattr(api_audience, "get_client", get_client)
    b = (await client.post(f"/api/v1/bots/{env.bot.id}/broadcasts", json={"text": "Salom"}, headers=client.hdr)).json()
    assert (await client.post(f"/api/v1/broadcasts/{b['id']}/preview", headers=client.hdr)).status_code == 204
    assert sent[0]["chat_id"] == OWNER and sent[0]["text"] == "Salom"

    up = await client.post(f"/api/v1/broadcasts/{b['id']}/media", headers=client.hdr, files={"file": ("a.png", b"png" * 10, "image/png")})
    assert up.json()["media_type"] == "photo" and "child-photo" not in up.text
    assert (await client.delete(f"/api/v1/broadcasts/{b['id']}/media", headers=client.hdr)).json()["media_type"] is None


async def test_preview_without_content_or_started_chat(client, monkeypatch):  # noqa: F811
    from telegram.error import Forbidden
    env = client.env
    empty = (await client.post(f"/api/v1/bots/{env.bot.id}/broadcasts", json={}, headers=client.hdr)).json()

    class Child:
        async def send_message(self, **kw):
            raise Forbidden("blocked")

    async def get_client(token):
        return Child()

    monkeypatch.setattr(api_audience, "get_client", get_client)
    assert (await client.post(f"/api/v1/broadcasts/{empty['id']}/preview", headers=client.hdr)).status_code == 422
    filled = (await client.post(f"/api/v1/bots/{env.bot.id}/broadcasts", json={"text": "x"}, headers=client.hdr)).json()
    blocked = await client.post(f"/api/v1/broadcasts/{filled['id']}/preview", headers=client.hdr)
    assert blocked.status_code == 409 and "/start" in blocked.json()["detail"]


async def test_other_users_cannot_touch_broadcasts_or_channels(client):  # noqa: F811
    env = client.env
    b = (await client.post(f"/api/v1/bots/{env.bot.id}/broadcasts", json={"text": "x"}, headers=client.hdr)).json()
    env.session.add(RequiredChannel(bot_id=env.bot.id, chat_id=-100, title="K", username="k"))
    await env.session.commit()
    channel = (await env.session.execute(select(RequiredChannel))).scalar_one()
    stranger = {"Authorization": f"tma {sign(999)}"}
    for method, url in (("get", f"/api/v1/bots/{env.bot.id}/broadcasts"), ("get", f"/api/v1/broadcasts/{b['id']}"),
                        ("post", f"/api/v1/broadcasts/{b['id']}/send"), ("post", f"/api/v1/broadcasts/{b['id']}/cancel"),
                        ("post", f"/api/v1/broadcasts/{b['id']}/preview"), ("delete", f"/api/v1/broadcasts/{b['id']}/media"),
                        ("get", f"/api/v1/bots/{env.bot.id}/channels"), ("delete", f"/api/v1/channels/{channel.id}")):
        assert (await getattr(client, method)(url, headers=stranger)).status_code == 404, url
    assert (await client.get(f"/api/v1/bots/{env.bot.id}/channels", headers=client.hdr)).json()[0]["title"] == "K"


def fake_channels(monkeypatch, *, problem=None, username="news", chat_id=-1001):
    async def describe(tg, ref):
        return (None, None, None, problem) if problem else (chat_id, "Yangiliklar", username, None)

    async def get_client(token):
        return object()

    monkeypatch.setattr(api_audience.subscription, "describe_channel", describe)
    monkeypatch.setattr(api_audience, "get_client", get_client)


async def test_add_channel_checks_admin_and_duplicates(client, monkeypatch):  # noqa: F811
    env = client.env
    url = f"/api/v1/bots/{env.bot.id}/channels"
    fake_channels(monkeypatch, problem="Bot bu kanalda administrator emas.")
    bad = await client.post(url, json={"ref": "@news"}, headers=client.hdr)
    assert bad.status_code == 422 and "administrator" in bad.json()["detail"]
    assert (await client.post(url, json={"ref": "nonsense"}, headers=client.hdr)).status_code == 422

    fake_channels(monkeypatch)
    ok = await client.post(url, json={"ref": "https://t.me/news"}, headers=client.hdr)
    assert ok.status_code == 201 and ok.json()["username"] == "news"
    assert (await client.post(url, json={"ref": "@news"}, headers=client.hdr)).status_code == 409
    assert (await client.delete(f"/api/v1/channels/{ok.json()['id']}", headers=client.hdr)).status_code == 204
    assert (await client.get(url, headers=client.hdr)).json() == []


async def test_private_channel_needs_invite_link(client, monkeypatch):  # noqa: F811
    env = client.env
    url = f"/api/v1/bots/{env.bot.id}/channels"
    fake_channels(monkeypatch, username=None)
    assert (await client.post(url, json={"ref": "-1001234567"}, headers=client.hdr)).status_code == 422
    assert (await client.post(url, json={"ref": "-1001234567", "invite_link": "https://evil.com/x"}, headers=client.hdr)).status_code == 422
    ok = await client.post(url, json={"ref": "-1001234567", "invite_link": "https://t.me/+AbC123"}, headers=client.hdr)
    assert ok.status_code == 201 and ok.json()["private"] is True
    stored = (await env.session.execute(select(RequiredChannel))).scalar_one()
    assert stored.invite_link == "https://t.me/+AbC123"


async def test_channel_limit(client, monkeypatch):  # noqa: F811
    env = client.env
    for i in range(api_audience.MAX_CHANNELS):
        env.session.add(RequiredChannel(bot_id=env.bot.id, chat_id=-i - 1, title="K", username="k"))
    await env.session.commit()
    fake_channels(monkeypatch)
    assert (await client.post(f"/api/v1/bots/{env.bot.id}/channels", json={"ref": "@news"}, headers=client.hdr)).status_code == 409
