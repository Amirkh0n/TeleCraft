"""Background health checks: database reachability and size, broken webhooks (repaired automatically)."""
import asyncio
import time

from sqlalchemy import select, text

from core import alerts
from core.config import settings
from core.database import AsyncSessionLocal
from core.logger import get_logger

logger = get_logger("health")

DOWN_AFTER = 2       # consecutive failed pings before "database is down"
SLOW_SECONDS = 2.0
SLOW_AFTER = 3
WEBHOOK_EVERY = 3600
WEBHOOK_BOTS = 200


async def ping() -> float | None:
    """Seconds one ``SELECT 1`` takes, or None if the database does not answer."""
    started = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=10)
    except Exception:
        return None
    return time.monotonic() - started


async def db_size_mb() -> float | None:
    """Database size in MB (PostgreSQL only)."""
    try:
        async with AsyncSessionLocal() as session:
            if session.bind.dialect.name != "postgresql":
                return None
            return (await session.execute(text("SELECT pg_database_size(current_database())"))).scalar_one() / 1024 / 1024
    except Exception:
        return None


class State:
    def __init__(self):
        self.failed = 0
        self.slow = 0
        self.down = False
        self.last_webhooks = 0.0


async def check_database(state: State, *, ping_fn=ping, size_fn=db_size_mb) -> None:
    seconds = await ping_fn()
    if seconds is None:
        state.failed += 1
        if state.failed >= DOWN_AFTER:
            state.down = True
            await alerts.notify("db_down", "🔴 <b>Baza javob bermayapti</b>\nBotlar ishlamasligi mumkin. Neon/Render holatini tekshiring.", cooldown=1800)
        return
    if state.down:
        state.down = False
        await alerts.notify("db_up", "🟢 Baza qayta javob bermoqda.", cooldown=0)
    state.failed = 0
    state.slow = state.slow + 1 if seconds > SLOW_SECONDS else 0
    if state.slow >= SLOW_AFTER:
        await alerts.notify("db_slow", f"🐢 Baza sekin javob beryapti: {seconds:.1f} soniya.", cooldown=6 * 3600)
    limit = settings.DB_SIZE_LIMIT_MB
    size = await size_fn() if limit else None
    if size:
        share = size / limit
        if share >= 0.95:
            await alerts.notify("db_size_95", f"🚨 <b>Baza deyarli to‘ldi</b>: {size:.0f} / {limit} MB ({share:.0%}). Eski ma’lumotni tozalang yoki tarifni oshiring.", cooldown=86400)
        elif share >= 0.8:
            await alerts.notify("db_size_80", f"⚠️ Baza hajmi {size:.0f} / {limit} MB ({share:.0%}).", cooldown=86400)


async def repair_webhooks(*, status_fn=None, set_fn=None, sleep=asyncio.sleep) -> tuple[int, int]:
    """Re-register the webhook of every active bot whose webhook vanished or points elsewhere.
    Returns (checked, repaired)."""
    from core.webhook_manager import build_webhook_url, get_webhook_status, set_webhook
    from models.bots import Bot
    status_fn, set_fn = status_fn or get_webhook_status, set_fn or set_webhook
    if "your-app" in settings.PUBLIC_BASE_URL:
        return 0, 0
    async with AsyncSessionLocal() as session:
        bots = (await session.execute(select(Bot).where(Bot.is_active == True).order_by(Bot.id).limit(WEBHOOK_BOTS))).scalars().all()  # noqa: E712
        targets = [(b.id, b.plain_token) for b in bots]
    repaired = 0
    for bot_id, token in targets:
        status = await status_fn(token)
        want = build_webhook_url(token)
        if "error" in status:
            continue  # Telegram unreachable or token revoked: not something a re-register fixes
        if not status.get("has_webhook") or status.get("url") != want:
            if await set_fn(token, want):
                repaired += 1
        await sleep(0.2)
    if repaired:
        await alerts.notify("webhooks_repaired", f"🔧 {repaired} ta botning webhooki avtomatik tiklandi.", cooldown=3600)
    return len(targets), repaired


async def health_loop(*, sleep=asyncio.sleep, clock=time.monotonic) -> None:
    state = State()
    while True:
        try:
            await check_database(state)
            if not state.down and clock() - state.last_webhooks >= WEBHOOK_EVERY:
                state.last_webhooks = clock()
                await repair_webhooks()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("health loop error")
        await sleep(settings.HEALTH_INTERVAL)
