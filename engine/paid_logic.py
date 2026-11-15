"""Pure rules of the paid-channel bot: promo codes, subscription dates, reminders."""
import re
from datetime import datetime, timedelta

from engine.booking_time import as_utc
from engine.shop_logic import fmt_money, parse_int  # noqa: F401  (re-exported for the engine)

CODE_RE = re.compile(r"^[A-Z0-9_-]{3,40}$")
REMIND_DAYS = (3, 1)


def norm_code(text: str) -> str:
    return (text or "").strip().upper()


def valid_code(text: str) -> bool:
    return bool(CODE_RE.match(norm_code(text)))


def parse_discount(text: str) -> tuple[int | None, int | None]:
    """'20%' -> (20, None); '15000' -> (None, 15000). Raises ValueError with a user-facing message."""
    raw = (text or "").strip()
    if raw.endswith("%"):
        value = parse_int(raw[:-1], minimum=1, maximum=100)
        return value, None
    return None, parse_int(raw, minimum=1)


def promo_error(promo, now: datetime) -> str | None:
    """Why a code cannot be used right now (None = usable)."""
    if promo is None or not promo.is_active:
        return "Bunday promokod topilmadi."
    if promo.expires_at is not None and as_utc(promo.expires_at) <= now:
        return "Promokod muddati tugagan."
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return "Promokod ishlatilib bo‘lingan."
    return None


def discounted(price: int, promo) -> int:
    if promo is None:
        return price
    if promo.percent:
        return max(0, price - price * promo.percent // 100)
    return max(0, price - (promo.amount or 0))


def promo_label(promo) -> str:
    return f"{promo.percent}%" if promo.percent else fmt_money(promo.amount or 0)


def extend(expires_at: datetime | None, now: datetime, days: int) -> datetime:
    """New expiry: renewing an active subscription adds days after the current end, an expired one starts now."""
    base = max(as_utc(expires_at), now) if expires_at is not None else now
    return base + timedelta(days=days)


def days_left(expires_at: datetime, now: datetime) -> int:
    """Whole days remaining, rounded up (a subscription ending in 5 hours has 1 day left)."""
    seconds = (as_utc(expires_at) - now).total_seconds()
    return 0 if seconds <= 0 else -(-int(seconds) // 86400)


def reminder_due(expires_at: datetime, now: datetime, reminded_3: bool, reminded_1: bool) -> int | None:
    """Which reminder (3 or 1 days before the end) should go out now; each is sent once."""
    left = as_utc(expires_at) - now
    if left.total_seconds() <= 0:
        return None
    if left <= timedelta(days=1):
        return None if reminded_1 else 1
    if left <= timedelta(days=3):
        return None if reminded_3 else 3
    return None
