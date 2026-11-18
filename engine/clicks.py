"""Button click log for the owner's statistics. Writes are best-effort and old rows are pruned daily."""
import time
from datetime import timedelta

from sqlalchemy import delete

from core.logger import get_logger
from engine.booking_time import utcnow
from models.analytics import AnalyticsEvent

logger = get_logger("clicks")
KEEP_DAYS = 90
_last_prune: float | None = None


async def record(session, bot_id: int, user_id: int | None, button_id: int) -> None:
    global _last_prune
    try:
        session.add(AnalyticsEvent(bot_id=bot_id, event_type="click", user_id=user_id, button_id=button_id))
        await session.commit()
        if _last_prune is None or time.monotonic() - _last_prune > 86400:
            _last_prune = time.monotonic()
            await session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.created_at < utcnow() - timedelta(days=KEEP_DAYS)))
            await session.commit()
    except Exception:  # statistics must never break the bot
        logger.exception("Could not record a click")
        try:
            await session.rollback()
        except Exception:
            pass
