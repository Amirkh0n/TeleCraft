from datetime import timedelta

from engine import course_notify as notify
from engine.booking_time import utcnow
from models.course import Enrollment
from test_course import cr, make_course, row  # noqa: F401  (fixtures/builders)
from test_course import cb, datas  # noqa: F401
from helpers import USER, send
from constructor.flows.cinema import set_kind
from models.course import KIND_COURSE
from models.menus import Menu
from sqlalchemy import select


async def no_sleep(_):
    return None


async def client(_bot, tg=None):
    return tg


async def test_new_drip_lesson_announced_once(cr):
    c, ls = await make_course(cr, n=3, unlock="drip", drip_days=1)
    en = Enrollment(bot_id=cr.bot.id, course_id=c.id, tg_user_id=USER, user_name="Ali", enrolled_at=utcnow() - timedelta(days=1, hours=2))
    cr.session.add(en)
    await cr.session.commit()

    async def cf(bot):
        return cr.tg
    assert await notify.run_once(cr.session, client_for=cf, sleep=no_sleep) == 1
    msg = cr.tg.of("send_message")[-1]
    assert msg["chat_id"] == USER and "Dars 2" in msg["text"]
    assert f"cr:l:{ls[1].id}" in datas(cr, msg)
    assert await notify.run_once(cr.session, client_for=cf, sleep=no_sleep) == 0


async def test_downtime_sends_one_notice_for_latest(cr):
    c, ls = await make_course(cr, n=5, unlock="drip", drip_days=1)
    cr.session.add(Enrollment(bot_id=cr.bot.id, course_id=c.id, tg_user_id=USER, user_name="Ali", enrolled_at=utcnow() - timedelta(days=3, hours=1)))
    await cr.session.commit()

    async def cf(bot):
        return cr.tg
    assert await notify.run_once(cr.session, client_for=cf, sleep=no_sleep) == 1
    assert "Dars 4" in cr.tg.of("send_message")[-1]["text"]
    assert (await row(cr, Enrollment))[0].notified_count == 4


async def test_non_drip_and_unpublished_and_finished_are_skipped(cr):
    c1, _ = await make_course(cr, unlock="seq")
    c2, _ = await make_course(cr, unlock="drip", published=False)
    c3, _ = await make_course(cr, unlock="drip")
    old = utcnow() - timedelta(days=5)
    for c in (c1, c2, c3):
        cr.session.add(Enrollment(bot_id=cr.bot.id, course_id=c.id, tg_user_id=USER, enrolled_at=old, completed_at=old if c is c3 else None))
    await cr.session.commit()

    async def cf(bot):
        return cr.tg
    assert await notify.run_once(cr.session, client_for=cf, sleep=no_sleep) == 0


async def test_network_error_retries_blocked_user_does_not(cr):
    from telegram.error import Forbidden
    c, _ = await make_course(cr, n=2, unlock="drip")
    cr.session.add(Enrollment(bot_id=cr.bot.id, course_id=c.id, tg_user_id=USER, enrolled_at=utcnow() - timedelta(days=2)))
    await cr.session.commit()

    async def broken(bot):
        raise RuntimeError("network")
    assert await notify.run_once(cr.session, client_for=broken, sleep=no_sleep) == 0
    assert (await row(cr, Enrollment))[0].notified_count == 1  # will retry

    cr.tg.blocked_chats.add(USER)

    async def cf(bot):
        return cr.tg
    await notify.run_once(cr.session, client_for=cf, sleep=no_sleep)
    assert (await row(cr, Enrollment))[0].notified_count == 2  # not retried forever


async def test_toggle_course_mode_creates_menu_and_router(env):
    await set_kind(env.session, env.bot, KIND_COURSE)
    menu = (await env.session.execute(select(Menu))).scalar_one()
    assert menu.is_start and "Kurs botiga" in menu.message_text
    await send(env, __import__("helpers").message("/start"))
    assert any("cr:cat:0" in str(kw.get("reply_markup")) for kw in env.tg.of("send_message"))
