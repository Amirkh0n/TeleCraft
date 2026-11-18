"""Alerts to the platform admins through the main bot, with a cool-down so one problem is reported once."""
import asyncio
import time
from collections import deque

from core.config import settings
from core.logger import get_logger

logger = get_logger("alerts")

SPIKE_COUNT = 5          # this many failed updates...
SPIKE_WINDOW = 600       # ...within this many seconds is an alert
_get_bot = lambda: None  # noqa: E731
_failures: deque = deque(maxlen=200)
_last_sent: dict[str, float] = {}


def configure(get_bot) -> None:
    global _get_bot
    _get_bot = get_bot


def reset() -> None:
    _failures.clear()
    _last_sent.clear()


async def notify(key: str, text: str, cooldown: float = 3600) -> bool:
    """Send ``text`` to every admin unless the same ``key`` was sent less than ``cooldown`` seconds ago."""
    admins, bot = settings.admin_ids_list, _get_bot()
    if not admins or bot is None:
        return False
    now = time.monotonic()
    last = _last_sent.get(key)
    if last is not None and now - last < cooldown:
        return False
    _last_sent[key] = now
    sent = False
    for admin in admins:
        try:
            await bot.send_message(chat_id=admin, text=text[:3500], parse_mode="HTML")
            sent = True
        except Exception as exc:  # the admin never started the main bot, or blocked it
            logger.warning("Alert not delivered to %s: %s", admin, exc)
    return sent


def record_failure(bot_id: int | None, exc: BaseException | None = None) -> None:
    """Called when an update or an API request failed. A burst of failures becomes one alert."""
    now = time.monotonic()
    _failures.append((now, bot_id, type(exc).__name__ if exc else "Error"))
    recent = [f for f in _failures if now - f[0] <= SPIKE_WINDOW]
    if len(recent) < SPIKE_COUNT:
        return
    per_bot: dict = {}
    for _, bid, _name in recent:
        per_bot[bid] = per_bot.get(bid, 0) + 1
    worst = ", ".join(f"{'API' if b is None else f'bot #{b}'}: {n}" for b, n in sorted(per_bot.items(), key=lambda x: -x[1])[:3])
    text = f"⚠️ <b>Xatolar ko‘paydi</b>: {len(recent)} ta / {SPIKE_WINDOW // 60} daqiqa\n{worst}\nOxirgi xato: {recent[-1][2]}\nLoglarni tekshiring."
    try:
        asyncio.get_running_loop().create_task(notify("spike", text, cooldown=1800))
    except RuntimeError:
        pass
