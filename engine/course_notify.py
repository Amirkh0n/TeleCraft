"""Scheduled courses: tells students when a new lesson has opened, from a background loop.

``Enrollment.notified_count`` is how many lessons the student has already been told about. After
downtime several lessons may have opened at once: one message announces the newest one, so nobody
gets a burst of stale notices. Run a single instance of the app.
"""
import asyncio

from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, Forbidden

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import course as core, course_logic as logic
from engine.booking_time import fmt_dt, tz_of, utcnow
from engine.telegram_client import get_client
from models.bots import Bot
from models.course import UNLOCK_DRIP, Course, CourseSettings, Enrollment

logger = get_logger("course.notify")
INTERVAL = 120


async def _default_client(bot):
    return await get_client(bot.plain_token)


async def run_once(session, *, now=None, client_for=_default_client, sleep=asyncio.sleep) -> int:
    """Announce every newly opened lesson. Returns how many notices were sent."""
    now = now or utcnow()
    rows = (await session.execute(
        select(Enrollment, Course, CourseSettings, Bot)
        .join(Course, Course.id == Enrollment.course_id)
        .join(CourseSettings, CourseSettings.bot_id == Enrollment.bot_id)
        .join(Bot, Bot.id == Enrollment.bot_id)
        .where(Course.unlock_mode == UNLOCK_DRIP, Course.is_published.is_(True), Enrollment.completed_at.is_(None),
               Bot.is_active.is_(True), Bot.kind == "course")
        .order_by(Enrollment.id)
    )).all()
    lessons_cache: dict = {}
    sent = 0
    for en, course, st, bot in rows:
        if course.id not in lessons_cache:
            lessons_cache[course.id] = await core.lessons_of(session, course.id)
        lessons = lessons_cache[course.id]
        opened = logic.unlocked_count(UNLOCK_DRIP, [False] * len(lessons), enrolled_at=en.enrolled_at, now=now,
                                      drip_days=course.drip_days, drip_hour=st.drip_hour, tz=tz_of(st.timezone))
        if opened <= en.notified_count:
            continue
        lesson = lessons[opened - 1]
        nxt = logic.next_open_at(UNLOCK_DRIP, opened, len(lessons), enrolled_at=en.enrolled_at,
                                 drip_days=course.drip_days, drip_hour=st.drip_hour, tz=tz_of(st.timezone))
        text = f"🔔 <b>{core.esc(course.title)}</b>\nYangi dars ochildi: <b>{core.esc(lesson.title)}</b>"
        if nxt:
            text += f"\n⏰ Keyingisi: {fmt_dt(nxt, tz_of(st.timezone))}"
        try:
            tg = await client_for(bot)
            await tg.send_message(chat_id=en.tg_user_id, text=text, parse_mode="HTML",
                                  reply_markup=Markup([[Btn("▶️ Darsni ochish", callback_data=f"cr:l:{lesson.id}")]]))
            sent += 1
        except (Forbidden, BadRequest) as exc:  # blocked the bot: retrying will not help
            logger.info("lesson notice for enrollment %s not deliverable: %s", en.id, exc)
        except Exception as exc:  # network trouble: try again on the next tick
            logger.warning("lesson notice for enrollment %s failed, will retry: %s", en.id, exc)
            continue
        en.notified_count = opened
        await session.commit()
        await sleep(0.05)
    return sent


async def loop(interval: int = INTERVAL, session_factory=AsyncSessionLocal) -> None:
    logger.info("Course notification loop started")
    while True:
        try:
            async with session_factory() as session:
                await run_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Course notification tick failed")
        await asyncio.sleep(interval)
