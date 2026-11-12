from datetime import date, datetime

import pytest

from engine.booking_time import (
    UTC, fmt_intervals, fmt_minutes, free_starts, parse_day, parse_day_range, parse_duration,
    parse_intervals, parse_phone, parse_price, parse_reminders, tz_of,
)

TZ = tz_of("Asia/Tashkent")  # UTC+5


@pytest.mark.parametrize("text, expected", [
    ("09:00-18:00", [(540, 1080)]),
    ("9-18", [(540, 1080)]),
    ("14:00–18:00, 09:00-13:00", [(540, 780), (840, 1080)]),
    ("09.30-12.00", [(570, 720)]),
    ("00:00-24:00", [(0, 1440)]),
    ("dam", []), ("  Dam olish ", []), ("-", []), ("", []),
])
def test_parse_intervals_ok(text, expected):
    assert parse_intervals(text) == expected


@pytest.mark.parametrize("text", ["abc", "18:00-09:00", "09:00-09:00", "25:00-26:00", "09:61-10:00",
                                  "09:00-13:00, 12:00-15:00", "24:30-24:45", "9"])
def test_parse_intervals_rejects(text):
    with pytest.raises(ValueError):
        parse_intervals(text)


def test_fmt_intervals():
    assert fmt_intervals([(540, 780), (840, 1080)]) == "09:00–13:00, 14:00–18:00"
    assert fmt_intervals([]) == "dam olish"


@pytest.mark.parametrize("text, expected", [
    ("1 kun, 2 soat", [1440, 120]), ("24h,30m", [1440, 30]), ("2 soat", [120]), ("90 daqiqa", [90]),
    ("1d; 1h", [1440, 60]), ("yo'q", []), ("", []), ("60m, 1 soat", [60]),
])
def test_parse_reminders_ok(text, expected):
    assert parse_reminders(text) == expected


@pytest.mark.parametrize("text", ["2", "soat", "1 hafta", "1m", "15 kun", "1h,2h,3h,4h,5h"])
def test_parse_reminders_rejects(text):
    with pytest.raises(ValueError):
        parse_reminders(text)


def test_fmt_minutes():
    assert fmt_minutes(1440) == "1 kun" and fmt_minutes(90) == "1 soat 30 daqiqa" and fmt_minutes(2880 + 60) == "2 kun 1 soat"


def test_values():
    assert parse_duration("45") == 45
    for bad in ("4", "721", "x", "1.5"):
        with pytest.raises(ValueError):
            parse_duration(bad)
    assert parse_price("80 000") == 80000 and parse_price("/skip") is None and parse_price("1,500") == 1500
    with pytest.raises(ValueError):
        parse_price("arzon")
    assert parse_phone("+998 90 123-45-67") == "+998901234567"
    assert parse_phone("901234567") == "+998901234567"
    for bad in ("123", "abc", "+998 90 12a45 67"):
        with pytest.raises(ValueError):
            parse_phone(bad)


def test_parse_day_and_range():
    today = date(2026, 11, 12)
    assert parse_day("25.12", today) == date(2026, 12, 25)
    assert parse_day("05.11", today) == date(2027, 11, 5)  # already passed: next year
    assert parse_day("05.11.2026", today) == date(2026, 11, 5)
    assert parse_day("2026-12-01", today) == date(2026, 12, 1)
    with pytest.raises(ValueError):
        parse_day("31.02", today)
    days = parse_day_range("30.12.2026 - 02.01.2027", today)
    assert [d.isoformat() for d in days] == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]
    assert parse_day_range("25.12", today) == [date(2026, 12, 25)]
    with pytest.raises(ValueError):
        parse_day_range("01.01.2027 - 01.01.2028", today)


def at(h, m=0, day=16):  # local Tashkent time on 2026-11-<day> as UTC
    return datetime(2026, 11, day, h, m, tzinfo=TZ).astimezone(UTC)


NOW = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)


def test_free_starts_basic_grid():
    got = free_starts(date(2026, 11, 16), [(540, 660)], 30, 30, [], NOW, 0, TZ)
    assert got == [at(9), at(9, 30), at(10), at(10, 30)]


def test_duration_must_fit_before_closing():
    got = free_starts(date(2026, 11, 16), [(540, 630)], 60, 30, [], NOW, 0, TZ)
    assert got == [at(9), at(9, 30)]


def test_busy_blocks_overlap_but_touching_is_ok():
    busy = [(at(10), at(11))]
    got = free_starts(date(2026, 11, 16), [(540, 720)], 60, 30, busy, NOW, 0, TZ)
    assert got == [at(9), at(11)]


def test_lunch_break_two_intervals():
    got = free_starts(date(2026, 11, 16), [(540, 600), (840, 900)], 60, 60, [], NOW, 0, TZ)
    assert got == [at(9), at(14)]


def test_min_notice_hides_near_slots():
    now = at(9, 10)
    got = free_starts(date(2026, 11, 16), [(540, 720)], 30, 30, [], now, 60, TZ)
    assert got[0] == at(10, 30)


def test_past_slots_hidden_today():
    now = at(12, 0, day=16)
    got = free_starts(date(2026, 11, 16), [(540, 780)], 30, 30, [], now, 0, TZ)
    assert got == [at(12), at(12, 30)]
