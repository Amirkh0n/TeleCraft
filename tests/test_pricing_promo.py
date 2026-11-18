"""Admin-editable prices and limits, and promo codes."""
import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core import plans, pricing, promo
from core.config import settings
from helpers import OWNER
from models.plans import AppSetting, PlanPayment, PromoCode, PromoUse
from models.users import User
from test_webapp_admin import ADMIN, ac  # noqa: F401


@pytest.fixture(autouse=True)
def restore_prices():
    pricing.apply(None)
    yield
    pricing.apply(None)


async def user_of(env) -> User:
    return await env.session.get(User, env.bot.owner_id)


# ------------------------------------------------------------------ prices and limits

def test_validate_rejects_bad_values():
    bad = [{"plans": {"gold": {"price": 5000}}}, {"plans": {"free": {"price": 5000}}}, {"plans": {"pro": {"price": 10}}},
           {"plans": {"pro": {"price": "x"}}}, {"plans": {"pro": {"max_bots": 0}}}, {"plans": {"pro": {"price": True}}},
           {"kind_prices": {"nope": 5000}}, {"kind_prices": {"shop": 99_000_000}}, {"discount": {"1": 5}}, {"discount": {"3": 95}}, {"discount": {"7": 5}}, []]
    for data in bad:
        with pytest.raises(pricing.PricingError):
            pricing.validate(data)
    ok = pricing.validate({"plans": {"pro": {"price": 60_000, "user_cap": None, "broadcasts": 0}}, "kind_prices": {"shop": 45_000}, "discount": {"3": 15}})
    assert ok["plans"]["pro"] == {"price": 60_000, "user_cap": None, "broadcasts": 0}


async def test_save_applies_everywhere_and_reset_restores(env):
    before = plans.PLANS["start"]
    await pricing.save(env.session, {"plans": {"start": {"price": 25_000, "max_bots": 5, "user_cap": None}, "free": {"user_cap": 50}},
                                     "kind_prices": {"shop": 45_000}, "discount": {"3": 20}})
    assert plans.PLANS["start"].price == 25_000 and plans.PLANS["start"].max_bots == 5 and plans.PLANS["start"].user_cap is None
    assert plans.PLANS["start"].watermark == before.watermark and plans.PLANS["free"].user_cap == 50
    assert plans.KIND_PRICES["shop"] == 45_000 and plans.price_for(25_000, 3) == 60_000  # 25k x 3 − 20%
    await pricing.save(env.session, {"plans": {"start": {"price": 27_000}}})  # merges: earlier edits stay
    assert plans.PLANS["start"].max_bots == 5 and plans.PLANS["start"].price == 27_000 and plans.KIND_PRICES["shop"] == 45_000
    stored = (await env.session.get(AppSetting, "pricing")).value
    pricing.apply(None)
    assert plans.PLANS["start"] == before
    await pricing.load(env.session)  # as at startup
    assert plans.PLANS["start"].price == 27_000 and stored["discount"] == {"3": 20}
    await pricing.reset(env.session)
    assert plans.PLANS["start"] == before and plans.KIND_PRICES["shop"] == 50_000 and plans.DISCOUNT[3] == 10
    assert await env.session.get(AppSetting, "pricing") is None


async def test_a_broken_stored_override_falls_back_to_defaults(env):
    env.session.add(AppSetting(key="pricing", value={"plans": {"pro": {"price": 1}}}))
    await env.session.commit()
    await pricing.load(env.session)
    assert plans.PLANS["pro"].price == 79_000


async def test_new_price_reaches_new_payments_and_user_cap_reaches_limits(env, monkeypatch):
    monkeypatch.setattr(settings, "PLANS_ENFORCE", True)
    monkeypatch.setattr(settings, "ADMIN_IDS", "")
    await pricing.save(env.session, {"plans": {"pro": {"price": 60_000}, "free": {"user_cap": 7}}})
    user = await user_of(env)
    pay = await plans.create_payment(env.session, user, plan="pro", months=1)
    assert pay.amount == 60_000
    limits = await plans.bot_limits(env.session, env.bot, use_cache=False)
    assert limits.user_cap == 7


async def test_admin_api_get_put_reset_and_access(ac):
    got = (await ac.get("/api/v1/admin/pricing", headers=ac.hdr)).json()
    assert [p["code"] for p in got["plans"]] == ["free", "start", "pro", "business"] and got["plans"][0]["editable_price"] is False
    assert got["kind_prices"][0]["default"] == got["kind_prices"][0]["price"]
    res = await ac.put("/api/v1/admin/pricing", headers=ac.hdr, json={"plans": {"pro": {"price": 55_000, "user_cap": 5000}}, "kind_prices": {"cinema": 18_000}, "discount": {"12": 30}})
    assert res.status_code == 200
    out = res.json()
    pro = next(p for p in out["plans"] if p["code"] == "pro")
    assert pro["price"] == 55_000 and pro["user_cap"] == 5000 and pro["default"]["price"] == 79_000 and out["discount"]["12"] == 30
    bad = await ac.put("/api/v1/admin/pricing", headers=ac.hdr, json={"plans": {"pro": {"price": 5}}})
    assert bad.status_code == 422 and "Pro narxi" in bad.json()["detail"]
    assert (await ac.put("/api/v1/admin/pricing", headers=ac.owner, json={})).status_code == 403
    again = (await ac.post("/api/v1/admin/pricing/reset", headers=ac.hdr)).json()
    assert next(p for p in again["plans"] if p["code"] == "pro")["price"] == 79_000
    actions = [x.action for x in (await ac.env.session.execute(select(__import__("models.plans", fromlist=["AdminLog"]).AdminLog))).scalars().all()]
    assert "pricing" in actions and "pricing_reset" in actions


# ------------------------------------------------------------------ promo codes

async def draft(env, plan="pro", months=1):
    user = await user_of(env)
    return user, await plans.create_payment(env.session, user, plan=plan, months=months)


async def test_create_validates_and_generates_codes(env):
    s = env.session
    auto = await promo.create(s, code=None, percent=20, amount=None, max_uses=None, days=None, note=None)
    assert len(auto.code) == 8 and set(auto.code) <= set(promo.ALPHABET)
    named = await promo.create(s, code=" yoz 2026 ", percent=None, amount=10_000, max_uses=5, days=10, note="Yoz aksiyasi")
    assert named.code == "YOZ2026" and named.expires_at is not None
    for kw, word in (({"percent": 20, "amount": 5000}, "birini"), ({"percent": None, "amount": None}, "birini"), ({"percent": 95}, "1 dan 90"),
                     ({"percent": None, "amount": 10}, "Summa"), ({"percent": 10, "max_uses": 0}, "kamida"), ({"percent": 10, "code": "a!"}, "3–32"),
                     ({"percent": 10, "code": "yoz2026"}, "allaqachon")):
        args = dict(code=None, percent=None, amount=None, max_uses=None, days=None, note=None) | kw
        with pytest.raises(plans.PlanError, match=word):
            await promo.create(s, **args)


async def test_apply_percent_fixed_minimum_and_replacement(env):
    user, pay = await draft(env)  # Pro 79 000
    await promo.create(env.session, code="P20", percent=20, amount=None, max_uses=None, days=None, note=None)
    await promo.create(env.session, code="MINUS10", percent=None, amount=10_000, max_uses=None, days=None, note=None)
    await promo.create(env.session, code="HUGE", percent=None, amount=10_000_000, max_uses=None, days=None, note=None)
    pay = await promo.apply_to_payment(env.session, pay.id, user.id, " p20 ")
    assert pay.amount == 63_000 and pay.discount == 16_000 and pay.promo_code == "P20"  # 79 000 − 20% = 63 200 → 63 000
    pay = await promo.apply_to_payment(env.session, pay.id, user.id, "MINUS10")  # replaces, counted from the full price
    assert pay.amount == 69_000 and pay.discount == 10_000 and pay.promo_code == "MINUS10"
    pay = await promo.apply_to_payment(env.session, pay.id, user.id, "HUGE")
    assert pay.amount == promo.MIN_AMOUNT  # never free: a free payment would need no receipt
    assert "promo HUGE" in plans.describe(pay)


async def test_check_reasons(env):
    user, pay = await draft(env)
    s = env.session
    await promo.create(s, code="OFF", percent=10, amount=None, max_uses=None, days=None, note=None)
    await promo.create(s, code="OLD", percent=10, amount=None, max_uses=None, days=None, note=None)
    await promo.create(s, code="FULL", percent=10, amount=None, max_uses=1, days=None, note=None)
    (await s.execute(select(PromoCode).where(PromoCode.code == "OFF"))).scalar_one().active = False
    (await s.execute(select(PromoCode).where(PromoCode.code == "OLD"))).scalar_one().expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    (await s.execute(select(PromoCode).where(PromoCode.code == "FULL"))).scalar_one().used_count = 1
    await s.commit()
    for code, word in (("NOPE", "yo‘q"), ("OFF", "yo‘q"), ("OLD", "muddati"), ("FULL", "limiti")):
        with pytest.raises(plans.PlanError, match=word):
            await promo.apply_to_payment(s, pay.id, user.id, code)
    other = await plans.create_payment(s, user, plan="pro", months=1)
    await plans.attach_receipt(s, other.id, user.tg_id, "photo", "F")  # no longer a draft
    await promo.create(s, code="OKAY", percent=10, amount=None, max_uses=None, days=None, note=None)
    with pytest.raises(plans.PlanError, match="allaqachon yuborilgan"):
        await promo.apply_to_payment(s, other.id, user.id, "OKAY")
    with pytest.raises(plans.PlanError, match="topilmadi"):
        await promo.apply_to_payment(s, pay.id, user.id + 999, "OK")


async def test_code_is_counted_only_when_the_payment_is_approved_and_once_per_person(env):
    user, pay = await draft(env)
    user = SimpleNamespace(id=user.id, tg_id=user.tg_id)  # plain copy: the ORM row expires after commits
    await promo.create(env.session, code="ONCE", percent=50, amount=None, max_uses=2, days=None, note=None)
    pay = await promo.apply_to_payment(env.session, pay.id, user.id, "ONCE")
    assert pay.amount == 40_000  # 39 500 → 40 000 (rounded to thousands)
    await plans.attach_receipt(env.session, pay.id, user.tg_id, "photo", "F")
    row = (await env.session.execute(select(PromoCode).where(PromoCode.code == "ONCE"))).scalar_one()
    assert row.used_count == 0  # pending: not counted yet
    await plans.decide(env.session, pay.id, ADMIN, True)
    env.session.expire_all()
    row = (await env.session.execute(select(PromoCode).where(PromoCode.code == "ONCE"))).scalar_one()
    assert row.used_count == 1 and len((await env.session.execute(select(PromoUse))).scalars().all()) == 1
    second = await plans.create_payment(env.session, user, plan="pro", months=1)
    with pytest.raises(plans.PlanError, match="allaqachon ishlatgansiz"):
        await promo.apply_to_payment(env.session, second.id, user.id, "ONCE")
    # a rejected payment never counts
    rej = await plans.create_payment(env.session, user, plan="start", months=1)
    rej.promo_code = "ONCE"
    await env.session.commit()
    await plans.attach_receipt(env.session, rej.id, user.tg_id, "photo", "F")
    await plans.decide(env.session, rej.id, ADMIN, False)
    env.session.expire_all()
    assert (await env.session.execute(select(PromoCode).where(PromoCode.code == "ONCE"))).scalar_one().used_count == 1


async def test_two_open_payments_with_the_same_code_do_not_break_approval(env):
    user, a = await draft(env, "pro")
    user = SimpleNamespace(id=user.id, tg_id=user.tg_id)
    await promo.create(env.session, code="TWICE", percent=10, amount=None, max_uses=None, days=None, note=None)
    a = await promo.apply_to_payment(env.session, a.id, user.id, "TWICE")
    b = PlanPayment(user_id=user.id, tg_user_id=user.tg_id, target="plan", plan="start", months=1, amount=26_000, promo_code="TWICE", discount=3000, status="pending", receipt_type="photo", receipt_file_id="F")
    env.session.add(b)
    await env.session.commit()
    await plans.attach_receipt(env.session, a.id, user.tg_id, "photo", "F")
    assert await plans.decide(env.session, a.id, ADMIN, True)
    assert await plans.decide(env.session, b.id, ADMIN, True)  # same person used it already: approved anyway, counted once
    env.session.expire_all()
    assert (await env.session.execute(select(PromoCode).where(PromoCode.code == "TWICE"))).scalar_one().used_count == 1


async def test_admin_api_promos(ac):
    res = await ac.post("/api/v1/admin/promos", headers=ac.hdr, json={"percent": 15, "max_uses": 3, "days": 7, "note": "test"})
    assert res.status_code == 201
    made = res.json()
    assert made["label"] == "−15%" and made["state"] == "live" and made["used"] == 0 and made["expires_at"]
    assert (await ac.post("/api/v1/admin/promos", headers=ac.hdr, json={"code": made["code"], "amount": 5000})).status_code == 422
    assert (await ac.post("/api/v1/admin/promos", headers=ac.hdr, json={"percent": 15, "amount": 5000})).status_code == 422
    assert (await ac.post("/api/v1/admin/promos", headers=ac.owner, json={"percent": 15})).status_code == 403
    off = (await ac.post(f"/api/v1/admin/promos/{made['id']}/active", headers=ac.hdr, json={"active": False})).json()
    assert off["state"] == "off" and off["active"] is False
    assert (await ac.post("/api/v1/admin/promos/999/active", headers=ac.hdr, json={"active": True})).status_code == 404
    items = (await ac.get("/api/v1/admin/promos", headers=ac.hdr)).json()["items"]
    assert [i["code"] for i in items] == [made["code"]]


# ------------------------------------------------------------------ main bot: typing a code while paying

async def test_main_bot_promo_flow(env, monkeypatch):
    import sys
    from constructor.flows import plans as flow
    from test_home import Query, buttons, make_msg, upd
    from helpers import FakeTG
    monkeypatch.setattr(settings, "PLANS_ENFORCE", True)
    monkeypatch.setattr(settings, "ADMIN_IDS", "")
    monkeypatch.setattr(settings, "PLAN_CARD_NUMBER", "8600 0000 0000 0000")
    for name, module in list(sys.modules.items()):
        if name.startswith("constructor") and hasattr(module, "AsyncSessionLocal"):
            monkeypatch.setattr(module, "AsyncSessionLocal", env.maker)
    ctx = SimpleNamespace(user_data={}, bot=FakeTG(), args=[])
    await promo.create(env.session, code="SALOM", percent=10, amount=None, max_uses=None, days=None, note=None)
    page = make_msg()
    await flow.make_payment(upd(OWNER, query=Query("plx:pm:pro:1", page)), ctx)
    text, kw = page.edits[-1]
    assert "79 000" in text and f"plx:pr:{ctx.user_data['draft']['id']}" in [b.callback_data for b in buttons(kw["reply_markup"])]
    pay_id = ctx.user_data["draft"]["id"]
    await flow.ask_promo(upd(OWNER, query=Query(f"plx:pr:{pay_id}", page)), ctx)
    assert ctx.user_data["state"] == "waiting_for_promo"
    bad = make_msg(text="NOPE")
    await flow.promo_text(upd(OWNER, message=bad), ctx)
    assert "❌" in bad.replies[-1][0] and ctx.user_data["state"] == "waiting_for_plan_receipt"  # back to waiting for the receipt
    await flow.ask_promo(upd(OWNER, query=Query(f"plx:pr:{pay_id}", page)), ctx)
    good = make_msg(text="salom")
    await flow.promo_text(upd(OWNER, message=good), ctx)
    shown = good.replies[-1][0]
    assert "<s>79 000" in shown and "71 000" in shown and "SALOM" in shown
    assert ctx.user_data["state"] == "waiting_for_plan_receipt" and ctx.user_data["draft"]["id"] == pay_id
