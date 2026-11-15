from datetime import datetime, timezone

from engine import course_logic as cl
from engine.booking_time import tz_of

TZ = tz_of("Asia/Tashkent")
UTC = timezone.utc
START = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)  # 08:00 Tashkent


def test_all_open():
    assert cl.unlocked_count("all", [False] * 4, enrolled_at=START, now=START) == 4


def test_sequential():
    assert cl.unlocked_count("seq", [False, False, False], enrolled_at=START, now=START) == 1
    assert cl.unlocked_count("seq", [True, False, False], enrolled_at=START, now=START) == 2
    assert cl.unlocked_count("seq", [True, True, True], enrolled_at=START, now=START) == 3
    assert cl.unlocked_count("seq", [False, True, False], enrolled_at=START, now=START) == 1


def test_drip_daily_at_hour():
    kw = dict(enrolled_at=START, drip_days=1, drip_hour=9, tz=TZ)
    d = [True] * 5  # a diligent student: everything opened so far is finished
    assert cl.unlocked_count("drip", d, now=START, **kw) == 1
    # day 2 at 09:00 Tashkent = 04:00 UTC
    assert cl.unlocked_count("drip", d, now=datetime(2026, 11, 2, 3, 59, tzinfo=UTC), **kw) == 1
    assert cl.unlocked_count("drip", d, now=datetime(2026, 11, 2, 4, 0, tzinfo=UTC), **kw) == 2
    assert cl.unlocked_count("drip", d, now=datetime(2026, 12, 1, tzinfo=UTC), **kw) == 5


def test_drip_waits_for_the_previous_lesson():
    kw = dict(enrolled_at=START, drip_days=1, drip_hour=9, tz=TZ)
    day2 = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)
    late = datetime(2026, 12, 1, tzinfo=UTC)
    # day 2 has come, but lesson 1 is not finished: lesson 2 stays closed
    assert cl.unlocked_count("drip", [False] * 5, now=day2, **kw) == 1
    assert cl.unlocked_count("drip", [False] * 5, now=late, **kw) == 1
    # finishing lesson 1 opens lesson 2 at once, and no further (the schedule is already due)
    assert cl.unlocked_count("drip", [True, False, False, False, False], now=late, **kw) == 2
    assert cl.unlocked_count("drip", [True, True, False, False, False], now=late, **kw) == 3
    # finished lesson 1 early: lesson 2 still waits for its day
    assert cl.unlocked_count("drip", [True, False, False], now=START, **kw) == 1
    # a skipped lesson in the middle blocks everything after it
    assert cl.unlocked_count("drip", [True, False, True, False], now=late, **kw) == 2


def test_drip_every_two_days_and_next_open():
    kw = dict(enrolled_at=START, drip_days=2, drip_hour=9, tz=TZ)
    nxt = cl.next_open_at("drip", 1, 3, **kw)
    assert nxt == datetime(2026, 11, 3, 4, 0, tzinfo=UTC)
    assert cl.next_open_at("drip", 3, 3, **kw) is None
    assert cl.next_open_at("all", 1, 3, **kw) is None


def test_naive_datetimes_from_sqlite():
    naive = datetime(2026, 11, 1, 3, 0)
    assert cl.unlocked_count("drip", [True, False], enrolled_at=naive, now=datetime(2026, 11, 2, 5, tzinfo=UTC),
                             drip_days=1, drip_hour=9, tz=TZ) == 2


def test_percent_bar():
    assert cl.percent(1, 3) == 33 and cl.percent(0, 0) == 0 and cl.percent(5, 3) == 100
    assert cl.bar(50) == "▰▰▰▰▰▱▱▱▱▱"
