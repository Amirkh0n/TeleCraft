from datetime import timedelta

from sqlalchemy import select
from telegram.error import Forbidden, NetworkError

from engine import booking_reminders as rem
from engine.booking_time import utcnow
from helpers import USER
from models.booking import Booking
from test_booking import shop  # noqa: F401  (fixture)


async def no_sleep(_):
    return None


def make(env, minutes_ahead, status="confirmed", user=USER):
    start = utcnow() + timedelta(minutes=minutes_ahead)
    b = Booking(bot_id=env.bot.id, service_id=env.service.id, tg_user_id=user, client_name="Ali", phone="+998901234567",
                service_name="Soch olish", price=50000, start_at=start, end_at=start + timedelta(minutes=30), status=status,
                reminders_sent=[])
    env.session.add(b)
    return b


async def tick(env, **kw):
    async def client_for(bot):
        return env.tg
    return await rem.run_once(env.session, client_for=client_for, sleep=no_sleep, **kw)


def reminders_to(env, user=USER):
    return [c for c in env.tg.of("send_message") if c["chat_id"] == user and "Eslatma" in c["text"]]


async def test_each_offset_is_sent_once_when_due(shop):
    b = make(shop, 3 * 60)  # visit in 3 hours; reminders: 1 day and 1 hour before
    await shop.session.commit()
    assert await tick(shop) == 1 and len(reminders_to(shop)) == 1  # the 1-day one is already due
    assert await tick(shop) == 0
    assert b.reminders_sent == [1440]
    assert await tick(shop, now=utcnow() + timedelta(minutes=125)) == 1  # now 55 minutes remain
    assert b.reminders_sent == [1440, 60] and len(reminders_to(shop)) == 2
    assert await tick(shop, now=utcnow() + timedelta(minutes=140)) == 0


async def test_overdue_offsets_send_only_one_message(shop):
    b = make(shop, 30)
    await shop.session.commit()
    assert await tick(shop) == 1
    assert b.reminders_sent == [1440, 60] and len(reminders_to(shop)) == 1
    assert "30 daqiqa" in reminders_to(shop)[0]["text"]
    assert "bk:c:" in reminders_to(shop)[0]["reply_markup"].inline_keyboard[0][0].callback_data


async def test_only_confirmed_future_bookings_get_reminders(shop):
    make(shop, 30, status="pending")
    make(shop, 30, status="cancelled")
    make(shop, -30)  # already started
    make(shop, 20 * 24 * 60)  # beyond the horizon
    await shop.session.commit()
    assert await tick(shop) == 0 and not reminders_to(shop)


async def test_reminders_can_be_switched_off_and_changed(shop):
    shop.settings.reminders = []
    make(shop, 30)
    await shop.session.commit()
    assert await tick(shop) == 0
    shop.settings.reminders = [45]  # admin decides: 45 minutes before only
    await shop.session.commit()
    assert await tick(shop) == 1  # 30 min left: the 45-minute offset is already due
    b2 = make(shop, 200)
    await shop.session.commit()
    assert await tick(shop) == 0 and b2.reminders_sent == []
    assert await tick(shop, now=utcnow() + timedelta(minutes=170)) == 1


async def test_blocked_user_is_marked_and_does_not_break_the_loop(shop):
    blocked = make(shop, 30, user=111)
    ok = make(shop, 40)
    await shop.session.commit()
    real = shop.tg.send_message

    async def send(**kw):
        if kw["chat_id"] == 111:
            raise Forbidden("bot was blocked by the user")
        return await real(**kw)
    shop.tg.send_message = send
    assert await tick(shop) == 1
    assert blocked.reminders_sent and ok.reminders_sent  # nothing is retried forever
    assert len(reminders_to(shop)) == 1


async def test_network_error_is_retried_next_tick(shop):
    b = make(shop, 30)
    await shop.session.commit()
    real = shop.tg.send_message
    calls = {"n": 0}

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise NetworkError("timeout")
        return await real(**kw)
    shop.tg.send_message = flaky
    assert await tick(shop) == 0 and b.reminders_sent == []
    assert await tick(shop) == 1 and b.reminders_sent


async def test_other_bot_kinds_are_ignored(shop):
    make(shop, 30)
    shop.bot.kind = "standard"
    await shop.session.commit()
    assert await tick(shop) == 0


async def test_loop_survives_errors_and_can_be_cancelled(shop):
    import asyncio
    ticks = {"n": 0}

    class Ctx:
        async def __aenter__(self):
            ticks["n"] += 1
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False
    task = asyncio.create_task(rem.loop(interval=0.01, session_factory=Ctx))
    await asyncio.sleep(0.1)
    assert ticks["n"] >= 2 and not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled()
    assert (await shop.session.execute(select(Booking))).first() is None
