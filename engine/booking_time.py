"""Pure time helpers for booking bots: parsing what admins type and computing free slots.

No database access here, so everything is trivially testable.
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
DEFAULT_TZ = "Asia/Tashkent"
WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
WD_SHORT = ["Du", "Se", "Chor", "Pay", "Ju", "Sha", "Yak"]
MAX_REMINDERS = 4


def tz_of(name: str | None):
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return timezone(timedelta(hours=5))  # Uzbekistan has no DST


def valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat them as UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local(dt: datetime, tz) -> datetime:
    return as_utc(dt).astimezone(tz)


def fmt_dt(dt: datetime, tz) -> str:
    d = local(dt, tz)
    return f"{d:%d.%m.%Y} ({WD_SHORT[d.weekday()]}) {d:%H:%M}"


def fmt_min(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ------------------------------------------------------------------ working hours

DAY_OFF_WORDS = {"dam", "dam olish", "off", "yo'q", "yoq", "-", "—", "–"}
_T = r"(\d{1,2})(?:[:.](\d{2}))?"
_RANGE = re.compile(rf"^\s*{_T}\s*[-–—]\s*{_T}\s*$")
HOURS_HINT = "Masalan: <code>09:00-18:00</code> yoki ttanaffus bilan <code>09:00-13:00, 14:00-18:00</code>. Dam olish kuni: <code>dam</code>."


def parse_intervals(text: str) -> list[tuple[int, int]]:
    """"09:00-13:00, 14:00-18:00" -> [(540, 780), (840, 1080)]; "dam" -> []."""
    t = (text or "").strip().lower().replace("’", "'").replace("‘", "'")
    if not t or t in DAY_OFF_WORDS:
        return []
    out = []
    for part in re.split(r"[;,]", t):
        m = _RANGE.match(part)
        if not m:
            raise ValueError("Vaqt formati noto‘g‘ri. " + HOURS_HINT)
        h1, m1, h2, m2 = int(m[1]), int(m[2] or 0), int(m[3]), int(m[4] or 0)
        if m1 > 59 or m2 > 59 or h1 > 23 or h2 > 24 or (h2 == 24 and m2):
            raise ValueError("Soat 00:00 dan 24:00 gacha bo‘lishi kerak.")
        a, b = h1 * 60 + m1, h2 * 60 + m2
        if b <= a:
            raise ValueError("Tugash vaqti boshlanishdan keyin bo‘lishi kerak.")
        out.append((a, b))
    out.sort()
    for (_, e1), (s2, _) in zip(out, out[1:]):
        if s2 < e1:
            raise ValueError("Vaqt oraliqlari bir-biriga tushib qolgan.")
    return out


def fmt_intervals(intervals) -> str:
    if not intervals:
        return "dam olish"
    return ", ".join(f"{fmt_min(a)}–{fmt_min(b)}" for a, b in intervals)


# ------------------------------------------------------------------ small value parsers

def parse_duration(text: str) -> int:
    t = (text or "").strip()
    if not t.isdigit() or not 5 <= int(t) <= 720:
        raise ValueError("Davomiylikni daqiqada, 5 dan 720 gacha butun son bilan yuboring (masalan 45).")
    return int(t)


def parse_price(text: str) -> int | None:
    t = (text or "").strip().lower()
    if t in ("/skip", "yo'q", "yoq", "-", "0"):
        return None
    digits = re.sub(r"[\s,._]", "", t)
    if not digits.isdigit() or int(digits) > 2_000_000_000:
        raise ValueError("Narxni so‘mda raqam bilan yuboring (masalan 80000) yoki /skip.")
    return int(digits)


_UNITS = [
    (1440, ("d", "kun", "day", "days")),
    (60, ("h", "soat", "hour", "hours", "s")),
    (1, ("m", "min", "minut", "daqiqa", "minute", "minutes")),
]
_REM = re.compile(r"^(\d+)\s*([a-zA-Z']+)$")


def parse_reminders(text: str) -> list[int]:
    """"1 kun, 2 soat" -> [1440, 120] (minutes before the visit, largest first)."""
    t = (text or "").strip().lower().replace("’", "'")
    if t in ("", "yo'q", "yoq", "off", "-", "/skip", "0"):
        return []
    out = set()
    for part in re.split(r"[;,\n]", t):
        m = _REM.match(part.strip())
        mult = next((k for k, names in _UNITS if m and m[2] in names), None)
        if not m or mult is None:
            raise ValueError("Format noto‘g‘ri. Masalan: <code>1 kun, 2 soat</code> yoki <code>24h, 30m</code>.")
        minutes = int(m[1]) * mult
        if not 5 <= minutes <= 14 * 1440:
            raise ValueError("Eslatma 5 daqiqadan 14 kungacha oldin bo‘lishi mumkin.")
        out.add(minutes)
    if len(out) > MAX_REMINDERS:
        raise ValueError(f"Eng ko‘pi bilan {MAX_REMINDERS} ta eslatma qo‘yish mumkin.")
    return sorted(out, reverse=True)


def fmt_minutes(minutes: int) -> str:
    if minutes <= 0:
        return "—"
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts = [f"{days} kun"] if days else []
    if hours:
        parts.append(f"{hours} soat")
    if mins:
        parts.append(f"{mins} daqiqa")
    return " ".join(parts)


def fmt_reminders(values) -> str:
    return ", ".join(fmt_minutes(v) + " oldin" for v in values) if values else "o‘chirilgan"


def parse_phone(text: str) -> str:
    raw = (text or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:  # local Uzbek number without the country code
        digits = "998" + digits
    if not 10 <= len(digits) <= 15 or re.search(r"[^\d\s+()\-]", raw):
        raise ValueError("Telefon raqami noto‘g‘ri. Masalan: +998901234567")
    return "+" + digits


def parse_day(text: str, today: date) -> date:
    t = (text or "").strip()
    m = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?$", t)
    try:
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3]) if m[3] else today.year
            result = date(y, mo, d)
            if not m[3] and result < today:
                result = date(y + 1, mo, d)
            return result
        return date.fromisoformat(t)
    except ValueError:
        raise ValueError("Sana noto‘g‘ri. Masalan: 25.12.2026 yoki 25.12") from None


def parse_day_range(text: str, today: date, limit: int = 60) -> list[date]:
    """"25.12" or "25.12.2026 - 05.01.2027" -> list of days."""
    parts = re.split(r"\s+[-–—]\s+|\s*[–—]\s*", (text or "").strip())
    if len(parts) == 1:
        return [parse_day(parts[0], today)]
    if len(parts) != 2:
        raise ValueError("Sana oralig‘i: <code>25.12.2026 - 05.01.2027</code>")
    a, b = parse_day(parts[0], today), parse_day(parts[1], today)
    if b < a:
        b = date(b.year + 1, b.month, b.day) if "." in parts[1] and parts[1].count(".") < 2 else b
    if b < a:
        raise ValueError("Tugash sanasi boshlanishdan oldin bo‘lmasin.")
    if (b - a).days + 1 > limit:
        raise ValueError(f"Bir safarda {limit} kundan ko‘p kiritib bo‘lmaydi.")
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


# ------------------------------------------------------------------ slots

def free_starts(day: date, intervals, duration: int, step: int, busy, now: datetime,
                notice: int, tz) -> list[datetime]:
    """UTC start times on ``day`` where a ``duration``-minute visit fits a working interval,
    does not overlap ``busy`` [(start_utc, end_utc)] and is at least ``notice`` minutes away."""
    base = datetime.combine(day, time(0), tzinfo=tz)
    earliest = now + timedelta(minutes=notice)
    step = max(step, 5)
    out = []
    for a, b in intervals:
        t = a
        while t + duration <= b:
            start = (base + timedelta(minutes=t)).astimezone(UTC)
            end = start + timedelta(minutes=duration)
            if start >= earliest and not any(start < be and end > bs for bs, be in busy):
                out.append(start)
            t += step
    return sorted(set(out))
