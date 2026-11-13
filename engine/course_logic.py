"""Pure rules of the course bot: which lessons a student may open, and progress."""
from datetime import datetime, timedelta

from engine.booking_time import as_utc, local
from models.course import UNLOCK_DRIP, UNLOCK_SEQ


def drip_open_at(enrolled_at: datetime, index: int, drip_days: int, drip_hour: int, tz) -> datetime:
    """UTC moment lesson ``index`` (0-based) opens in a scheduled course. The first lesson opens at once."""
    start = local(enrolled_at, tz)
    if index <= 0:
        return as_utc(enrolled_at)
    day = start.date() + timedelta(days=index * max(1, drip_days))
    return datetime(day.year, day.month, day.day, drip_hour, 0, tzinfo=tz).astimezone(as_utc(enrolled_at).tzinfo)


def unlocked_count(mode: str, done: list[bool], *, enrolled_at: datetime, now: datetime,
                   drip_days: int = 1, drip_hour: int = 9, tz=None) -> int:
    """How many lessons (a prefix of the ordered list) are open. ``done[i]`` = lesson i is completed."""
    total = len(done)
    if mode == UNLOCK_SEQ:
        run = 0
        while run < total and done[run]:
            run += 1
        return min(total, run + 1)
    if mode == UNLOCK_DRIP:
        count = 0
        while count < total and drip_open_at(enrolled_at, count, drip_days, drip_hour, tz) <= now:
            count += 1
        return count
    return total


def next_open_at(mode: str, opened: int, total: int, *, enrolled_at, drip_days=1, drip_hour=9, tz=None):
    """When the next locked lesson opens (scheduled courses only), else None."""
    if mode != UNLOCK_DRIP or opened >= total:
        return None
    return drip_open_at(enrolled_at, opened, drip_days, drip_hour, tz)


def percent(done_count: int, total: int) -> int:
    return 0 if total <= 0 else min(100, round(done_count * 100 / total))


def bar(pct: int, width: int = 10) -> str:
    filled = round(width * pct / 100)
    return "▰" * filled + "▱" * (width - filled)
