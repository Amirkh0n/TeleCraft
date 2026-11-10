"""Mass messages to a bot's audience.

* Runs as a background task; progress (cursor + counters) is committed every few users, so a
  restart resumes where it stopped (at most ``COMMIT_EVERY`` people may get the message twice).
* Respects Telegram limits: ~25 messages/second, ``RetryAfter`` pauses, and users who blocked
  the bot are marked ``is_blocked`` and skipped from then on.
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from core.logger import get_logger
from engine.render import CAPTION_LIMIT, send_media, send_text
from models.audience import (
    BROADCAST_CANCELLED, BROADCAST_DONE, BROADCAST_DRAFT, BROADCAST_SENDING, Broadcast, BotUser,
)

logger = get_logger("broadcast")

RATE_PER_SECOND = 25
COMMIT_EVERY = 10
MAX_ATTEMPTS = 3
_tasks: dict[int, asyncio.Task] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def markup_for(broadcast):
    if broadcast.button_text and broadcast.button_url:
        return InlineKeyboardMarkup([[InlineKeyboardButton(broadcast.button_text, url=broadcast.button_url)]])
    return None


async def deliver(tg, chat_id: int, broadcast) -> bool:
    """Send the broadcast to one chat. ``Forbidden`` (blocked) propagates; other Telegram
    refusals of the content return False."""
    markup = markup_for(broadcast)
    text = broadcast.text
    if broadcast.media_type and broadcast.media_file_id:
        if text and len(text) > CAPTION_LIMIT:
            if not await send_media(tg, chat_id, broadcast.media_type, broadcast.media_file_id):
                return False
            await send_text(tg, chat_id, text, reply_markup=markup)
            return True
        return await send_media(
            tg, chat_id, broadcast.media_type, broadcast.media_file_id, caption=text, reply_markup=markup
        )
    if not text:
        return False
    await send_text(tg, chat_id, text, reply_markup=markup)
    return True


async def audience_size(session, bot_id: int) -> int:
    return (await session.execute(
        select(func.count(BotUser.id)).where(BotUser.bot_id == bot_id, BotUser.is_blocked.is_(False))
    )).scalar_one()


async def create_draft(session, bot_id: int, created_by: int, **content) -> Broadcast:
    broadcast = Broadcast(bot_id=bot_id, created_by=created_by, status=BROADCAST_DRAFT, **content)
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    return broadcast


async def start(session, broadcast_id: int, *, spawn=True) -> str:
    """Begin sending. Returns ``"started"``, ``"busy"`` (another one is running) or ``"invalid"``."""
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None or broadcast.status != BROADCAST_DRAFT or not (broadcast.text or broadcast.media_file_id):
        return "invalid"
    busy = (await session.execute(
        select(Broadcast.id).where(Broadcast.bot_id == broadcast.bot_id, Broadcast.status == BROADCAST_SENDING)
    )).first()
    if busy:
        return "busy"
    broadcast.status = BROADCAST_SENDING
    broadcast.started_at = _now()
    broadcast.total = await audience_size(session, broadcast.bot_id)
    await session.commit()
    if spawn:
        spawn_task(broadcast.id)
    return "started"


async def cancel(session, broadcast_id: int) -> bool:
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None or broadcast.status not in (BROADCAST_DRAFT, BROADCAST_SENDING):
        return False
    broadcast.status = BROADCAST_CANCELLED
    broadcast.finished_at = _now()
    await session.commit()
    return True


def spawn_task(broadcast_id: int) -> None:
    task = _tasks.get(broadcast_id)
    if task and not task.done():
        return
    _tasks[broadcast_id] = asyncio.create_task(run(broadcast_id))
    _tasks[broadcast_id].add_done_callback(lambda t, i=broadcast_id: _tasks.pop(i, None))


async def resume_pending() -> int:
    """After a restart: continue broadcasts that were interrupted."""
    from core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        ids = (await session.execute(
            select(Broadcast.id).where(Broadcast.status == BROADCAST_SENDING)
        )).scalars().all()
    for broadcast_id in ids:
        spawn_task(broadcast_id)
    return len(ids)


async def _send_one(tg, chat_id, broadcast, sleep) -> str:
    """``"sent"``, ``"blocked"`` or ``"failed"``."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return "sent" if await deliver(tg, chat_id, broadcast) else "failed"
        except Forbidden:
            return "blocked"
        except RetryAfter as exc:
            wait = exc.retry_after
            await sleep((wait.total_seconds() if hasattr(wait, "total_seconds") else float(wait)) + 1)
        except BadRequest as exc:
            return "blocked" if "chat not found" in str(exc).lower() else "failed"
        except TelegramError as exc:  # network hiccup, 5xx: retry a couple of times
            logger.info("broadcast send to %s failed (attempt %s): %s", chat_id, attempt + 1, exc)
            await sleep(1 + attempt)
    return "failed"


async def run(broadcast_id: int, *, client=None, session_factory=None, sleep=asyncio.sleep, rate=RATE_PER_SECOND) -> None:
    """Send to everyone not yet handled. Safe to call again after a crash."""
    from core.database import AsyncSessionLocal
    from engine.telegram_client import get_client
    session_factory = session_factory or AsyncSessionLocal
    delay = 1 / rate if rate else 0

    try:
        async with session_factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None or broadcast.status != BROADCAST_SENDING:
                return
            from models.bots import Bot
            bot = await session.get(Bot, broadcast.bot_id)
            tg = client or await get_client(bot.plain_token)

            while True:
                batch = (await session.execute(
                    select(BotUser).where(
                        BotUser.bot_id == broadcast.bot_id, BotUser.is_blocked.is_(False),
                        BotUser.id > broadcast.cursor,
                    ).order_by(BotUser.id).limit(COMMIT_EVERY)
                )).scalars().all()
                if not batch:
                    break
                for user in batch:
                    outcome = await _send_one(tg, user.tg_user_id, broadcast, sleep)
                    if outcome == "sent":
                        broadcast.sent += 1
                    elif outcome == "blocked":
                        broadcast.blocked += 1
                        user.is_blocked = True
                    else:
                        broadcast.failed += 1
                    broadcast.cursor = user.id
                    if delay:
                        await sleep(delay)
                await session.commit()
                await session.refresh(broadcast)  # picks up a cancellation made meanwhile
                if broadcast.status != BROADCAST_SENDING:
                    return

            broadcast.status = BROADCAST_DONE
            broadcast.finished_at = _now()
            await session.commit()
    except Exception:
        logger.exception("broadcast %s crashed; it will resume on the next start", broadcast_id)


def summary(broadcast) -> str:
    done = broadcast.sent + broadcast.failed + broadcast.blocked
    state = {
        BROADCAST_DRAFT: "📝 Qoralama", BROADCAST_SENDING: "⏳ Yuborilmoqda",
        BROADCAST_DONE: "✅ Tugadi", BROADCAST_CANCELLED: "🛑 To‘xtatildi",
    }.get(broadcast.status, broadcast.status)
    return (
        f"{state}\n"
        f"Yuborildi: {broadcast.sent}\n"
        f"Bloklaganlar: {broadcast.blocked}\n"
        f"Xato: {broadcast.failed}\n"
        f"Jarayon: {done}/{broadcast.total}"
    )
