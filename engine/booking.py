"""Booking bots (barbershop, clinic, tutoring...): clients pick service -> specialist -> day ->
time and leave a phone number; admins confirm/manage everything from inside the child bot
(``engine/booking_admin.py``). Never raises for normal user input.

Times are stored in UTC and shown in the bot's own time zone (``BookingSettings.timezone``).
"""
import asyncio
import weakref
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from telegram import (
    InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.error import TelegramError

from core.logger import get_logger
from engine import booking_admin, cinema, forms, subscription
from engine.audience import touch_user
from engine.booking_time import (
    UTC, WD_SHORT, as_utc, fmt_dt, fmt_minutes, free_starts, local, parse_phone, tz_of, utcnow,
)
from models.booking import (
    ACTIVE_STATUSES, CANCELLED, CONFIRMED, PENDING, REJECTED, Booking, BookingDayOff, BookingHours,
    BookingService, BookingSettings, BookingStaff, BookingStaffService,
)
from models.user_sessions import UserSession

logger = get_logger("booking")
esc = cinema.esc

WELCOME = "📅 <b>Xush kelibsiz!</b>\n\nVaqtingizni oldindan band qilish uchun «📅 Bron qilish» tugmasini bosing."
DAYS_PER_PAGE = 9
STATUS_ICON = {PENDING: "⏳", CONFIRMED: "✅", CANCELLED: "❌", REJECTED: "🚫", "done": "✔️", "no_show": "👻"}
STATUS_TEXT = {PENDING: "tasdiq kutilmoqda", CONFIRMED: "tasdiqlangan", CANCELLED: "bekor qilingan",
               REJECTED: "rad etilgan", "done": "bajarilgan", "no_show": "kelmagan"}

_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()


def bot_lock(bot_id: int) -> asyncio.Lock:
    lock = _locks.get(bot_id)
    if lock is None:
        lock = _locks[bot_id] = asyncio.Lock()
    return lock


# ------------------------------------------------------------------ settings & scheduling data

async def get_settings(session, bot_id: int) -> BookingSettings:
    st = (await session.execute(select(BookingSettings).where(BookingSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = BookingSettings(bot_id=bot_id, reminders=[1440, 60])
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> BookingSettings:
    """Settings, default Mon-Sat 09:00-18:00 hours and a start menu (sessions need one)."""
    st = await get_settings(session, bot.id)
    has_hours = (await session.execute(
        select(func.count(BookingHours.id)).where(BookingHours.bot_id == bot.id)
    )).scalar()
    if not has_hours:
        session.add_all(BookingHours(bot_id=bot.id, weekday=wd, start_min=540, end_min=1080) for wd in range(6))
        await session.commit()
    await cinema.ensure_start_menu(session, bot, WELCOME)
    return st


async def week_hours(session, bot_id: int, staff_id) -> dict[int, list[tuple[int, int]]]:
    """A specialist's own schedule if they have one, otherwise the business hours."""
    scopes = ([staff_id] if staff_id else []) + [None]
    for scope in scopes:
        cond = BookingHours.staff_id.is_(None) if scope is None else BookingHours.staff_id == scope
        rows = (await session.execute(
            select(BookingHours).where(BookingHours.bot_id == bot_id, cond).order_by(BookingHours.start_min)
        )).scalars().all()
        if rows:
            out: dict[int, list] = {}
            for r in rows:
                out.setdefault(r.weekday, []).append((r.start_min, r.end_min))
            return out
    return {}


async def days_off(session, bot_id: int, staff_id, first: date, last: date) -> set[date]:
    """Business-wide days off plus the specialist's own."""
    cond = BookingDayOff.staff_id.is_(None)
    if staff_id:
        cond = cond | (BookingDayOff.staff_id == staff_id)
    rows = (await session.execute(
        select(BookingDayOff.day).where(BookingDayOff.bot_id == bot_id, cond, BookingDayOff.day.between(first, last))
    )).scalars().all()
    return set(rows)


async def active_services(session, bot_id: int):
    return list((await session.execute(
        select(BookingService).where(BookingService.bot_id == bot_id, BookingService.is_active.is_(True))
        .order_by(BookingService.position, BookingService.id)
    )).scalars().all())


async def eligible_staff(session, bot_id: int, service_id: int):
    """(has_staff_mode, specialists who can do the service). No specialists at all = one shared chair."""
    staff = list((await session.execute(
        select(BookingStaff).where(BookingStaff.bot_id == bot_id, BookingStaff.is_active.is_(True))
        .order_by(BookingStaff.position, BookingStaff.id)
    )).scalars().all())
    if not staff:
        return False, []
    links: dict[int, set[int]] = {}
    for sid, svc in (await session.execute(
        select(BookingStaffService.staff_id, BookingStaffService.service_id)
        .where(BookingStaffService.staff_id.in_([s.id for s in staff]))
    )).all():
        links.setdefault(sid, set()).add(svc)
    return True, [s for s in staff if s.id not in links or service_id in links[s.id]]


async def availability(session, bot, st, service, staff_ids: list, days: list[date]) -> dict[date, dict[datetime, int | None]]:
    """{day: {start_utc: staff_id}} for the given specialists (``[None]`` = shared chair)."""
    if not days or not staff_ids:
        return {}
    tz, now = tz_of(st.timezone), utcnow()
    lo = datetime.combine(days[0], time(0), tzinfo=tz).astimezone(UTC)
    hi = (datetime.combine(days[-1], time(0), tzinfo=tz) + timedelta(days=1)).astimezone(UTC)
    busy = [(b.staff_id, as_utc(b.start_at), as_utc(b.end_at)) for b in (await session.execute(
        select(Booking).where(Booking.bot_id == bot.id, Booking.status.in_(ACTIVE_STATUSES),
                              Booking.start_at < hi, Booking.end_at > lo)
    )).scalars().all()]
    result: dict[date, dict[datetime, int | None]] = {}
    for sid in staff_ids:
        hours = await week_hours(session, bot.id, sid)
        off = await days_off(session, bot.id, sid, days[0], days[-1])
        mine = [(s, e) for bid, s, e in busy if bid == sid]
        for d in days:
            intervals = hours.get(d.weekday())
            if d in off or not intervals:
                continue
            for start in free_starts(d, intervals, service.duration_min, st.slot_step_min, mine, now,
                                     st.min_notice_min, tz):
                result.setdefault(d, {}).setdefault(start, sid)
    return result


def window(st) -> list[date]:
    today = local(utcnow(), tz_of(st.timezone)).date()
    return [today + timedelta(days=i) for i in range(st.max_days_ahead + 1)]


async def staff_ids_for(session, bot_id: int, service_id: int, choice) -> list:
    has_staff, staff = await eligible_staff(session, bot_id, service_id)
    if not has_staff:
        return [None]
    ids = [s.id for s in staff]
    return [choice] if choice and choice in ids else ([] if choice else ids)


async def create_booking(session, bot, st, service, choice, start_utc, user: dict, phone: str):
    """Book atomically (per-bot lock). Returns the Booking, or ``None`` if the slot was just taken."""
    async with bot_lock(bot.id):
        tz = local(start_utc, tz_of(st.timezone)).date()
        ids = await staff_ids_for(session, bot.id, service.id, choice)
        found = (await availability(session, bot, st, service, ids, [tz])).get(tz, {})
        if start_utc not in found:
            return None
        sid = found[start_utc]
        staff = await session.get(BookingStaff, sid) if sid else None
        booking = Booking(
            bot_id=bot.id, service_id=service.id, staff_id=sid, tg_user_id=user["id"],
            client_name=(user.get("first_name") or "") + (f" {user['last_name']}" if user.get("last_name") else "") or "Mijoz",
            phone=phone, service_name=service.name, staff_name=staff.name if staff else None, price=service.price,
            start_at=start_utc, end_at=start_utc + timedelta(minutes=service.duration_min),
            status=CONFIRMED if st.auto_confirm else PENDING, reminders_sent=[],
        )
        session.add(booking)
        await session.commit()
        return booking


# ------------------------------------------------------------------ formatting & notifications

def money(value) -> str:
    return f"{value:,}".replace(",", " ") + " so‘m" if value else ""


def card(b, tz, *, with_client=False) -> str:
    lines = [f"{STATUS_ICON.get(b.status, '')} <b>Bron #{b.id}</b> — {STATUS_TEXT.get(b.status, b.status)}",
             f"🧾 {esc(b.service_name)}"]
    if b.staff_name:
        lines.append(f"👤 {esc(b.staff_name)}")
    lines.append(f"🗓 {fmt_dt(b.start_at, tz)}")
    if b.price:
        lines.append(f"💰 {money(b.price)}")
    if with_client:
        # a text link (not a button): buttons with tg://user links make Telegram reject the whole message
        # for users with strict privacy settings
        who = f'<a href="tg://user?id={b.tg_user_id}">{esc(b.client_name)}</a>' + (f" · {esc(b.phone)}" if b.phone else "")
        lines.append(f"🙋 {who} (<code>{b.tg_user_id}</code>)")
    return "\n".join(lines)


async def tell(tg, chat_id: int, text: str, markup=None) -> bool:
    try:
        await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)
        return True
    except TelegramError as exc:
        logger.info("cannot message %s: %s", chat_id, exc)
        return False


async def notify_admins(tg, bot, session, text: str, markup=None):
    delivered = 0
    for admin_id in sorted(await cinema.admin_ids(session, bot)):
        delivered += await tell(tg, admin_id, text, markup)
    if not delivered:  # nobody started the child bot: fall back to the constructor bot (text only)
        await forms.notify(tg, bot, text, session)


def admin_buttons(b) -> Markup:
    rows = []
    if b.status == PENDING:
        rows.append([Btn("✅ Tasdiqlash", callback_data=f"ba:bs:{b.id}:ok"), Btn("🚫 Rad etish", callback_data=f"ba:bs:{b.id}:no")])
    rows.append([Btn("📋 Bron", callback_data=f"ba:b:{b.id}")])
    return Markup(rows)


# ------------------------------------------------------------------ sessions

async def session_of(session, bot, user_id: int) -> UserSession:
    from engine.actions import get_user_session
    us = await get_user_session(session, bot.id, user_id)
    if us is None:
        menu = await cinema.ensure_start_menu(session, bot, WELCOME)
        us = UserSession(bot_id=bot.id, tg_user_id=user_id, current_menu_id=menu.id)
        session.add(us)
        await session.commit()
    return us


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


# ------------------------------------------------------------------ client screens

def home_markup(is_admin: bool) -> Markup:
    rows = [[Btn("📅 Bron qilish", callback_data="bk:new")],
            [Btn("📋 Mening bronlarim", callback_data="bk:my"), Btn("ℹ️ Ma’lumot", callback_data="bk:info")]]
    if is_admin:
        rows.append([Btn("🛠 Admin panel", callback_data="ba:home")])
    return Markup(rows)


async def show_home(tg, callback, chat_id, session, bot, admin):
    menu = await cinema.ensure_start_menu(session, bot, WELCOME)
    await cinema._show(tg, callback, chat_id, menu.message_text or WELCOME, home_markup(admin))


async def show_services(tg, callback, chat_id, session, bot):
    services = await active_services(session, bot.id)
    if not services:
        await cinema._show(tg, callback, chat_id, "😕 Hozircha xizmatlar kiritilmagan. Keyinroq urinib ko‘ring.",
                           Markup([[Btn("⬅️ Orqaga", callback_data="bk:home")]]))
        return
    rows = []
    for s in services:
        price = f" · {money(s.price)}" if s.price else ""
        rows.append([Btn(f"{s.name} · {s.duration_min} daq{price}"[:60], callback_data=f"bk:s:{s.id}")])
    rows.append([Btn("⬅️ Orqaga", callback_data="bk:home")])
    await cinema._show(tg, callback, chat_id, "🧾 <b>Xizmatni tanlang:</b>", Markup(rows))


async def after_service(tg, callback, chat_id, session, bot, us, service):
    has_staff, staff = await eligible_staff(session, bot.id, service.id)
    data = {"svc": service.id, "stf": 0}
    await set_state(session, us, "bk", data)
    if has_staff and not staff:
        await cinema._show(tg, callback, chat_id, "😕 Bu xizmat uchun hozircha mutaxassis yo‘q.",
                           Markup([[Btn("⬅️ Orqaga", callback_data="bk:new")]]))
    elif has_staff and len(staff) > 1:
        rows = [[Btn("🎲 Farqi yo‘q (birinchi bo‘sh)", callback_data="bk:m:0")]]
        rows += [[Btn(f"👤 {s.name}"[:60], callback_data=f"bk:m:{s.id}")] for s in staff]
        rows.append([Btn("⬅️ Orqaga", callback_data="bk:new")])
        await cinema._show(tg, callback, chat_id, "👤 <b>Mutaxassisni tanlang:</b>", Markup(rows))
    else:
        data["stf"] = staff[0].id if staff else 0
        await set_state(session, us, "bk", data)
        await show_days(tg, callback, chat_id, session, bot, us, 0)


async def show_days(tg, callback, chat_id, session, bot, us, page: int):
    data = dict(us.state_data or {})
    service = await session.get(BookingService, data.get("svc"))
    if not service or service.bot_id != bot.id or not service.is_active:
        return await show_services(tg, callback, chat_id, session, bot)
    st = await get_settings(session, bot.id)
    ids = await staff_ids_for(session, bot.id, service.id, data.get("stf") or None)
    free = await availability(session, bot, st, service, ids, window(st))
    days = sorted(free)
    pages = max(1, (len(days) + DAYS_PER_PAGE - 1) // DAYS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    back = "bk:new" if len((await eligible_staff(session, bot.id, service.id))[1]) <= 1 else f"bk:s:{service.id}"
    if not days:
        await cinema._show(tg, callback, chat_id, "😕 Yaqin kunlarda bo‘sh vaqt yo‘q. Keyinroq urinib ko‘ring.",
                           Markup([[Btn("⬅️ Orqaga", callback_data=back)]]))
        return
    chunk = days[page * DAYS_PER_PAGE:(page + 1) * DAYS_PER_PAGE]
    buttons = [Btn(f"{d:%d.%m} {WD_SHORT[d.weekday()]}", callback_data=f"bk:d:{d:%Y%m%d}") for d in chunk]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    nav = ([Btn("◀️", callback_data=f"bk:dp:{page - 1}")] if page else []) + \
          ([Btn("▶️", callback_data=f"bk:dp:{page + 1}")] if page < pages - 1 else [])
    if nav:
        rows.append(nav)
    rows.append([Btn("⬅️ Orqaga", callback_data=back)])
    desc = f"\n<i>{esc(service.description)}</i>" if service.description else ""
    await cinema._show(tg, callback, chat_id, f"🗓 <b>{esc(service.name)}</b>{desc}\nKunni tanlang:", Markup(rows))


async def show_times(tg, callback, chat_id, session, bot, us, day: date):
    data = dict(us.state_data or {})
    service = await session.get(BookingService, data.get("svc"))
    if not service or service.bot_id != bot.id:
        return await show_services(tg, callback, chat_id, session, bot)
    st = await get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    ids = await staff_ids_for(session, bot.id, service.id, data.get("stf") or None)
    slots = sorted((await availability(session, bot, st, service, ids, [day])).get(day, {}))
    if not slots:
        await cinema._show(tg, callback, chat_id, "😕 Bu kunda bo‘sh vaqt qolmadi.",
                           Markup([[Btn("⬅️ Kunlar", callback_data="bk:dp:0")]]))
        return
    data["day"] = day.isoformat()
    await set_state(session, us, "bk", data)
    buttons = [Btn(f"{local(s, tz):%H:%M}", callback_data=f"bk:t:{local(s, tz):%H%M}") for s in slots]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([Btn("⬅️ Kunlar", callback_data="bk:dp:0")])
    await cinema._show(tg, callback, chat_id,
                       f"🕒 <b>{day:%d.%m.%Y} ({WD_SHORT[day.weekday()]})</b>\nVaqtni tanlang:", Markup(rows))


async def last_phone(session, bot_id: int, user_id: int):
    return (await session.execute(
        select(Booking.phone).where(Booking.bot_id == bot_id, Booking.tg_user_id == user_id, Booking.phone.isnot(None))
        .order_by(Booking.id.desc()).limit(1)
    )).scalar_one_or_none()


def _chosen_start(data, st):
    tz = tz_of(st.timezone)
    day = date.fromisoformat(data["day"])
    hh, mm = int(data["time"][:2]), int(data["time"][2:])
    return datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(UTC)


async def show_confirm(tg, callback, chat_id, session, bot, us):
    data = dict(us.state_data or {})
    service = await session.get(BookingService, data.get("svc"))
    st = await get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    start = _chosen_start(data, st)
    staff = await session.get(BookingStaff, data["stf"]) if data.get("stf") else None
    lines = ["📝 <b>Bronni tasdiqlang</b>", "", f"🧾 {esc(service.name)} ({service.duration_min} daq)"]
    if staff:
        lines.append(f"👤 {esc(staff.name)}")
    elif (await eligible_staff(session, bot.id, service.id))[0]:
        lines.append("👤 Mutaxassis avtomatik tanlanadi")
    lines += [f"🗓 {fmt_dt(start, tz)}", f"📞 {esc(data.get('phone'))}"]
    if service.price:
        lines.append(f"💰 {money(service.price)}")
    if not st.auto_confirm:
        lines.append("\nℹ️ Bron admin tasdiqlagandan keyin kuchga kiradi.")
    rows = [[Btn("✅ Tasdiqlash", callback_data="bk:ok")],
            [Btn("📞 Raqamni o‘zgartirish", callback_data="bk:ph"), Btn("✖️ Bekor qilish", callback_data="bk:home")]]
    await cinema._show(tg, callback, chat_id, "\n".join(lines), Markup(rows))


async def ask_phone(tg, chat_id, session, us, data):
    await set_state(session, us, "bk_phone", data)
    kb = ReplyKeyboardMarkup([[KeyboardButton("📱 Raqamni yuborish", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await tg.send_message(chat_id=chat_id, text="📞 Telefon raqamingizni yuboring (tugma orqali yoki yozib: +998901234567).",
                          reply_markup=kb)


async def finish_booking(tg, callback, chat_id, session, bot, us, user: dict):
    data = dict(us.state_data or {})
    service = await session.get(BookingService, data.get("svc"))
    if not service or not service.is_active or "time" not in data or "day" not in data:
        await cinema._show(tg, callback, chat_id, "⚠️ Bron ma’lumotlari eskirgan. Qaytadan boshlang.", home_markup(False))
        return
    st = await get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    start = _chosen_start(data, st)
    booking = await create_booking(session, bot, st, service, data.get("stf") or None, start, user, data["phone"])
    if booking is None:
        await set_state(session, us, "bk", {k: v for k, v in data.items() if k not in ("time",)})
        await cinema._show(tg, callback, chat_id, "😕 Afsus, bu vaqt hozirgina band bo‘ldi. Boshqa vaqtni tanlang.",
                           Markup([[Btn("🕒 Boshqa vaqt", callback_data=f"bk:d:{data['day'].replace('-', '')}")]]))
        return
    await set_state(session, us)
    if booking.status == CONFIRMED:
        head = "✅ <b>Bron tasdiqlandi!</b>"
    else:
        head = "⏳ <b>Bron qabul qilindi.</b> Admin tasdiqlashi bilan sizga xabar beramiz."
    await cinema._show(tg, callback, chat_id, f"{head}\n\n{card(booking, tz)}",
                       Markup([[Btn("📋 Mening bronlarim", callback_data="bk:my")], [Btn("🏠 Bosh sahifa", callback_data="bk:home")]]))
    await notify_admins(tg, bot, session, "🔔 <b>Yangi bron</b>\n\n" + card(booking, tz, with_client=True), admin_buttons(booking))


async def show_my(tg, callback, chat_id, session, bot, user_id):
    st = await get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    items = (await session.execute(
        select(Booking).where(Booking.bot_id == bot.id, Booking.tg_user_id == user_id,
                              Booking.status.in_(ACTIVE_STATUSES), Booking.end_at >= utcnow())
        .order_by(Booking.start_at).limit(10)
    )).scalars().all()
    if not items:
        await cinema._show(tg, callback, chat_id, "📭 Sizda kelgusi bronlar yo‘q.",
                           Markup([[Btn("📅 Bron qilish", callback_data="bk:new")], [Btn("⬅️ Orqaga", callback_data="bk:home")]]))
        return
    rows = [[Btn(f"{STATUS_ICON[b.status]} {local(b.start_at, tz):%d.%m %H:%M} · {b.service_name}"[:60], callback_data=f"bk:v:{b.id}")] for b in items]
    rows.append([Btn("⬅️ Orqaga", callback_data="bk:home")])
    await cinema._show(tg, callback, chat_id, "📋 <b>Mening bronlarim</b>", Markup(rows))


async def _own_booking(session, bot, user_id, booking_id):
    b = await session.get(Booking, booking_id)
    return b if b and b.bot_id == bot.id and b.tg_user_id == user_id else None


async def client_cancel(tg, callback, chat_id, session, bot, booking, admin):
    st = await get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    if as_utc(booking.start_at) - utcnow() < timedelta(minutes=st.cancel_deadline_min) and not admin:
        await cinema._show(tg, callback, chat_id,
                           f"⚠️ Bronni boshlanishiga {fmt_minutes(st.cancel_deadline_min)} qolganda bekor qilib bo‘lmaydi. "
                           "Iltimos, admin bilan bog‘laning.", Markup([[Btn("ℹ️ Aloqa", callback_data="bk:info")]]))
        return
    booking.status, booking.cancelled_by = CANCELLED, "client"
    await session.commit()
    await cinema._show(tg, callback, chat_id, "❌ Bron bekor qilindi.", Markup([[Btn("🏠 Bosh sahifa", callback_data="bk:home")]]))
    await notify_admins(tg, bot, session, "❌ <b>Mijoz bronni bekor qildi</b>\n\n" + card(booking, tz, with_client=True))


# ------------------------------------------------------------------ dispatch

async def handle(bot, update, session, tg):
    if update.get("callback_query"):
        await _on_callback(bot, update["callback_query"], session, tg)
    elif update.get("message"):
        await _on_message(bot, update["message"], session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    uid = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    admin = await cinema.is_admin(session, bot, uid)
    if data.startswith("ba:"):
        if admin:
            await booking_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    if data == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, uid, session, use_cache=False):
            await show_home(tg, None, uid, session, bot, admin)
        return
    if not data.startswith("bk:"):
        return
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)
    parts = data.split(":")
    action, arg = parts[1], (parts[2] if len(parts) > 2 else "")
    if action == "home":
        await set_state(session, us)
        await show_home(tg, callback, uid, session, bot, admin)
    elif action == "info":
        st = await get_settings(session, bot.id)
        text = esc(st.contact_text) if st.contact_text else "Ma’lumot kiritilmagan."
        await cinema._show(tg, callback, uid, f"ℹ️ <b>Ma’lumot</b>\n\n{text}", Markup([[Btn("⬅️ Orqaga", callback_data="bk:home")]]))
    elif action == "new":
        await set_state(session, us)
        await show_services(tg, callback, uid, session, bot)
    elif action == "s" and arg.isdigit():
        service = await session.get(BookingService, int(arg))
        if service and service.bot_id == bot.id and service.is_active:
            await after_service(tg, callback, uid, session, bot, us, service)
    elif action == "m" and arg.isdigit() and us.state == "bk":
        d = dict(us.state_data or {})
        d["stf"] = int(arg)
        await set_state(session, us, "bk", d)
        await show_days(tg, callback, uid, session, bot, us, 0)
    elif action == "dp" and arg.isdigit() and us.state in ("bk", "bk_phone"):
        await show_days(tg, callback, uid, session, bot, us, int(arg))
    elif action == "d" and len(arg) == 8 and arg.isdigit() and us.state == "bk":
        try:
            await show_times(tg, callback, uid, session, bot, us, date(int(arg[:4]), int(arg[4:6]), int(arg[6:])))
        except ValueError:
            return
    elif action == "t" and len(arg) == 4 and arg.isdigit() and us.state == "bk" and (us.state_data or {}).get("day"):
        d = dict(us.state_data)
        d["time"] = arg
        phone = d.get("phone") or await last_phone(session, bot.id, uid)
        if phone:
            d["phone"] = phone
            await set_state(session, us, "bk", d)
            await show_confirm(tg, callback, uid, session, bot, us)
        else:
            await ask_phone(tg, uid, session, us, d)
    elif action == "ph" and us.state == "bk":
        await ask_phone(tg, uid, session, us, dict(us.state_data or {}))
    elif action == "ok" and us.state == "bk":
        await finish_booking(tg, callback, uid, session, bot, us, user)
    elif action == "my":
        await show_my(tg, callback, uid, session, bot, uid)
    elif action in ("v", "c", "cy") and arg.isdigit():
        b = await _own_booking(session, bot, uid, int(arg))
        if b is None:
            return
        tz = tz_of((await get_settings(session, bot.id)).timezone)
        if action == "v":
            rows = [[Btn("❌ Bekor qilish", callback_data=f"bk:c:{b.id}")]] if b.status in ACTIVE_STATUSES else []
            await cinema._show(tg, callback, uid, card(b, tz), Markup(rows + [[Btn("⬅️ Orqaga", callback_data="bk:my")]]))
        elif b.status not in ACTIVE_STATUSES:
            await show_my(tg, callback, uid, session, bot, uid)
        elif action == "c":
            await cinema._show(tg, callback, uid, "❓ Bronni bekor qilmoqchimisiz?\n\n" + card(b, tz),
                               Markup([[Btn("✅ Ha, bekor qilish", callback_data=f"bk:cy:{b.id}"), Btn("↩️ Yo‘q", callback_data=f"bk:v:{b.id}")]]))
        else:
            await client_cancel(tg, callback, uid, session, bot, b, False)


async def _on_message(bot, message, session, tg):
    sender = message["from"]
    uid = sender["id"]
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    await touch_user(session, bot.id, sender)
    admin = await cinema.is_admin(session, bot, uid)
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)

    if cmd in ("/start", "/cancel"):
        await set_state(session, us)
        if cmd == "/cancel":
            await tg.send_message(chat_id=uid, text="Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        await show_home(tg, None, uid, session, bot, admin)
        return
    if admin and cmd == "/admin":
        await set_state(session, us)
        await booking_admin.show_home(tg, None, uid, session, bot)
        return
    if admin and us.state and us.state.startswith("ba_"):
        if await booking_admin.on_message(bot, message, session, tg, us):
            return
    if us.state == "bk_phone":
        raw = (message.get("contact") or {}).get("phone_number") or text
        try:
            phone = parse_phone(raw)
        except ValueError as exc:
            await tg.send_message(chat_id=uid, text=f"❌ {exc}")
            return
        d = dict(us.state_data or {})
        d["phone"] = phone
        await set_state(session, us, "bk", d)
        await tg.send_message(chat_id=uid, text="✅ Raqam qabul qilindi.", reply_markup=ReplyKeyboardRemove())
        await show_confirm(tg, None, uid, session, bot, us)
        return
    await show_home(tg, None, uid, session, bot, admin)
