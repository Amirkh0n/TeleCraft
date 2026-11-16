"""Main bot home menu, gallery of ready-made bots, and paying for a bot in another mode."""
import datetime as dt
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from constructor.flows import home, plans as flow
from constructor import handlers
from core import plans
from core.config import settings
from helpers import FakeTG, OWNER
from models.plans import AccountPlan
from models.users import User
from test_constructor_plans import Msg, Query, make_msg, upd  # noqa: F401
from webapp import api_modes

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def henv(env, monkeypatch):
    monkeypatch.setattr(settings, "PLANS_ENFORCE", True)
    monkeypatch.setattr(settings, "ADMIN_IDS", "")
    for name, module in list(sys.modules.items()):
        if name.startswith("constructor") and hasattr(module, "AsyncSessionLocal"):
            monkeypatch.setattr(module, "AsyncSessionLocal", env.maker)
    plans.invalidate()
    env.ctx = SimpleNamespace(user_data={}, bot=FakeTG(), args=[])
    return env


def buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def data_of(markup):
    return [b.callback_data for b in buttons(markup) if b.callback_data]


async def give(env, plan):
    user = await env.session.get(User, env.bot.owner_id)
    env.session.add(AccountPlan(user_id=user.id, plan=plan, expires_at=NOW + dt.timedelta(days=20)))
    await env.session.commit()
    plans.invalidate()


async def test_start_opens_the_home_menu_not_the_last_bot(henv):
    ctx = henv.ctx
    ctx.user_data["current_bot_id"] = henv.bot.id
    msg = make_msg()
    await handlers.start(upd(OWNER, message=msg), ctx)
    text, kw = msg.replies[-1]
    data = data_of(kw["reply_markup"])
    assert "TeleCraft" in text and "Botlaringiz: <b>1</b>" in text and "Free" in text
    assert {"back_to_bots", "add_bot", "gal:home", "plx:home", "help"} <= set(data)
    assert f"bot_{henv.bot.id}" in data  # "continue" is a button, not an automatic jump


async def test_home_callback_and_no_last_bot(henv):
    page = make_msg()
    await home.show_home(upd(OWNER, query=Query("home", page)), henv.ctx)
    text, kw = page.edits[-1]
    assert "Davom etish" not in str(kw["reply_markup"].inline_keyboard)


async def test_gallery_marks_locked_modes_per_plan(henv):
    page = make_msg()
    await home.gallery_home(upd(OWNER, query=Query("gal:home", page)), henv.ctx)
    rows = {b.callback_data: b.text for b in buttons(page.edits[-1][1]["reply_markup"])}
    assert rows["gal:k:shop"].startswith("🔒") and rows["gal:k:cinema"].startswith("🎬") and "50 000" in rows["gal:k:shop"]
    await give(henv, "pro")
    page = make_msg()
    await home.gallery_home(upd(OWNER, query=Query("gal:home", page)), henv.ctx)
    assert all(not b.text.startswith("🔒") for b in buttons(page.edits[-1][1]["reply_markup"]))


async def test_gallery_card_offers_create_or_pay(henv):
    page = make_msg()
    await home.gallery_kind(upd(OWNER, query=Query("gal:k:shop", page)), henv.ctx)
    text, kw = page.edits[-1]
    assert "Do‘kon bot" in text and "yopadi" in text or "ochmaydi" in text
    assert {"plx:home", "gal:pay:shop"} <= set(data_of(kw["reply_markup"])) and "gal:new:shop" not in data_of(kw["reply_markup"])
    page = make_msg()
    await home.gallery_kind(upd(OWNER, query=Query("gal:k:cinema", page)), henv.ctx)
    data = data_of(page.edits[-1][1]["reply_markup"])
    assert {"gal:new:cinema", "gal:use:cinema"} <= set(data)


async def test_switching_an_existing_bot_from_the_gallery(henv):
    ctx = henv.ctx
    page = make_msg()
    await home.gallery_set(upd(OWNER, query=Query(f"gal:set:cinema:{henv.bot.id}", page)), ctx)
    await henv.session.refresh(henv.bot)
    assert henv.bot.kind == "cinema"
    locked_page = make_msg()  # Free plan: the shop mode is refused with a way to pay for this bot only
    await home.gallery_set(upd(OWNER, query=Query(f"gal:set:shop:{henv.bot.id}", locked_page)), ctx)
    assert f"plx:bk:{henv.bot.id}:shop" in data_of(locked_page.edits[-1][1]["reply_markup"])
    await henv.session.refresh(henv.bot)
    assert henv.bot.kind == "cinema"


async def test_creating_from_the_gallery_asks_for_a_token_and_remembers_the_mode(henv):
    ctx = henv.ctx
    await give(henv, "business")
    page = make_msg()
    await home.gallery_new(upd(OWNER, query=Query("gal:new:course", page)), ctx)
    assert ctx.user_data["draft"] == {"flow": "create_bot", "kind": "course"} and ctx.user_data["state"] == "waiting_for_token"
    msg = make_msg()
    await handlers.start(upd(OWNER, message=msg), SimpleNamespace(user_data={}, bot=FakeTG(), args=["new_shop"]))
    assert "Bot tokeni" in page.replies[-1][0] and "Bot tokeni" in msg.replies[-1][0]


async def test_free_owner_cannot_start_a_locked_gallery_bot(henv):
    page = make_msg()
    await handlers.begin_create(upd(OWNER, query=Query("gal:new:shop", page)), henv.ctx, kind="shop")
    assert "state" not in henv.ctx.user_data  # still blocked: Free already holds its one bot


async def test_finish_create_switches_the_new_bot_and_opens_its_panel(henv):
    await give(henv, "pro")
    msg = make_msg()
    ok = await home.finish_create(upd(OWNER, message=msg), henv.ctx, henv.bot.id, "course")
    assert ok
    await henv.session.refresh(henv.bot)
    assert henv.bot.kind == "course" and henv.bot.onboarding_completed
    assert "Kurs bot" in msg.replies[0][0]


async def test_deep_link_rejects_unknown_modes(henv):
    assert not await home.deep_link(upd(OWNER, message=make_msg()), henv.ctx, "new_nonsense")
    assert not await home.deep_link(upd(OWNER, message=make_msg()), henv.ctx, "ref_1")


async def test_paying_for_another_mode_switches_the_bot_once_approved(henv):
    user = await henv.session.get(User, henv.bot.owner_id)
    pay = await plans.create_payment(henv.session, user, bot_id=henv.bot.id, months=1, kind="shop")
    assert pay.kind == "shop" and pay.amount == 50_000
    pid = pay.id
    await plans.attach_receipt(henv.session, pid, user.tg_id, "photo", "F")
    await plans.decide(henv.session, pid, 9000, True)
    await henv.session.refresh(henv.bot)
    assert henv.bot.kind == "shop"
    assert await plans.bot_limits(henv.session, henv.bot, use_cache=False) == plans.Limits("free", True, None, False, None, licensed=True)
    with pytest.raises(plans.PlanError):
        await plans.create_payment(henv.session, user, bot_id=henv.bot.id, kind="nonsense")


async def test_bot_kind_payment_screen(henv):
    page = make_msg()
    await flow.pick_bot_kind_months(upd(OWNER, query=Query(f"plx:bk:{henv.bot.id}:shop", page)), henv.ctx)
    data = data_of(page.edits[-1][1]["reply_markup"])
    assert f"plx:bn:{henv.bot.id}:shop:1" in data and f"plx:bn:{henv.bot.id}:shop:12" in data
    pay_page = make_msg()
    await flow.make_payment(upd(OWNER, query=Query(f"plx:bn:{henv.bot.id}:shop:3", pay_page)), henv.ctx)
    assert "135 000" in pay_page.edits[-1][0] and "Do‘kon bot" in pay_page.edits[-1][0]


async def test_miniapp_home_payload(henv):
    from fastapi import FastAPI
    import httpx
    from test_webapp_api import sign
    from webapp.auth import get_session

    app = FastAPI()
    app.include_router(api_modes.router)

    async def override():
        yield henv.session

    app.dependency_overrides[get_session] = override
    settings.MAIN_BOT_USERNAME = "telecraft_bot"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            data = (await c.get("/api/v1/home", headers={"Authorization": f"tma {sign()}"})).json()
    finally:
        settings.MAIN_BOT_USERNAME = ""
    assert data["plan"] == "Free" and data["bots"] == 1 and data["max_bots"] == 1 and data["main_bot"] == "telecraft_bot"
    by_kind = {g["kind"]: g for g in data["gallery"]}
    assert set(by_kind) == set(home.GALLERY_ORDER) and by_kind["shop"]["locked"] and not by_kind["cinema"]["locked"]
