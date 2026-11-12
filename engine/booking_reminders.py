"""Reminders for confirmed bookings, sent by a background loop started with the app.

The admin chooses the offsets (``BookingSettings.reminders``, e.g. 1 day and 2 hours before).
Each offset is sent at most once per booking (``Booking.reminders_sent``). After downtime several
offsets may be overdue at once: only the closest one is sent and all of them are marked as sent,
so the client never gets a burst of stale reminders. Run a single instance of the app.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, Forbidden

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import booking as core
from engine.booking_time import as_utc, fmt_minutes, tz_of, utcnow
from engine.telegram_client import get_client
from models.booking import CONFIRMED, Booking, BookingSettings
from models.bots import Bot

logger = get_logger("booking.reminders")
HORIZON = timedelta(days=14)
INTERVAL = 60


async def _default_client(bot):
    return await get_client(bot.plain_token)


async def run_once(session, *, now=None, client_for=_default_client, sleep=asyncio.sleep) -> int:
    """Send every reminder that is due. Returns how many were sent."""
    now = now or utcnow()
    rows = (await session.execute(
        select(Booking, BookingSettings, Bot)
        .join(BookingSettings, BookingSettings.bot_id == Booking.bot_id)
        .join(Bot, Bot.id == Booking.bot_id)
        .where(Booking.status == CONFIRMED, Booking.start_at > now, Booking.start_at <= now + HORIZON,
               Bot.is_active.is_(True), Bot.kind == "booking")
        .order_by(Booking.start_at)
    )).all()
    sent_count = 0
    for booking, st, bot in rows:
        start = as_utc(booking.start_at)
        already = set(booking.reminders_sent or [])
        due = [m for m in (st.reminders or []) if m not in already and start - timedelta(minutes=m) <= now]
        if not due:
            continue
        remaining = max(1, round((start - now).total_seconds() / 60))
        text = (f"⏰ <b>Eslatma:</b> broningizga {fmt_minutes(remaining)} qoldi.\n\n"
                f"{core.card(booking, tz_of(st.timezone))}")
        markup = Markup([[Btn("❌ Bekor qilish", callback_data=f"bk:c:{booking.id}")]])
        try:
            tg = await client_for(bot)
            await tg.send_message(chat_id=booking.tg_user_id, text=text, parse_mode="HTML", reply_markup=markup)
            sent_count += 1
        except (Forbidden, BadRequest) as exc:  # blocked the bot / chat gone: retrying will not help
            logger.info("reminder for booking %s not deliverable: %s", booking.id, exc)
        except Exception as exc:  # network trouble: try again on the next tick
            logger.warning("reminder for booking %s failed, will retry: %s", booking.id, exc)
            continue
        booking.reminders_sent = sorted(already | set(due), reverse=True)
        await session.commit()
        await sleep(0.05)
    return sent_count


async def loop(interval: int = INTERVAL, session_factory=AsyncSessionLocal) -> None:
    logger.info("Booking reminder loop started")
    while True:
        try:
            async with session_factory() as session:
                await run_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Booking reminder tick failed")
        await asyncio.sleep(interval)
