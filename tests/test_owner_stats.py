"""Owner statistics: click log, growth, top buttons, plan cap."""
import datetime as dt
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from engine import clicks, owner_stats
from helpers import USER, add_button, add_menu, message, send, tap
from models.analytics import AnalyticsEvent
from models.audience import BotUser, Broadcast
from models.button_actions import ActionType
from test_home import henv  # noqa: F401
from test_webapp_api import sign
from webapp import api as webapp_api
from webapp.auth import get_session


async def clicks_of(env):
    return (await env.session.execute(select(AnalyticsEvent).where(AnalyticsEvent.event_type == "click"))).scalars().all()


async def test_inline_and_reply_clicks_are_logged_once_each(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    inline = await add_button(env, menu, "Narxlar", ActionType.text, "10")
    await send(env, tap(inline))
    await send(env, tap(inline))
    rows = await clicks_of(env)
    assert [(r.bot_id, r.user_id, r.button_id) for r in rows] == [(env.bot.id, USER, inline.id)] * 2
    reply = await add_menu(env, "R", "Pastki", mode="reply")
    key = await add_button(env, reply, "Aloqa", ActionType.text, "tel")
    from models.user_sessions import UserSession
    env.session.add(UserSession(bot_id=env.bot.id, tg_user_id=USER, current_menu_id=reply.id))
    await env.session.commit()
    await send(env, message("Aloqa"))
    assert len(await clicks_of(env)) == 3 and (await clicks_of(env))[-1].button_id == key.id


async def test_a_foreign_or_missing_button_is_not_logged_and_errors_do_not_break(env, monkeypatch):
    await send(env, {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "A"}, "data": "99999"}})
    assert await clicks_of(env) == []
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "X", ActionType.text, "ok")

    async def boom(*a, **k):
        raise RuntimeError("db")
    monkeypatch.setattr(env.session, "commit", boom, raising=False)
    await clicks.record(env.session, env.bot.id, USER, button.id)  # swallowed


async def test_old_clicks_are_pruned(env, monkeypatch):
    old = AnalyticsEvent(bot_id=env.bot.id, event_type="click", user_id=1, button_id=1, created_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=clicks.KEEP_DAYS + 5))
    env.session.add(old)
    await env.session.commit()
    monkeypatch.setattr(clicks, "_last_prune", None)
    await clicks.record(env.session, env.bot.id, 2, 1)
    left = await clicks_of(env)
    assert len(left) == 1 and left[0].user_id == 2


async def test_overview_growth_top_buttons_and_cap(env):
    now = dt.datetime.now(dt.UTC)
    for i, days in enumerate([0, 0, 1, 3, 40]):
        env.session.add(BotUser(bot_id=env.bot.id, tg_user_id=100 + i, first_seen_at=now - dt.timedelta(days=days), last_seen_at=now))
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    a = await add_button(env, menu, "Menyu", ActionType.text, "m")
    b = await add_button(env, menu, "Aloqa", ActionType.text, "a", position=1)
    for button, n in ((a, 3), (b, 1)):
        for u in range(n):
            env.session.add(AnalyticsEvent(bot_id=env.bot.id, event_type="click", user_id=u, button_id=button.id))
    env.session.add(Broadcast(bot_id=env.bot.id, created_by=1, text="x", status="done", total=5, sent=4, failed=1))
    await env.session.commit()
    data = await owner_stats.overview(env.session, env.bot, SimpleNamespace(user_cap=20, plan="free"), now=now)
    assert data["total"] == 5 and len(data["daily"]) == owner_stats.DAYS
    assert [d["new"] for d in data["daily"]][-1] == 2 and data["daily"][-2]["new"] == 1 and data["daily"][-4]["new"] == 1 and sum(d["new"] for d in data["daily"]) == 4
    assert data["top_buttons"] == [{"text": "Menyu", "clicks": 3}, {"text": "Aloqa", "clicks": 1}]
    assert data["clicks_7d"] == 4 and data["clickers_7d"] == 3
    assert data["broadcasts"][0]["sent"] == 4 and data["cap"] == {"limit": 20, "used": 5, "plan": "free"}
    unlimited = await owner_stats.overview(env.session, env.bot, SimpleNamespace(user_cap=None, plan="pro"), now=now)
    assert unlimited["cap"] is None


def test_spark():
    assert owner_stats.spark([0, 0, 0]) == "▁▁▁" and owner_stats.spark([]) == ""
    line = owner_stats.spark([0, 1, 4, 8])
    assert len(line) == 4 and line[0] == "▁" and line[-1] == "█" and line[1] <= line[2]


async def test_stats_endpoint_has_the_new_sections(env):
    app = FastAPI()
    app.include_router(webapp_api.router)

    async def override():
        yield env.session
    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        data = (await c.get(f"/api/v1/bots/{env.bot.id}/stats", headers={"Authorization": f"tma {sign()}"})).json()
    assert data["total"] == 0 and len(data["daily"]) == 14 and data["top_buttons"] == [] and data["broadcasts"] == [] and "clicks_7d" in data and "sources" in data


async def test_bot_statistics_screen_shows_numbers_top_buttons_and_limit_warning(henv):
    from constructor import handlers
    from helpers import OWNER
    from test_home import Query, buttons, make_msg, upd
    henv.ctx.user_data["current_bot_id"] = henv.bot.id
    now = dt.datetime.now(dt.UTC)
    for i in range(18):
        henv.session.add(BotUser(bot_id=henv.bot.id, tg_user_id=500 + i, first_seen_at=now, last_seen_at=now))
    menu = await add_menu(henv, "Bosh", "Salom", start=True)
    button = await add_button(henv, menu, "Menyu", ActionType.text, "m")
    henv.session.add(AnalyticsEvent(bot_id=henv.bot.id, event_type="click", user_id=1, button_id=button.id))
    await henv.session.commit()
    page = make_msg()
    await handlers.show_bot_status(upd(OWNER, query=Query("bot_status", page)), henv.ctx)
    text, kw = page.edits[-1]
    assert "<b>18</b> / 20" in text and "Menyu — 1" in text and "Limit 20" in text
    assert "plx:home" in [b.callback_data for b in buttons(kw["reply_markup"])]
