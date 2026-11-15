"""Pricing: plans, per-bot licences, limits in the child-bot router, receipt payments, reminders."""
import datetime as dt
from dataclasses import replace
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from core import plans
from core.config import settings
from core.migrations import make_config
from engine import plans_notify, router
from helpers import OWNER, USER, message, send
from models.audience import BotUser, Broadcast
from models.bots import Bot
from models.plans import AccountPlan, BotLicense, PlanPayment
from models.users import User

NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "PLANS_ENFORCE", True)
    monkeypatch.setattr(settings, "ADMIN_IDS", "")
    plans.invalidate()
    yield
    plans.invalidate()


async def owner(env) -> User:
    return await env.session.get(User, env.bot.owner_id)


async def buy(env, *, plan=None, bot_id=None, months=1, admin=9000, approve=True, now=NOW):
    user = await owner(env)
    pay = await plans.create_payment(env.session, user, plan=plan, bot_id=bot_id, months=months)
    assert await plans.attach_receipt(env.session, pay.id, user.tg_id, "photo", "F")
    return await plans.decide(env.session, pay.id, admin, approve, now=now)


# ------------------------------------------------------------------ pure rules

def test_prices_and_discounts():
    assert plans.price_for(29_000, 1) == 29_000
    assert plans.price_for(29_000, 3) == 78_000  # -10%
    assert plans.price_for(29_000, 12) == 261_000  # -25%
    assert plans.price_for(79_000, 12) == 711_000
    assert plans.price_for(50_000, 3) == 135_000


def test_state_of_follows_grace():
    acc = AccountPlan(user_id=1, plan="pro", expires_at=NOW)
    assert plans.state_of(None, NOW) == ("free", "free")
    assert plans.state_of(acc, NOW) == ("pro", "active")
    assert plans.state_of(acc, NOW + dt.timedelta(days=2)) == ("pro", "grace")
    assert plans.state_of(acc, NOW + dt.timedelta(days=3, minutes=1)) == ("free", "free")


def test_every_mode_has_a_price_and_a_minimum_plan():
    assert set(plans.KIND_PRICES) == set(plans.ALL_KINDS) == set(plans.KIND_MIN_PLAN)
    assert plans.KIND_MIN_PLAN["shop"] == plans.PRO and plans.KIND_MIN_PLAN["cinema"] == plans.FREE


# ------------------------------------------------------------------ limits on owners

async def test_free_owner_gets_one_bot_and_basic_modes(env, on):
    user = await owner(env)
    with pytest.raises(plans.PlanError):  # env already holds one bot
        await plans.check_new_bot(env.session, user.id)
    await plans.check_kind(env.session, user.id, "cinema")
    with pytest.raises(plans.PlanError) as err:
        await plans.check_kind(env.session, user.id, "shop")
    assert "Pro" in str(err.value) and "50 000" in str(err.value)


async def test_start_allows_three_bots_and_booking_but_not_shop(env, on):
    await buy(env, plan="start")
    user = await owner(env)
    await plans.check_new_bot(env.session, user.id)
    await plans.check_kind(env.session, user.id, "booking")
    with pytest.raises(plans.PlanError):
        await plans.check_kind(env.session, user.id, "shop")
    for n in range(2):
        env.session.add(Bot(owner_id=user.id, name=f"b{n}", token=f"{n}:{'x' * 30}"))
    await env.session.commit()
    with pytest.raises(plans.PlanError):
        await plans.check_new_bot(env.session, user.id)


async def test_nothing_is_limited_when_plans_are_off(env):
    user = await owner(env)
    await plans.check_new_bot(env.session, user.id)
    await plans.check_kind(env.session, user.id, "shop")


async def test_platform_admin_is_never_limited(env, on, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", str(OWNER))
    user = await owner(env)
    await plans.check_new_bot(env.session, user.id)
    await plans.check_kind(env.session, user.id, "shop")
    with pytest.raises(plans.PlanError):
        await plans.start_trial(env.session, user)


async def test_set_kind_refuses_a_locked_mode_and_keeps_the_bot_unchanged(env, on):
    from constructor.flows.cinema import set_kind
    with pytest.raises(plans.PlanError):
        await set_kind(env.session, env.bot, "shop")
    assert env.bot.kind == "standard"
    await set_kind(env.session, env.bot, "cinema")
    assert env.bot.kind == "cinema"


# ------------------------------------------------------------------ payments

async def test_plan_payment_activates_once(env, on):
    user = await owner(env)
    pay = await plans.create_payment(env.session, user, plan="pro", months=3)
    assert pay.amount == 213_000 and pay.status == "draft"
    assert await plans.decide(env.session, pay.id, 9000, True, now=NOW) is None  # no receipt yet
    assert await plans.attach_receipt(env.session, pay.id, user.tg_id + 1, "photo", "F") is None  # not theirs
    assert await plans.attach_receipt(env.session, pay.id, user.tg_id, "photo", "F")
    assert await plans.attach_receipt(env.session, pay.id, user.tg_id, "photo", "G") is None  # sent already
    done = await plans.decide(env.session, pay.id, 9000, True, now=NOW)
    assert done.status == "approved" and done.decided_by == 9000
    assert await plans.decide(env.session, pay.id, 9001, True, now=NOW) is None  # second tap does nothing
    acc = await plans.get_account(env.session, user.id)
    assert acc.plan == "pro" and plans.as_utc(acc.expires_at) == NOW + dt.timedelta(days=90)


async def test_same_plan_extends_from_its_end_other_plan_restarts(env, on):
    await buy(env, plan="start", now=NOW)
    await buy(env, plan="start", now=NOW + dt.timedelta(days=10))
    acc = await plans.get_account(env.session, (await owner(env)).id)
    assert plans.as_utc(acc.expires_at) == NOW + dt.timedelta(days=60)
    await buy(env, plan="pro", now=NOW + dt.timedelta(days=11))
    await env.session.refresh(acc)
    assert acc.plan == "pro" and plans.as_utc(acc.expires_at) == NOW + dt.timedelta(days=41)


async def test_rejected_and_cancelled_payments_change_nothing(env, on):
    user = await owner(env)
    done = await buy(env, plan="pro", approve=False)
    assert done.status == "rejected" and await plans.get_account(env.session, user.id) is None
    pay = await plans.create_payment(env.session, user, plan="pro")
    assert await plans.cancel_payment(env.session, pay.id, user.tg_id)
    assert await plans.attach_receipt(env.session, pay.id, user.tg_id, "photo", "F") is None
    newer = await plans.create_payment(env.session, user, plan="start")  # a new draft drops the old one
    older = await plans.create_payment(env.session, user, plan="pro")
    await env.session.refresh(newer)
    assert newer.status == "cancelled" and older.status == "draft"


async def test_bad_payment_requests_are_refused(env, on):
    user = await owner(env)
    for kw in ({"plan": "gold"}, {"plan": "pro", "months": 2}, {"bot_id": 999}):
        with pytest.raises(plans.PlanError):
            await plans.create_payment(env.session, user, **kw)


async def test_bot_licence_unlocks_one_bot_only(env, on):
    from constructor.flows.cinema import set_kind
    user = await owner(env)
    env.bot.kind = "standard"
    await env.session.commit()
    with pytest.raises(plans.PlanError):
        await set_kind(env.session, env.bot, "shop")
    # buy the shop licence: the bot must already be a shop bot, so switch via the platform admin path first
    env.bot.kind = "shop"
    await env.session.commit()
    pay = await buy(env, bot_id=env.bot.id)
    assert pay.kind == "shop" and pay.amount == 50_000
    lic = (await env.session.execute(select(BotLicense))).scalar_one()
    assert plans.as_utc(lic.expires_at) == NOW + dt.timedelta(days=30)
    other = Bot(owner_id=user.id, name="other", token="5:" + "y" * 30)
    env.session.add(other)
    await env.session.commit()
    with pytest.raises(plans.PlanError):
        await plans.check_kind(env.session, user.id, "shop", other.id)
    await plans.check_kind(env.session, user.id, "shop", env.bot.id)
    # extending continues from the current end
    await buy(env, bot_id=env.bot.id, months=3, now=NOW + dt.timedelta(days=5))
    await env.session.refresh(lic)
    assert plans.as_utc(lic.expires_at) == NOW + dt.timedelta(days=30 + 90)


async def test_trial_is_given_once(env, on):
    user = await owner(env)
    acc = await plans.start_trial(env.session, user, now=NOW)
    assert acc.plan == "pro" and plans.as_utc(acc.expires_at) == NOW + dt.timedelta(days=7)
    await plans.check_kind(env.session, user.id, "shop")
    with pytest.raises(plans.PlanError):
        await plans.start_trial(env.session, user, now=NOW + dt.timedelta(days=30))


# ------------------------------------------------------------------ the child-bot router

@pytest.fixture
def tiny_free(monkeypatch):
    monkeypatch.setitem(plans.PLANS, plans.FREE, replace(plans.PLANS[plans.FREE], user_cap=2))


async def users(env):
    return {u.tg_user_id for u in (await env.session.execute(select(BotUser))).scalars()}


async def test_cap_stops_new_people_but_not_those_already_in(env, on, tiny_free):
    for uid in (1001, 1002):
        await send(env, message("/start", user=uid))
    plans.invalidate()  # the cached limits are refreshed once a minute
    env.tg.calls.clear()
    await send(env, message("/start", user=1003))
    assert 1003 not in await users(env)
    assert router.FULL_TEXT in env.tg.texts(1003)
    await send(env, message("hi", user=1001))
    assert router.FULL_TEXT not in env.tg.texts(1001)


async def test_licensed_bot_ignores_the_cap_and_has_no_footer(env, on, tiny_free):
    await buy(env, bot_id=env.bot.id)
    for uid in (1001, 1002, 1003):
        await send(env, message("/start", user=uid))
    plans.invalidate()
    await send(env, message("/start", user=1004))
    assert {1003, 1004} <= await users(env)
    assert not any("TeleCraft yordamida" in t for t in env.tg.texts(1004))


async def test_free_bot_shows_the_footer_after_start(env, on):
    await send(env, message("/start", user=USER))
    assert any("TeleCraft yordamida" in t for t in env.tg.texts(USER))
    await buy(env, plan="pro")
    plans.invalidate()
    env.tg.calls.clear()
    await send(env, message("/start", user=USER))
    assert not any("TeleCraft yordamida" in t for t in env.tg.texts(USER))


async def test_locked_mode_falls_back_to_standard_until_paid(env, on, monkeypatch):
    seen = []

    async def fake_handle(bot, update, session, tg):
        seen.append(update)

    monkeypatch.setitem(router.MODE_HANDLERS, "shop", SimpleNamespace(handle=fake_handle))
    env.bot.kind = "shop"
    await env.session.commit()
    await send(env, message("x", user=USER))
    assert seen == []  # Free plan: the shop mode does not run
    await buy(env, plan="pro")
    plans.invalidate()
    await send(env, message("y", user=USER))
    assert len(seen) == 1


async def test_everything_runs_as_before_when_plans_are_off(env, monkeypatch):
    seen = []

    async def fake_handle(bot, update, session, tg):
        seen.append(1)

    monkeypatch.setitem(router.MODE_HANDLERS, "shop", SimpleNamespace(handle=fake_handle))
    env.bot.kind = "shop"
    await env.session.commit()
    await send(env, message("x", user=USER))
    assert seen == [1]
    assert not any("TeleCraft yordamida" in t for t in env.tg.texts(USER))


async def test_broadcasts_per_month_are_limited_on_free(env, on):
    await plans.check_broadcast(env.session, env.bot, now=NOW)
    env.session.add(Broadcast(bot_id=env.bot.id, created_by=1, text="x", status="done", started_at=NOW))
    await env.session.commit()
    with pytest.raises(plans.PlanError):
        await plans.check_broadcast(env.session, env.bot, now=NOW + dt.timedelta(days=1))
    await plans.check_broadcast(env.session, env.bot, now=NOW + dt.timedelta(days=20))  # next month
    await buy(env, plan="pro")
    await plans.check_broadcast(env.session, env.bot, now=NOW + dt.timedelta(days=1))


# ------------------------------------------------------------------ reminders

class Outbox:
    def __init__(self):
        self.sent = []

    async def __call__(self, tg_id, text, markup):
        self.sent.append((tg_id, text))


async def test_reminders_grace_and_downgrade_go_out_once(env, on):
    await buy(env, plan="pro", now=NOW)  # ends NOW + 30d
    end = NOW + dt.timedelta(days=30)
    box = Outbox()
    assert await plans_notify.run_once(env.session, box, now=end - dt.timedelta(days=10)) == 0
    assert await plans_notify.run_once(env.session, box, now=end - dt.timedelta(days=2, hours=1)) == 1
    assert await plans_notify.run_once(env.session, box, now=end - dt.timedelta(days=2)) == 0  # same notice
    assert await plans_notify.run_once(env.session, box, now=end - dt.timedelta(hours=5)) == 1  # "tomorrow"
    assert await plans_notify.run_once(env.session, box, now=end + dt.timedelta(days=1)) == 1  # grace
    assert await plans_notify.run_once(env.session, box, now=end + dt.timedelta(days=4)) == 1  # Free again
    assert await plans_notify.run_once(env.session, box, now=end + dt.timedelta(days=5)) == 0
    assert all(tg == OWNER for tg, _ in box.sent) and "Pro" in box.sent[0][1]
    assert "Free" in box.sent[-1][1]


async def test_renewal_gets_fresh_reminders(env, on):
    await buy(env, plan="pro", now=NOW)
    box = Outbox()
    first_end = NOW + dt.timedelta(days=30)
    await plans_notify.run_once(env.session, box, now=first_end - dt.timedelta(days=2))
    await buy(env, plan="pro", now=first_end - dt.timedelta(days=1))  # now ends in 59 days
    assert await plans_notify.run_once(env.session, box, now=first_end - dt.timedelta(hours=2)) == 0
    assert await plans_notify.run_once(env.session, box, now=first_end + dt.timedelta(days=29)) == 1


async def test_licence_reminder_and_user_cap_warning(env, on, tiny_free):
    await buy(env, bot_id=env.bot.id, now=NOW)
    box = Outbox()
    assert await plans_notify.run_once(env.session, box, now=NOW + dt.timedelta(days=28)) == 1
    assert "Shop" in box.sent[0][1]
    # a second Free-capped bot that is full
    user = await owner(env)
    other = Bot(owner_id=user.id, name="Full", token="6:" + "z" * 30)
    env.session.add(other)
    await env.session.flush()
    env.session.add_all([BotUser(bot_id=other.id, tg_user_id=n) for n in (1, 2)])
    await env.session.commit()
    box = Outbox()
    assert await plans_notify.run_once(env.session, box, now=NOW) == 1
    assert "Full" in box.sent[0][1] and "limiti" in box.sent[0][1]
    assert await plans_notify.run_once(env.session, box, now=NOW) == 0


async def test_failed_delivery_is_not_retried_forever(env, on):
    await buy(env, plan="pro", now=NOW)

    async def broken(tg_id, text, markup):
        raise RuntimeError("blocked")

    now = NOW + dt.timedelta(days=28)
    assert await plans_notify.run_once(env.session, broken, now=now) == 0
    assert await plans_notify.run_once(env.session, Outbox(), now=now) == 0  # claimed: not repeated


# ------------------------------------------------------------------ migration

async def test_existing_owners_get_a_30_day_pro(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")

    def up(conn, revision):
        command.upgrade(make_config(conn), revision)

    async with eng.begin() as conn:
        await conn.run_sync(up, "0012_paid_channel")
        await conn.execute(text("insert into users (id, tg_id, full_name) values (1, 5, 'Has bots'), (2, 6, 'No bots')"))
        await conn.execute(text("insert into bots (owner_id, name, token, is_active, webhook_set, onboarding_completed, kind) "
                                "values (1, 'a', 't1', 1, 0, 0, 'standard'), (1, 'b', 't2', 1, 0, 0, 'shop')"))
        await conn.run_sync(up, "head")
        rows = (await conn.execute(text("select user_id, plan, trial_used from account_plans"))).all()
    await eng.dispose()
    assert [tuple(r) for r in rows] == [(1, "pro", 1)]
