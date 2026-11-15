"""Subscription clock of paid-channel bots: reminders 3 and 1 days before the end, and removal from the
channels when a subscription has expired (the user is kicked without a permanent ban and offered a renewal).
Run a single instance of the app."""
import asyncio

from sqlalchemy import select, update
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import paid as core, paid_logic as logic
from engine.booking_time import as_utc, utcnow
from engine.telegram_client import get_client
from models.bots import Bot
from models.paid import SUB_ACTIVE, SUB_EXPIRED, PaidPlan, PaidSub

logger = get_logger("paid.notify")
INTERVAL = 120


async def _default_client(bot):
    return await get_client(bot.plain_token)


def _extend_markup():
    return Markup([[Btn("🔄 Uzaytirish", callback_data="pc:plans")]])


async def run_once(session, *, now=None, client_for=_default_client, sleep=asyncio.sleep) -> dict:
    """Send due reminders and expire ended subscriptions. Returns ``{"reminded": n, "expired": n}``."""
    now = now or utcnow()
    done = {"reminded": 0, "expired": 0}
    rows = (await session.execute(
        select(PaidSub, PaidPlan, Bot).join(PaidPlan, PaidPlan.id == PaidSub.plan_id).join(Bot, Bot.id == PaidSub.bot_id)
        .where(PaidSub.status == SUB_ACTIVE, Bot.is_active.is_(True), Bot.kind == "paid").order_by(PaidSub.id))).all()
    for sub, plan, bot in rows:
        try:
            tg = await client_for(bot)
            if as_utc(sub.expires_at) <= now:
                done["expired"] += await _expire(tg, session, bot, sub, plan, now)
                continue
            which = logic.reminder_due(sub.expires_at, now, sub.reminded_3, sub.reminded_1)
            if which is None:
                continue
            left = logic.days_left(sub.expires_at, now)
            text = (f"⏰ <b>{core.esc(plan.title)}</b> obunangiz {left} kundan so‘ng tugaydi "
                    f"({core.when(sub.expires_at)}).\nUzluksiz foydalanish uchun uzaytiring.")
            try:
                await tg.send_message(chat_id=sub.tg_user_id, text=text, parse_mode="HTML", reply_markup=_extend_markup())
                done["reminded"] += 1
            except TelegramError as exc:  # blocked the bot: do not retry forever
                logger.info("reminder to %s not delivered: %s", sub.tg_user_id, exc)
            sub.reminded_1 = sub.reminded_1 or which == 1
            sub.reminded_3 = sub.reminded_3 or which in (3, 1)
            await session.commit()
            await sleep(0.05)
        except Exception:
            logger.exception("paid: clock failed for subscription %s", sub.id)
            await session.rollback()
    return done


async def _expire(tg, session, bot, sub, plan, now) -> int:
    claimed = await session.execute(
        update(PaidSub).where(PaidSub.id == sub.id, PaidSub.status == SUB_ACTIVE, PaidSub.expires_at <= now)
        .values(status=SUB_EXPIRED))
    await session.commit()
    if claimed.rowcount == 0:
        return 0
    keep = {c.id for c in await core.access_channels(session, bot.id, sub.tg_user_id, now, skip_sub=sub.id)}
    gone = [c for c in await core.plan_channels(session, plan.id, active_only=False) if c.id not in keep]
    await core.remove_from(tg, gone, sub.tg_user_id)
    try:
        await tg.send_message(chat_id=sub.tg_user_id, parse_mode="HTML", reply_markup=Markup(
            [[Btn("💳 Qayta to‘lash", callback_data=f"pc:p:{plan.id}")]]),
            text=f"⌛️ <b>{core.esc(plan.title)}</b> obunangiz tugadi" + (" va kanaldan chiqarildingiz" if gone else "") + ".\nQayta qo‘shilish uchun obunani yangilang.")
    except TelegramError as exc:
        logger.info("expiry notice to %s not delivered: %s", sub.tg_user_id, exc)
    return 1


async def loop(interval: int = INTERVAL, session_factory=AsyncSessionLocal) -> None:
    logger.info("Paid subscription loop started")
    while True:
        try:
            async with session_factory() as session:
                await run_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Paid subscription tick failed")
        await asyncio.sleep(interval)
