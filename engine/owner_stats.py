"""Statistics for a bot's owner: growth, activity, popular buttons, broadcasts and the plan's user cap."""
from datetime import timedelta

from sqlalchemy import func, select

from engine import audience
from models.analytics import AnalyticsEvent
from models.audience import BotUser, Broadcast
from models.buttons import Button

DAYS = 14
TOP = 8


async def overview(session, bot, limits=None, *, now=None) -> dict:
    now = now or audience._now()
    data = await audience.stats(session, bot.id, now=now)
    start = (now - timedelta(days=DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    firsts = (await session.execute(select(BotUser.first_seen_at).where(BotUser.bot_id == bot.id, BotUser.first_seen_at >= start))).scalars().all()
    per_day = {}
    for stamp in firsts:
        per_day[stamp.date().isoformat()] = per_day.get(stamp.date().isoformat(), 0) + 1
    data["daily"] = [{"day": (start + timedelta(days=i)).date().isoformat(), "new": per_day.get((start + timedelta(days=i)).date().isoformat(), 0)} for i in range(DAYS)]

    since = now - timedelta(days=30)
    rows = (await session.execute(
        select(Button.text, func.count(AnalyticsEvent.id).label("n"))
        .join(Button, Button.id == AnalyticsEvent.button_id)
        .where(AnalyticsEvent.bot_id == bot.id, AnalyticsEvent.event_type == "click", AnalyticsEvent.created_at >= since)
        .group_by(Button.text).order_by(func.count(AnalyticsEvent.id).desc(), Button.text).limit(TOP)
    )).all()
    data["top_buttons"] = [{"text": text, "clicks": n} for text, n in rows]
    data["clicks_7d"] = (await session.execute(
        select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.bot_id == bot.id, AnalyticsEvent.event_type == "click", AnalyticsEvent.created_at >= now - timedelta(days=7))
    )).scalar_one()
    data["clickers_7d"] = (await session.execute(
        select(func.count(func.distinct(AnalyticsEvent.user_id))).where(AnalyticsEvent.bot_id == bot.id, AnalyticsEvent.event_type == "click", AnalyticsEvent.created_at >= now - timedelta(days=7))
    )).scalar_one()

    last = (await session.execute(select(Broadcast).where(Broadcast.bot_id == bot.id, Broadcast.status == "done").order_by(Broadcast.id.desc()).limit(3))).scalars().all()
    data["broadcasts"] = [{"at": b.created_at.isoformat() if b.created_at else None, "total": b.total, "sent": b.sent, "failed": b.failed, "blocked": b.blocked} for b in last]
    cap = getattr(limits, "user_cap", None)
    data["cap"] = {"limit": cap, "used": data["total"], "plan": getattr(limits, "plan", None)} if cap else None
    return data


def spark(values: list[int]) -> str:
    """▁▂▃▅▇ line for a list of counts (text version of the growth chart)."""
    marks = "▁▂▃▄▅▆▇█"
    top = max(values) if values else 0
    return "".join(marks[0] if not top or not v else marks[min(7, max(1, round(v / top * 7)))] for v in values)
