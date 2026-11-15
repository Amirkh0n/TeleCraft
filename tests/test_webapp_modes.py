"""Mini App: bot kind, mode panel numbers, payment settings and switching modes."""
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from engine.booking_time import utcnow
from helpers import OWNER
from models import join as jn, paid as pd, shop as sh
from models.audience import BotUser
from models.course import CourseSettings
from models.menus import Menu
from models.movies import Movie
from test_webapp_api import sign
from webapp import api as webapp_api, api_modes
from webapp.auth import get_session


@pytest.fixture
async def mc(env):
    app = FastAPI()
    app.include_router(webapp_api.router)
    app.include_router(api_modes.router)

    async def override():
        yield env.session

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.env, c.hdr = env, {"Authorization": f"tma {sign()}"}
        c.stranger = {"Authorization": f"tma {sign(999)}"}
        yield c


async def mode(mc, kind=None):
    if kind:
        mc.env.bot.kind = kind
        await mc.env.session.commit()
    response = await mc.get(f"/api/v1/bots/{mc.env.bot.id}/mode", headers=mc.hdr)
    assert response.status_code == 200
    return response.json()


def numbers(data):
    return {m["label"]: m["value"] for m in data["metrics"]}


async def test_bot_payload_carries_the_kind(mc):
    listed = (await mc.get("/api/v1/bots", headers=mc.hdr)).json()
    assert listed[0]["kind"] == "standard"
    mc.env.bot.kind = "course"
    await mc.env.session.commit()
    assert (await mc.get(f"/api/v1/bots/{mc.env.bot.id}", headers=mc.hdr)).json()["bot"]["kind"] == "course"


async def test_every_mode_has_a_description_steps_and_numbers(mc):
    seen = set()
    for kind in api_modes.MODES:
        data = await mode(mc, kind)
        assert data["kind"] == kind and data["name"] and data["about"] and data["steps"] and data["metrics"]
        assert [k["kind"] for k in data["kinds"]] == list(api_modes.MODES)
        seen.add(kind)
    assert seen == {"standard", "cinema", "booking", "quiz", "course", "shop", "join", "paid"}


async def test_standard_mode_has_no_payment_and_counts_users(mc):
    mc.env.session.add(BotUser(bot_id=mc.env.bot.id, tg_user_id=1))
    await mc.env.session.commit()
    data = await mode(mc)
    assert data["payment"] is None and numbers(data) == {"Foydalanuvchilar": 1}


async def test_cinema_numbers(mc):
    mc.env.session.add(Movie(bot_id=mc.env.bot.id, code="1", title="Film", file_id="f"))
    await mc.env.session.commit()
    assert numbers(await mode(mc, "cinema"))["Kinolar"] == 1


async def test_paid_numbers_and_revenue(mc):
    s, b, now = mc.env.session, mc.env.bot.id, utcnow()
    plan = pd.PaidPlan(bot_id=b, title="1 oy", days=30, price=100_000)
    s.add(plan)
    await s.flush()
    from datetime import timedelta
    for uid, days in ((1, 2), (2, 20), (3, -1)):  # expiring soon, healthy, already expired
        s.add(pd.PaidSub(bot_id=b, plan_id=plan.id, tg_user_id=uid, expires_at=now + timedelta(days=days)))
    s.add(pd.PaidPayment(bot_id=b, plan_id=plan.id, tg_user_id=1, days=30, original_price=100_000, price=80_000, status="approved"))
    s.add(pd.PaidPayment(bot_id=b, plan_id=plan.id, tg_user_id=2, days=30, original_price=100_000, price=100_000, status="approved"))
    s.add(pd.PaidPayment(bot_id=b, plan_id=plan.id, tg_user_id=3, days=30, original_price=100_000, price=100_000, status="pending"))
    await s.commit()
    data = await mode(mc, "paid")
    assert numbers(data) == {"Tariflar": 1, "Faol obunachilar": 2, "3 kunda tugaydi": 1,
                             "Kutilayotgan to‘lovlar": 1, "Tushum": 180_000}
    assert [m["money"] for m in data["metrics"]] == [False, False, False, False, True]


async def test_join_numbers(mc):
    s, b = mc.env.session, mc.env.bot.id
    chat = jn.JoinChat(bot_id=b, chat_id=-1, title="K", questions=[])
    s.add(chat)
    await s.flush()
    for i, status in enumerate(("review", "pending", "approved", "approved", "declined", "expired")):
        s.add(jn.JoinRequest(bot_id=b, chat_ref=chat.id, tg_user_id=i, status=status, answers=[]))
    await s.commit()
    assert numbers(await mode(mc, "join")) == {"Kanal va guruhlar": 1, "Kutilayotgan arizalar": 2, "Qabul qilingan": 2,
                                               "Rad / muddati o‘tgan": 2}


async def test_shop_numbers(mc):
    s, b = mc.env.session, mc.env.bot.id
    for i, (status, total, pay) in enumerate((("new", 10_000, "unpaid"), ("done", 50_000, "paid"), ("done", 70_000, "paid"), ("cancelled", 9_000, "unpaid"))):
        s.add(sh.Order(bot_id=b, tg_user_id=i, status=status, total=total, payment_status=pay))
    s.add(sh.Order(bot_id=b, tg_user_id=9, status="confirmed", total=1, payment_status="pending"))
    await s.commit()
    data = numbers(await mode(mc, "shop"))
    assert data["Faol buyurtmalar"] == 2 and data["Bajarilgan"] == 2 and data["Chek kutilmoqda"] == 1 and data["Tushum"] == 120_000


async def test_switching_modes_sets_up_the_new_kind(mc):
    bot = mc.env.bot
    out = (await mc.put(f"/api/v1/bots/{bot.id}/mode", json={"kind": "course"}, headers=mc.hdr)).json()
    assert out["bot"]["kind"] == "course" and out["mode"]["name"] == "Kurs bot"
    await mc.env.session.refresh(bot)
    assert bot.kind == "course"
    assert (await mc.env.session.execute(select(CourseSettings).where(CourseSettings.bot_id == bot.id))).scalar_one()
    menu = (await mc.env.session.execute(select(Menu).where(Menu.bot_id == bot.id, Menu.is_start.is_(True)))).scalar_one()
    assert "Kurs" in menu.message_text
    back = (await mc.put(f"/api/v1/bots/{bot.id}/mode", json={"kind": "standard"}, headers=mc.hdr)).json()
    assert back["bot"]["kind"] == "standard"
    assert (await mc.put(f"/api/v1/bots/{bot.id}/mode", json={"kind": "standard"}, headers=mc.hdr)).status_code == 200  # no-op


async def test_unknown_mode_is_rejected(mc):
    response = await mc.put(f"/api/v1/bots/{mc.env.bot.id}/mode", json={"kind": "bogus"}, headers=mc.hdr)
    assert response.status_code == 422
    await mc.env.session.refresh(mc.env.bot)
    assert mc.env.bot.kind == "standard"


@pytest.mark.parametrize("kind,model", [("course", "CourseSettings"), ("shop", "ShopSettings"), ("paid", "PaidSettings")])
async def test_payment_settings_roundtrip(mc, kind, model):
    from models import course, paid, shop
    cls = {"CourseSettings": course.CourseSettings, "ShopSettings": shop.ShopSettings, "PaidSettings": paid.PaidSettings}[model]
    bot = mc.env.bot
    assert (await mode(mc, kind))["payment"]["card_number"] is None
    body = {"card_number": " 8600 1111 2222 3333 ", "card_holder": "Ali V.", "pay_note": "  Izoh  "}
    saved = (await mc.put(f"/api/v1/bots/{bot.id}/payment", json=body, headers=mc.hdr)).json()
    assert saved["card_number"] == "8600 1111 2222 3333" and saved["card_holder"] == "Ali V." and saved["pay_note"] == "Izoh"
    row = (await mc.env.session.execute(select(cls).where(cls.bot_id == bot.id))).scalar_one()
    assert row.card_number == "8600 1111 2222 3333"  # the same row the bot's own engine reads
    assert (await mode(mc))["payment"]["card_number"] == "8600 1111 2222 3333"
    cleared = (await mc.put(f"/api/v1/bots/{bot.id}/payment", json={"card_number": "  "}, headers=mc.hdr)).json()
    assert cleared["card_number"] is None and cleared["card_holder"] is None


async def test_shop_card_switch(mc):
    bot = mc.env.bot
    await mode(mc, "shop")
    assert (await mc.put(f"/api/v1/bots/{bot.id}/payment", json={"card_enabled": False}, headers=mc.hdr)).json()["card_enabled"] is False
    assert (await mc.put(f"/api/v1/bots/{bot.id}/payment", json={"card_number": "1"}, headers=mc.hdr)).json()["card_enabled"] is False  # untouched
    assert (await mc.put(f"/api/v1/bots/{bot.id}/payment", json={"card_enabled": True}, headers=mc.hdr)).json()["card_enabled"] is True


async def test_payment_settings_not_available_for_other_kinds(mc):
    for kind in ("standard", "cinema", "join"):
        await mode(mc, kind)
        response = await mc.put(f"/api/v1/bots/{mc.env.bot.id}/payment", json={"card_number": "1"}, headers=mc.hdr)
        assert response.status_code == 422


async def test_limits_are_enforced(mc):
    await mode(mc, "paid")
    response = await mc.put(f"/api/v1/bots/{mc.env.bot.id}/payment", json={"card_number": "1" * 41}, headers=mc.hdr)
    assert response.status_code == 422


async def test_other_users_cannot_read_or_change_the_mode(mc):
    bot = mc.env.bot
    assert (await mc.get(f"/api/v1/bots/{bot.id}/mode", headers=mc.stranger)).status_code == 404
    assert (await mc.put(f"/api/v1/bots/{bot.id}/mode", json={"kind": "shop"}, headers=mc.stranger)).status_code == 404
    assert (await mc.put(f"/api/v1/bots/{bot.id}/payment", json={"card_number": "1"}, headers=mc.stranger)).status_code == 404
    await mc.env.session.refresh(bot)
    assert bot.kind == "standard"


async def test_requires_authentication(mc):
    assert (await mc.get(f"/api/v1/bots/{mc.env.bot.id}/mode")).status_code == 401
