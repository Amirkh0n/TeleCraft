import datetime as dt
from datetime import timedelta

import pytest
from sqlalchemy import select

from engine import paid as core, paid_logic as logic, paid_notify as notify
from engine.booking_time import utcnow
from helpers import OWNER, USER, send
from helpers import message as _message
from models.paid import PaidChannel, PaidPayment, PaidPlan, PaidPlanChannel, PaidPromo, PaidSub

CH1, CH2 = -1001, -1002


def message(text=None, *, user=USER, **extra):
    return _message(text, user=user, **extra)


def cb(data, user=USER, mid=9, caption=False):
    msg = {"message_id": mid, "chat": {"id": user, "type": "private"}}
    if caption:
        msg["caption"] = "x"
    return {"update_id": None, "callback_query": {"id": "c", "from": {"id": user, "first_name": "Ali", "username": "ali"},
                                                 "data": data, "message": msg}}


def photo(user=USER):
    return message(user=user, photo=[{"file_id": "small"}, {"file_id": "rcpt"}])


def admin_added(chat_id=CH1, title="Yopiq", status="administrator", **rights):
    return {"update_id": None, "my_chat_member": {
        "chat": {"id": chat_id, "title": title, "type": "channel"}, "from": {"id": OWNER, "first_name": "Owner"},
        "new_chat_member": {"status": status, **rights}}}


def datas(call):
    kb = call.get("reply_markup")
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data] if kb else []


def urls(call):
    kb = call.get("reply_markup")
    return [b.url for row in kb.inline_keyboard for b in row if b.url] if kb else []


@pytest.fixture
async def penv(env):
    env.bot.kind = "paid"
    await core.ensure_setup(env.session, env.bot)
    st = await core.get_settings(env.session, env.bot.id)
    st.card_number, st.card_holder = "8600 1111 2222 3333", "Ali V."
    await env.session.commit()
    return env


async def make_plan(env, title="1 oy", days=30, price=100_000, channels=(CH1,)):
    plan = PaidPlan(bot_id=env.bot.id, title=title, days=days, price=price)
    env.session.add(plan)
    await env.session.flush()
    for chat_id in channels:
        ch = (await env.session.execute(select(PaidChannel).where(PaidChannel.chat_id == chat_id))).scalar_one_or_none()
        if ch is None:
            ch = PaidChannel(bot_id=env.bot.id, chat_id=chat_id, title=f"Kanal {-chat_id}")
            env.session.add(ch)
            await env.session.flush()
        env.session.add(PaidPlanChannel(plan_id=plan.id, channel_id=ch.id))
    await env.session.commit()
    env.tg.calls.clear()
    return plan


async def rows(env, model):
    q = select(model).execution_options(populate_existing=True).order_by(getattr(model, 'id', None) or model.plan_id)
    return list((await env.session.execute(q)).scalars().all())


async def buy(env, plan, user=USER):
    await send(env, cb(f"pc:buy:{plan.id}", user=user))
    await send(env, photo(user))
    return [x for x in await rows(env, PaidPayment) if x.tg_user_id == user][-1]


# ------------------------------------------------------------------ pure logic

def test_discount_parsing_and_prices():
    assert logic.parse_discount("20%") == (20, None) and logic.parse_discount("15 000") == (None, 15000)
    for bad in ("0%", "101%", "abc", "0"):
        with pytest.raises(ValueError):
            logic.parse_discount(bad)
    p = PaidPromo(percent=25, amount=None)
    assert logic.discounted(100_000, p) == 75_000
    assert logic.discounted(100_000, PaidPromo(percent=None, amount=150_000)) == 0
    assert logic.discounted(100_000, PaidPromo(percent=100, amount=None)) == 0
    assert logic.valid_code("yoz-25") and not logic.valid_code("a b")


def test_promo_errors():
    now = utcnow()
    assert logic.promo_error(None, now)
    assert logic.promo_error(PaidPromo(is_active=False, used_count=0), now)
    assert logic.promo_error(PaidPromo(is_active=True, used_count=0, expires_at=now - timedelta(seconds=1)), now)
    assert logic.promo_error(PaidPromo(is_active=True, used_count=3, max_uses=3), now)
    assert logic.promo_error(PaidPromo(is_active=True, used_count=2, max_uses=3), now) is None


def test_extend_days_left_and_reminders():
    now = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)
    assert logic.extend(None, now, 30) == now + timedelta(days=30)
    assert logic.extend(now + timedelta(days=5), now, 30) == now + timedelta(days=35)  # renewing adds to the end
    assert logic.extend(now - timedelta(days=5), now, 30) == now + timedelta(days=30)  # expired: starts now
    assert logic.days_left(now + timedelta(hours=5), now) == 1 and logic.days_left(now - timedelta(1), now) == 0
    assert logic.reminder_due(now + timedelta(days=10), now, False, False) is None
    assert logic.reminder_due(now + timedelta(days=3), now, False, False) == 3
    assert logic.reminder_due(now + timedelta(days=3), now, True, False) is None
    assert logic.reminder_due(now + timedelta(hours=20), now, True, False) == 1
    assert logic.reminder_due(now + timedelta(hours=20), now, True, True) is None
    assert logic.reminder_due(now - timedelta(seconds=1), now, False, False) is None


# ------------------------------------------------------------------ channels

async def test_bot_made_admin_registers_channel_and_warns_about_rights(penv):
    await send(penv, admin_added(can_invite_users=True, can_restrict_members=False))
    ch = (await rows(penv, PaidChannel))[0]
    assert (ch.chat_id, ch.title, ch.is_active) == (CH1, "Yopiq", True)
    assert "cheklash" in penv.tg.texts(OWNER)[-1]
    await send(penv, admin_added(status="left"))
    assert (await rows(penv, PaidChannel))[0].is_active is False


# ------------------------------------------------------------------ buying

async def test_purchase_flow_with_receipt_and_approval(penv):
    plan = await make_plan(penv)
    await send(penv, message("/start"))
    assert "pc:plans" in datas(penv.tg.last())
    await send(penv, cb("pc:plans"))
    assert f"pc:p:{plan.id}" in datas(penv.tg.last("edit_message_text"))
    await send(penv, cb(f"pc:buy:{plan.id}"))
    pay_text = penv.tg.last("edit_message_text")["text"]
    assert "8600 1111 2222 3333" in pay_text and "100 000" in pay_text
    await send(penv, photo())
    (pay,) = await rows(penv, PaidPayment)
    assert pay.status == "pending" and pay.receipt_file_id == "rcpt"
    notice = penv.tg.of("send_photo")[-1]
    assert notice["chat_id"] == OWNER and datas(notice) == [f"pa:pok:{pay.id}", f"pa:prj:{pay.id}"]

    await send(penv, cb(f"pa:pok:{pay.id}", user=OWNER, caption=True))
    (sub,) = await rows(penv, PaidSub)
    assert sub.status == "active" and not sub.is_trial
    assert timedelta(days=29, hours=23) < core.as_utc(sub.expires_at) - utcnow() <= timedelta(days=30)
    assert penv.tg.of("create_chat_invite_link")[-1]["member_limit"] == 1
    access = [c for c in penv.tg.of("send_message") if c["chat_id"] == USER][-1]
    assert "To‘lov tasdiqlandi" in access["text"] and urls(access) == ["https://t.me/+link1"]
    await send(penv, cb(f"pa:pok:{pay.id}", user=OWNER, caption=True))  # second tap is a no-op
    assert len(await rows(penv, PaidSub)) == 1 and len(penv.tg.of("create_chat_invite_link")) == 1


async def test_second_receipt_while_pending_is_refused(penv):
    plan = await make_plan(penv)
    await buy(penv, plan)
    await send(penv, cb(f"pc:buy:{plan.id}"))
    assert "tekshirilmoqda" in penv.tg.last("edit_message_text")["text"]
    assert len(await rows(penv, PaidPayment)) == 1


async def test_non_image_instead_of_receipt(penv):
    plan = await make_plan(penv)
    await send(penv, cb(f"pc:buy:{plan.id}"))
    await send(penv, message("men to'ladim"))
    assert "rasmini yuboring" in penv.tg.texts()[-1]
    assert (await rows(penv, PaidPayment))[0].status == "draft"


async def test_rejection_notifies_with_reason_and_allows_retry(penv):
    plan = await make_plan(penv)
    pay = await buy(penv, plan)
    await send(penv, cb(f"pa:prj:{pay.id}", user=OWNER, caption=True))
    await send(penv, message("Summa kam", user=OWNER))
    assert "Summa kam" in penv.tg.texts(USER)[-1]
    assert (await rows(penv, PaidPayment))[0].status == "rejected" and not await rows(penv, PaidSub)
    pay2 = await buy(penv, plan)  # a fresh attempt creates a new payment
    assert pay2.id != pay.id and pay2.status == "pending"


async def test_no_card_configured_blocks_payment(penv):
    (await core.get_settings(penv.session, penv.bot.id)).card_number = None
    await penv.session.commit()
    plan = await make_plan(penv)
    await send(penv, cb(f"pc:buy:{plan.id}"))
    assert "sozlanmagan" in penv.tg.last("edit_message_text")["text"]


async def test_renewal_extends_from_current_end(penv):
    plan = await make_plan(penv)
    pay = await buy(penv, plan)
    await send(penv, cb(f"pa:pok:{pay.id}", user=OWNER, caption=True))
    first = (await rows(penv, PaidSub))[0].expires_at
    pay2 = await buy(penv, plan)
    await send(penv, cb(f"pa:pok:{pay2.id}", user=OWNER, caption=True))
    (sub,) = await rows(penv, PaidSub)
    assert core.as_utc(sub.expires_at) - core.as_utc(first) == timedelta(days=30)


# ------------------------------------------------------------------ promo codes

async def promo(env, code="YOZ25", **kw):
    p = PaidPromo(bot_id=env.bot.id, code=code, **kw)
    env.session.add(p)
    await env.session.commit()
    return p


async def test_promo_code_discounts_the_price(penv):
    plan = await make_plan(penv)
    await promo(penv, percent=25)
    await send(penv, cb(f"pc:promo:{plan.id}"))
    await send(penv, message("noto'g'ri"))
    assert "topilmadi" in penv.tg.texts()[-1]
    await send(penv, message("yoz25"))  # case-insensitive
    assert "75 000" in penv.tg.last()["text"]
    pay = await buy(penv, plan)
    assert (pay.price, pay.original_price, pay.promo_code) == (75_000, 100_000, "YOZ25")
    assert (await rows(penv, PaidPromo))[0].used_count == 1
    await send(penv, cb(f"pa:prj:{pay.id}", user=OWNER, caption=True))
    await send(penv, message("/skip", user=OWNER))
    assert (await rows(penv, PaidPromo))[0].used_count == 0  # a rejected payment gives the use back


async def test_promo_with_limited_uses_runs_out(penv):
    plan = await make_plan(penv)
    p = await promo(penv, percent=10, max_uses=1)
    for user in (USER, 888):  # both apply the code before anyone pays: the single use is taken at the receipt
        await send(penv, cb(f"pc:promo:{plan.id}", user=user))
        await send(penv, message(p.code, user=user))
    first = await buy(penv, plan, user=USER)
    assert (first.price, first.status) == (90_000, "pending")
    await send(penv, cb(f"pc:buy:{plan.id}", user=888))
    shown = penv.tg.last("edit_message_text")["text"]
    assert "Promokod endi amal qilmaydi" in shown and "100 000" in shown
    await send(penv, photo(888))
    (second,) = [x for x in await rows(penv, PaidPayment) if x.tg_user_id == 888]
    assert (second.status, second.price, second.promo_code) == ("pending", 100_000, None)
    assert (await rows(penv, PaidPromo))[0].used_count == 1


async def test_hundred_percent_promo_is_free_and_instant(penv):
    plan = await make_plan(penv)
    await promo(penv, code="FREE", percent=100)
    await send(penv, cb(f"pc:promo:{plan.id}"))
    await send(penv, message("free"))
    await send(penv, cb(f"pc:buy:{plan.id}"))
    (sub,) = await rows(penv, PaidSub)
    assert sub.status == "active"
    assert not penv.tg.of("send_photo")  # no receipt, no admin work
    assert urls([c for c in penv.tg.of("send_message") if c["chat_id"] == USER][-1])
    assert (await rows(penv, PaidPromo))[0].used_count == 1


# ------------------------------------------------------------------ trial

async def test_free_trial_once_per_person(penv):
    plan = await make_plan(penv)
    st = await core.get_settings(penv.session, penv.bot.id)
    st.trial_enabled, st.trial_days, st.trial_plan_id = True, 3, plan.id
    await penv.session.commit()
    await send(penv, message("/start"))
    assert "pc:trial" in datas(penv.tg.last())
    await send(penv, cb("pc:trial"))
    (sub,) = await rows(penv, PaidSub)
    assert sub.is_trial and sub.trial_used and timedelta(days=2, hours=23) < core.as_utc(sub.expires_at) - utcnow() <= timedelta(days=3)
    assert urls([c for c in penv.tg.of("send_message") if c["chat_id"] == USER][-1])
    await send(penv, message("/start"))
    assert "pc:trial" not in datas(penv.tg.last())
    await send(penv, cb("pc:trial"))  # tapping a stale button changes nothing
    assert len(await rows(penv, PaidSub)) == 1
    pay = await buy(penv, plan)  # paying afterwards turns the trial into a normal subscription, trial stays used
    await send(penv, cb(f"pa:pok:{pay.id}", user=OWNER, caption=True))
    sub = (await rows(penv, PaidSub))[0]
    assert not sub.is_trial and sub.trial_used


# ------------------------------------------------------------------ the clock

async def client_for_factory(env):
    async def client_for(bot):
        return env.tg
    return client_for


async def subscribe(env, plan, user=USER, days=30):
    return await core.grant(env.session, env.bot, plan, {"id": user, "name": "Ali", "username": "ali"}, days)


async def test_expired_subscription_is_removed_and_offered_renewal(penv):
    plan = await make_plan(penv)
    sub = await subscribe(penv, plan, days=1)
    sub.expires_at = utcnow() - timedelta(minutes=1)
    await penv.session.commit()
    result = await notify.run_once(penv.session, client_for=await client_for_factory(penv))
    assert result["expired"] == 1
    assert penv.tg.of("ban_chat_member") == [{"chat_id": CH1, "user_id": USER}]
    assert penv.tg.of("unban_chat_member") == [{"chat_id": CH1, "user_id": USER, "only_if_banned": True}]
    msg = penv.tg.of("send_message")[-1]
    assert "tugadi" in msg["text"] and datas(msg) == [f"pc:p:{plan.id}"]
    assert (await rows(penv, PaidSub))[0].status == "expired"
    penv.tg.calls.clear()
    assert (await notify.run_once(penv.session, client_for=await client_for_factory(penv)))["expired"] == 0
    assert not penv.tg.calls


async def test_channel_shared_with_a_live_plan_is_not_removed(penv):
    a = await make_plan(penv, "Oddiy", channels=(CH1,))
    b = await make_plan(penv, "Premium", channels=(CH1, CH2))
    sub_a = await subscribe(penv, a)
    await subscribe(penv, b)
    sub_a.expires_at = utcnow() - timedelta(minutes=1)
    await penv.session.commit()
    await notify.run_once(penv.session, client_for=await client_for_factory(penv))
    assert penv.tg.of("ban_chat_member") == []  # CH1 is still covered by Premium


async def test_reminders_go_out_once_each(penv):
    plan = await make_plan(penv)
    sub = await subscribe(penv, plan, days=30)
    cf = await client_for_factory(penv)
    assert (await notify.run_once(penv.session, client_for=cf))["reminded"] == 0
    sub.expires_at = utcnow() + timedelta(days=2, hours=23)
    await penv.session.commit()
    assert (await notify.run_once(penv.session, client_for=cf))["reminded"] == 1
    assert "3 kundan" in penv.tg.of("send_message")[-1]["text"]
    assert (await notify.run_once(penv.session, client_for=cf))["reminded"] == 0
    sub.expires_at = utcnow() + timedelta(hours=20)
    await penv.session.commit()
    assert (await notify.run_once(penv.session, client_for=cf))["reminded"] == 1
    assert "1 kundan" in penv.tg.of("send_message")[-1]["text"]
    assert (await notify.run_once(penv.session, client_for=cf))["reminded"] == 0
    # renewing resets the reminders
    await core.grant(penv.session, penv.bot, plan, {"id": USER, "name": "Ali", "username": None}, 2)
    assert (await rows(penv, PaidSub))[0].reminded_1 is False


async def test_blocked_user_does_not_break_the_clock(penv):
    plan = await make_plan(penv)
    sub = await subscribe(penv, plan)
    sub.expires_at = utcnow() - timedelta(minutes=1)
    await penv.session.commit()
    penv.tg.blocked_chats.add(USER)
    assert (await notify.run_once(penv.session, client_for=await client_for_factory(penv)))["expired"] == 1
    assert (await rows(penv, PaidSub))[0].status == "expired"


# ------------------------------------------------------------------ admin panel

async def test_admin_creates_plan_edits_it_and_links_channels(penv):
    await send(penv, admin_added())
    await send(penv, message("/admin", user=OWNER))
    assert "pa:pl" in datas(penv.tg.last())
    await send(penv, cb("pa:pn", user=OWNER))
    await send(penv, message("1 oylik", user=OWNER))
    await send(penv, message("nol", user=OWNER))
    assert "❌" in penv.tg.texts(OWNER)[-1]
    await send(penv, message("30", user=OWNER))
    await send(penv, message("99 000", user=OWNER))
    (plan,) = await rows(penv, PaidPlan)
    assert (plan.title, plan.days, plan.price) == ("1 oylik", 30, 99_000)
    assert len(await rows(penv, PaidPlanChannel)) == 1  # linked to the existing channel
    await send(penv, cb(f"pa:pe:{plan.id}:price", user=OWNER))
    await send(penv, message("149000", user=OWNER))
    await send(penv, cb(f"pa:pe:{plan.id}:desc", user=OWNER))
    await send(penv, message("Hammasi shu yerda", user=OWNER))
    await penv.session.refresh(plan)
    assert plan.price == 149_000 and plan.description == "Hammasi shu yerda"
    ch = (await rows(penv, PaidChannel))[0]
    await send(penv, cb(f"pa:pc:{plan.id}:{ch.id}", user=OWNER))
    assert await rows(penv, PaidPlanChannel) == []  # toggled off
    await send(penv, cb(f"pa:pt:{plan.id}", user=OWNER))
    await penv.session.refresh(plan)
    assert plan.is_active is False
    await send(penv, message("/start"))
    await send(penv, cb("pc:plans"))
    assert f"pc:p:{plan.id}" not in datas(penv.tg.last("edit_message_text"))  # paused plans are not sold


async def test_deleting_a_plan_with_history_only_pauses_it(penv):
    used = await make_plan(penv, "Eski")
    await subscribe(penv, used)
    fresh = await make_plan(penv, "Yangi")
    await send(penv, cb(f"pa:pd2:{used.id}", user=OWNER))
    await send(penv, cb(f"pa:pd2:{fresh.id}", user=OWNER))
    left = await rows(penv, PaidPlan)
    assert [p.title for p in left] == ["Eski"] and left[0].is_active is False


async def test_admin_manages_subscribers(penv):
    plan = await make_plan(penv)
    sub = await subscribe(penv, plan, days=10)
    before = core.as_utc(sub.expires_at)
    await send(penv, cb("pa:subs:a:0", user=OWNER))
    assert f"pa:s:{sub.id}" in datas(penv.tg.last("edit_message_text"))
    await send(penv, cb(f"pa:sx:{sub.id}:7", user=OWNER))
    await penv.session.refresh(sub)
    assert core.as_utc(sub.expires_at) - before == timedelta(days=7)
    await send(penv, cb(f"pa:sl:{sub.id}", user=OWNER))
    assert urls([c for c in penv.tg.of("send_message") if c["chat_id"] == USER][-1])
    await send(penv, cb(f"pa:sc2:{sub.id}", user=OWNER))
    await penv.session.refresh(sub)
    assert sub.status == "cancelled" and penv.tg.of("ban_chat_member") == [{"chat_id": CH1, "user_id": USER}]


async def test_manual_grant_by_telegram_id(penv):
    plan = await make_plan(penv)
    await send(penv, cb("pa:gr", user=OWNER))
    await send(penv, message("abc", user=OWNER))
    assert "❌" in penv.tg.texts(OWNER)[-1]
    await send(penv, message("5551234", user=OWNER))
    choice = penv.tg.of("send_message")[-1]
    assert datas(choice) == [f"pa:gp:{plan.id}:5551234", "pa:subs:a:0"]
    await send(penv, cb(f"pa:gp:{plan.id}:5551234", user=OWNER))
    (sub,) = await rows(penv, PaidSub)
    assert sub.tg_user_id == 5551234 and sub.status == "active"


async def test_admin_creates_and_toggles_promo(penv):
    await send(penv, cb("pa:prn", user=OWNER))
    await send(penv, message("a", user=OWNER))
    assert "❌" in penv.tg.texts(OWNER)[-1]
    await send(penv, message("Qish-20", user=OWNER))
    await send(penv, message("20%", user=OWNER))
    await send(penv, message("/skip", user=OWNER))
    (p,) = await rows(penv, PaidPromo)
    assert (p.code, p.percent, p.amount, p.max_uses) == ("QISH-20", 20, None, None)
    await send(penv, cb("pa:prn", user=OWNER))
    await send(penv, message("qish-20", user=OWNER))
    assert "allaqachon" in penv.tg.texts(OWNER)[-1]
    await send(penv, cb(f"pa:pro:{p.id}:t", user=OWNER))
    assert (await rows(penv, PaidPromo))[0].is_active is False
    await send(penv, cb(f"pa:pro:{p.id}:d", user=OWNER))
    assert await rows(penv, PaidPromo) == []


async def test_settings_and_trial_configuration(penv):
    plan = await make_plan(penv)
    await send(penv, cb("pa:se:card", user=OWNER))
    await send(penv, message("9860 0000 1111 2222", user=OWNER))
    assert (await core.get_settings(penv.session, penv.bot.id)).card_number == "9860 0000 1111 2222"
    await send(penv, cb("pa:trt", user=OWNER))
    await send(penv, cb(f"pa:trs:{plan.id}", user=OWNER))
    await send(penv, cb("pa:trd", user=OWNER))
    await send(penv, message("5", user=OWNER))
    st = await core.get_settings(penv.session, penv.bot.id)
    await penv.session.refresh(st)
    assert (st.trial_enabled, st.trial_plan_id, st.trial_days) == (True, plan.id, 5)


async def test_statistics_show_revenue(penv):
    plan = await make_plan(penv)
    pay = await buy(penv, plan)
    await send(penv, cb(f"pa:pok:{pay.id}", user=OWNER, caption=True))
    await send(penv, cb("pa:stats", user=OWNER))
    text = penv.tg.last("edit_message_text")["text"]
    assert "100 000" in text and "Faol: <b>1</b>" in text


async def test_non_admin_cannot_use_admin_panel(penv):
    plan = await make_plan(penv)
    pay = await buy(penv, plan)
    await send(penv, cb(f"pa:pok:{pay.id}", user=999))
    await send(penv, message("/admin", user=999))
    assert not await rows(penv, PaidSub)
    assert (await rows(penv, PaidPayment))[0].status == "pending"


async def test_my_subscription_screen_and_links(penv):
    plan = await make_plan(penv)
    await send(penv, cb("pc:my"))
    assert "Hali obunangiz yo‘q" in penv.tg.last("edit_message_text")["text"]
    await send(penv, cb("pc:links"))
    assert "Faol obunangiz yo‘q" in penv.tg.last("edit_message_text")["text"]
    await subscribe(penv, plan)
    await send(penv, cb("pc:my"))
    assert "pc:links" in datas(penv.tg.last("edit_message_text"))
    await send(penv, cb("pc:links"))
    assert urls(penv.tg.last())


async def test_other_bot_kinds_ignore_paid_callbacks(env):
    await send(env, cb("pc:plans"))
    assert not env.tg.of("edit_message_text")
