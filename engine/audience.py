"""Who uses a child bot: tracking and statistics."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.logger import get_logger
from models.audience import Broadcast, BotUser
from models.forms import FormSubmission

logger = get_logger("audience")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(value, size):
    return value[:size] if value else None


async def touch_user(session, bot_id: int, tg_user: dict, *, source: str | None = None) -> None:
    """Record that this person just used the bot (creating them on first contact).
    Seeing them again also clears ``is_blocked``: they obviously can read our messages."""
    user_id = tg_user.get("id")
    if user_id is None or tg_user.get("is_bot"):
        return
    full_name = " ".join(p for p in (tg_user.get("first_name"), tg_user.get("last_name")) if p) or None
    row = (await session.execute(
        select(BotUser).where(BotUser.bot_id == bot_id, BotUser.tg_user_id == user_id)
    )).scalar_one_or_none()
    if row is None:
        session.add(BotUser(
            bot_id=bot_id, tg_user_id=user_id, username=_clip(tg_user.get("username"), 255),
            full_name=_clip(full_name, 255), language_code=_clip(tg_user.get("language_code"), 16),
            source=_clip(source, 64), first_seen_at=_now(), last_seen_at=_now(),
        ))
        try:
            await session.commit()
        except IntegrityError:  # a parallel update created the row first
            await session.rollback()
        return
    row.username = _clip(tg_user.get("username"), 255)
    row.full_name = _clip(full_name, 255) or row.full_name
    row.is_blocked = False
    row.last_seen_at = _now()
    await session.commit()


async def set_blocked(session, bot_id: int, tg_user_id: int, blocked: bool = True) -> None:
    row = (await session.execute(
        select(BotUser).where(BotUser.bot_id == bot_id, BotUser.tg_user_id == tg_user_id)
    )).scalar_one_or_none()
    if row is not None and row.is_blocked != blocked:
        row.is_blocked = blocked
        await session.commit()


async def stats(session, bot_id: int, *, now: datetime | None = None) -> dict:
    now = now or _now()
    day, week, month = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)

    async def count(*conditions):
        return (await session.execute(
            select(func.count(BotUser.id)).where(BotUser.bot_id == bot_id, *conditions)
        )).scalar_one()

    blocked = await count(BotUser.is_blocked.is_(True))
    total = await count()
    submissions = (await session.execute(
        select(func.count(FormSubmission.id)).where(FormSubmission.bot_id == bot_id)
    )).scalar_one()
    sent = (await session.execute(
        select(func.coalesce(func.sum(Broadcast.sent), 0)).where(Broadcast.bot_id == bot_id)
    )).scalar_one()
    sources = (await session.execute(
        select(BotUser.source, func.count(BotUser.id)).where(BotUser.bot_id == bot_id, BotUser.source.is_not(None))
        .group_by(BotUser.source).order_by(func.count(BotUser.id).desc()).limit(5)
    )).all()
    return {
        "total": total,
        "active": total - blocked,
        "blocked": blocked,
        "new_24h": await count(BotUser.first_seen_at >= day),
        "new_7d": await count(BotUser.first_seen_at >= week),
        "new_30d": await count(BotUser.first_seen_at >= month),
        "active_24h": await count(BotUser.last_seen_at >= day),
        "active_7d": await count(BotUser.last_seen_at >= week),
        "submissions": submissions,
        "broadcast_messages": int(sent or 0),
        "sources": [(s, n) for s, n in sources],
    }
