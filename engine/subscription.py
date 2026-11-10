"""Forced subscription: a user must be a member of the owner's channels before using the bot.

Membership is checked with ``getChatMember`` (the child bot must be an administrator of the
channel). If the check itself fails — bot not admin, channel deleted — the user is let in:
a misconfigured channel must never lock everybody out.
"""
import time

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from core.logger import get_logger
from engine.render import send_text
from models.audience import RequiredChannel

logger = get_logger("subscription")

CHECK_CALLBACK = "chk"
JOINED_STATUSES = {"member", "administrator", "creator"}
CACHE_SECONDS = 60
_ok_cache: dict[tuple, float] = {}


def channel_url(channel) -> str | None:
    if channel.invite_link:
        return channel.invite_link
    if channel.username:
        return f"https://t.me/{channel.username.lstrip('@')}"
    return None


def is_joined(member) -> bool:
    status = getattr(member, "status", None)
    if status in JOINED_STATUSES:
        return True
    return status == "restricted" and bool(getattr(member, "is_member", False))


async def channels_of(session, bot_id: int) -> list:
    return list((await session.execute(
        select(RequiredChannel).where(RequiredChannel.bot_id == bot_id).order_by(RequiredChannel.position, RequiredChannel.id)
    )).scalars().all())


async def missing_channels(tg, session, bot_id: int, user_id: int, *, use_cache: bool = True) -> list:
    missing = []
    now = time.monotonic()
    for channel in await channels_of(session, bot_id):
        key = (bot_id, user_id, channel.chat_id)
        if use_cache and _ok_cache.get(key, 0) > now:
            continue
        try:
            member = await tg.get_chat_member(chat_id=channel.chat_id, user_id=user_id)
        except TelegramError as exc:
            logger.warning("bot_id=%s: cannot check channel %s (%s); letting the user in", bot_id, channel.chat_id, exc)
            continue
        if is_joined(member):
            _ok_cache[key] = now + CACHE_SECONDS
        else:
            _ok_cache.pop(key, None)
            missing.append(channel)
    return missing


def prompt_markup(missing) -> InlineKeyboardMarkup:
    rows = []
    for channel in missing:
        url = channel_url(channel)
        if url:
            rows.append([InlineKeyboardButton(f"📢 {channel.title}", url=url)])
    rows.append([InlineKeyboardButton("✅ Tekshirish", callback_data=CHECK_CALLBACK)])
    return InlineKeyboardMarkup(rows)


async def gate(tg, bot, user_id: int, session, *, use_cache: bool = True) -> bool:
    """True if the user may continue. Otherwise the "please subscribe" screen was sent."""
    missing = await missing_channels(tg, session, bot.id, user_id, use_cache=use_cache)
    if not missing:
        return True
    await send_text(
        tg, user_id,
        "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling, so‘ng "
        "«✅ Tekshirish» tugmasini bosing.",
        reply_markup=prompt_markup(missing),
    )
    return False


async def describe_channel(tg, channel_ref: str):
    """Look a channel up by @username or numeric id. Returns ``(chat_id, title, username, problem)``
    where ``problem`` is a user-facing string if the bot cannot work with that channel."""
    try:
        chat = await tg.get_chat(chat_id=channel_ref)
    except TelegramError:
        return None, None, None, "Kanal topilmadi. @username to‘g‘ri yozilganini tekshiring."
    if chat.type not in ("channel", "supergroup", "group"):
        return None, None, None, "Bu kanal yoki guruh emas."
    try:
        me = await tg.get_me()
        member = await tg.get_chat_member(chat_id=chat.id, user_id=me.id)
    except TelegramError:
        return chat.id, chat.title, chat.username, "Bot bu kanalda administrator emas. Avval botni kanalga admin qiling."
    if getattr(member, "status", None) not in ("administrator", "creator"):
        return chat.id, chat.title, chat.username, "Bot bu kanalda administrator emas. Avval botni kanalga admin qiling."
    return chat.id, chat.title or str(chat.id), chat.username, None
