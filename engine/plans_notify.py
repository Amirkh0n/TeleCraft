"""Plan clock, run by the main bot: reminders 3 and 1 days before a plan or bot licence ends, the grace-period
and downgrade notices, and a one-time warning when a bot reaches its user cap. Every notice goes out once
(``core.plans.claim_notice``). Run a single instance of the app."""
import asyncio
import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from core import plans
from core.config import settings
from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine.booking_time import as_utc, utcnow
from models.bots import Bot
from models.plans import AccountPlan, BotLicense
from models.users import User

TZ = ZoneInfo("Asia/Tashkent")
logger = get_logger("plans.notify")
INTERVAL = 600
MARKUP = Markup([[Btn("💳 Uzaytirish", callback_data="plx:home")]])


def _stage(end, now):
    """Which notice an end date calls for right now: rem3 / rem1 / grace / down, or None."""
    if now <= end:
        days = math.ceil((end - now) / timedelta(days=1))
        return "rem1" if days <= 1 else "rem3" if days <= 3 else None
    return "grace" if now <= end + timedelta(days=plans.GRACE_DAYS) else "down"


def _text(stage: str, what: str, end) -> str:
    when = as_utc(end).astimezone(TZ).strftime("%d.%m.%Y")
    if stage in ("rem3", "rem1"):
        left = "ertaga" if stage == "rem1" else "3 kundan so‘ng"
        return f"⏰ {what} {left} tugaydi ({when}). Uzluksiz ishlashi uchun uzaytiring."
    if stage == "grace":
        return (f"⌛️ {what} muddati {when} da tugadi. {plans.GRACE_DAYS} kunlik imtiyoz davom etmoqda: "
                "shu vaqtda uzaytirmasangiz, Free tarif cheklovlari qo‘llanadi (ma’lumotlar saqlanadi).")
    return (f"🔒 {what} uzaytirilmadi, Free tarif cheklovlari yoqildi. Ma’lumotlaringiz saqlanib qoldi: "
            "istalgan vaqtda to‘lab, hammasini qayta oching.")


async def run_once(session, send, *, now=None) -> int:
    """``send(tg_id, text, markup)`` delivers one message. Returns how many notices went out."""
    now = now or utcnow()
    sent = 0

    async def notify(key, tg_id, text):
        nonlocal sent
        if not await plans.claim_notice(session, key):
            return
        try:
            await send(tg_id, text, MARKUP)
            sent += 1
        except Exception as exc:
            logger.info("plan notice %s not delivered: %s", key, exc)

    for acc, tg_id in (await session.execute(
            select(AccountPlan, User.tg_id).join(User, User.id == AccountPlan.user_id))).all():
        if plans.is_platform_admin(tg_id):
            continue
        end = as_utc(acc.expires_at)
        stage = _stage(end, now)
        if stage:
            await notify(f"{stage}:acc:{acc.id}:{end:%Y%m%d%H}", tg_id,
                         _text(stage, f"<b>{plans.PLANS[acc.plan].title}</b> tarifingiz", end))
    for lic, bot, tg_id in (await session.execute(
            select(BotLicense, Bot, User.tg_id).join(Bot, Bot.id == BotLicense.bot_id)
            .join(User, User.id == Bot.owner_id))).all():
        if plans.is_platform_admin(tg_id):
            continue
        end = as_utc(lic.expires_at)
        stage = _stage(end, now)
        if stage:
            await notify(f"{stage}:lic:{lic.id}:{end:%Y%m%d%H}", tg_id,
                         _text(stage, f"<b>{bot.name}</b> botining alohida to‘lovi", end))
    for bot, tg_id in (await session.execute(
            select(Bot, User.tg_id).join(User, User.id == Bot.owner_id).where(Bot.is_active.is_(True)))).all():
        limits = await plans.bot_limits(session, bot, now, use_cache=False)
        if limits.full and limits.user_cap:
            await notify(f"full:{bot.id}:{limits.user_cap}", tg_id,
                         f"📈 <b>{bot.name}</b> botida {limits.user_cap} ta foydalanuvchi limiti to‘ldi. "
                         "Yangi foydalanuvchilar qabul qilinmayapti. Tarifni oshiring yoki botni alohida oching.")
    return sent


async def loop(get_bot, interval: int = INTERVAL, session_factory=AsyncSessionLocal) -> None:
    logger.info("Plan clock started")
    while True:
        try:
            tg = get_bot()
            if tg is not None and settings.PLANS_ENFORCE:
                async def send(tg_id, text, markup):
                    await tg.send_message(chat_id=tg_id, text=text, parse_mode="HTML", reply_markup=markup)

                async with session_factory() as session:
                    await run_once(session, send)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Plan clock tick failed")
        await asyncio.sleep(interval)
