"""Child bot languages: the owner translates texts, the customer picks a language."""
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from helpers import USER, add_button, add_menu, message, send, tap
from models.audience import BotUser
from models.button_actions import ActionType
from models.translations import ContentTranslation
from test_webapp_api import sign
from webapp import api_langs, api as webapp_api
from webapp.auth import get_session


@pytest.fixture
async def ac(env):
    app = FastAPI()
    app.include_router(webapp_api.router)
    app.include_router(api_langs.router)

    async def override():
        yield env.session

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.hdr = {"Authorization": f"tma {sign()}"}
        yield c


async def shop(env):
    start = await add_menu(env, "Bosh", "Salom!", start=True)
    price = await add_button(env, start, "Narxlar", ActionType.text, "100 so‘m", position=0)
    sub = await add_menu(env, "Aloqa", "Aloqa bo‘limi")
    go = await add_button(env, start, "Aloqa", ActionType.menu, str(sub.id), position=1)
    return SimpleNs(start=start.id, price=price.id, sub=sub.id, go=go)


class SimpleNs:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def put(ac, env, items):
    r = await ac.put(f"/api/v1/bots/{env.bot.id}/translations", json={"items": items}, headers=ac.hdr)
    assert r.status_code == 200, r.text
    return r.json()


async def enable(ac, env, langs=("ru",)):
    r = await ac.put(f"/api/v1/bots/{env.bot.id}/languages", json={"languages": list(langs)}, headers=ac.hdr)
    assert r.status_code == 200, r.text
    await env.session.refresh(env.bot)


async def test_single_language_bot_is_unchanged(env):
    ids = await shop(env)
    await send(env, message("/start"))
    assert env.tg.texts()[-1] == "Salom!"
    assert not any("Tilni" in t for t in env.tg.texts())


async def test_start_asks_language_then_shows_translated_screen(ac, env):
    ids = await shop(env)
    await enable(ac, env)
    await put(ac, env, [
        {"entity": "menu_text", "entity_id": ids.start, "lang": "ru", "text": "Привет!"},
        {"entity": "button_text", "entity_id": ids.price, "lang": "ru", "text": "Цены"},
        {"entity": "action_text", "entity_id": ids.price, "lang": "ru", "text": "100 сум"},
    ])
    await send(env, message("/start"))
    picker = env.tg.last()
    labels = [b.text for row in picker["reply_markup"].inline_keyboard for b in row]
    assert labels == ["🇺🇿 O‘zbekcha", "🇷🇺 Русский"]

    ru = picker["reply_markup"].inline_keyboard[1][0]
    env.tg.calls.clear()
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": ru.callback_data}})
    screen = env.tg.last()
    assert screen["text"] == "Привет!"
    keys = [b.text for row in screen["reply_markup"].inline_keyboard for b in row]
    assert keys == ["Цены", "Aloqa", "🌐"]  # untranslated button falls back to the base text

    env.tg.calls.clear()
    from types import SimpleNamespace
    await send(env, tap(SimpleNamespace(id=ids.price)))
    assert env.tg.texts()[-1] == "100 сум"

    # /start no longer asks again
    env.tg.calls.clear()
    await send(env, message("/start"))
    assert env.tg.last()["text"] == "Привет!"


async def test_uzbek_choice_and_language_command(ac, env):
    ids = await shop(env)
    await enable(ac, env)
    await put(ac, env, [{"entity": "menu_text", "entity_id": ids.start, "lang": "ru", "text": "Привет!"}])
    await send(env, message("/start"))
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "lang:uz"}})
    assert env.tg.last()["text"] == "Salom!"
    await send(env, message("/language"))
    assert "reply_markup" in env.tg.last() and "Tilni" in env.tg.last()["text"]
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "lang:pick"}})
    assert "Tilni" in env.tg.last()["text"]
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "lang:ru"}})
    assert env.tg.last()["text"] == "Привет!"
    # a language the bot does not offer is ignored
    env.tg.calls.clear()
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "lang:en"}})
    user = (await env.session.execute(select(BotUser))).scalar_one()
    assert user.lang == "ru"


async def test_reply_keyboard_matches_translated_label(ac, env):
    start = await add_menu(env, "Bosh", "Salom", start=True, mode="reply")
    btn = await add_button(env, start, "Narxlar", ActionType.text, "100 so‘m")
    await enable(ac, env)
    await put(ac, env, [
        {"entity": "button_text", "entity_id": btn.id, "lang": "ru", "text": "Цены"},
        {"entity": "action_text", "entity_id": btn.id, "lang": "ru", "text": "100 сум"},
    ])
    await send(env, message("/start"))
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "lang:ru"}})
    kb = env.tg.last()["reply_markup"].keyboard
    assert kb[0][0].text == "Цены"
    await send(env, message("Цены"))
    assert env.tg.texts()[-1] == "100 сум"


async def test_api_validation_and_cleanup(ac, env):
    ids = await shop(env)
    r = await ac.put(f"/api/v1/bots/{env.bot.id}/translations", headers=ac.hdr,
                     json={"items": [{"entity": "menu_text", "entity_id": ids.start, "lang": "ru", "text": "x"}]})
    assert r.status_code == 422  # language not enabled
    await enable(ac, env, ("ru", "en"))
    bad = await ac.put(f"/api/v1/bots/{env.bot.id}/translations", headers=ac.hdr,
                       json={"items": [{"entity": "menu_text", "entity_id": 99999, "lang": "ru", "text": "x"}]})
    assert bad.status_code == 404
    broken = await ac.put(f"/api/v1/bots/{env.bot.id}/translations", headers=ac.hdr,
                          json={"items": [{"entity": "menu_text", "entity_id": ids.start, "lang": "ru", "text": "<b>x"}]})
    assert broken.status_code == 422

    data = await put(ac, env, [{"entity": "button_text", "entity_id": ids.price, "lang": "en", "text": "Prices"}])
    start = next(m for m in data["menus"] if m["id"] == ids.start)
    assert start["buttons"][0]["tr"] == {"en": "Prices"} and start["buttons"][0]["action_text"] == "100 so‘m"
    # empty text deletes
    data = await put(ac, env, [{"entity": "button_text", "entity_id": ids.price, "lang": "en", "text": ""}])
    assert next(m for m in data["menus"] if m["id"] == ids.start)["buttons"][0]["tr"] == {}
    # deleting a button removes its translations
    await put(ac, env, [{"entity": "action_text", "entity_id": ids.price, "lang": "ru", "text": "100"}])
    assert (await ac.delete(f"/api/v1/buttons/{ids.price}", headers=ac.hdr)).status_code == 204
    left = (await env.session.execute(select(ContentTranslation))).scalars().all()
    assert left == []


async def test_other_owner_cannot_touch(ac, env):
    await shop(env)
    foreign = {"Authorization": f"tma {sign(4242)}"}
    r = await ac.get(f"/api/v1/bots/{env.bot.id}/translations", headers=foreign)
    assert r.status_code == 404
