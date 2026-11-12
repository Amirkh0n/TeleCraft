"""Admin panel of booking bots, used inside the child bot (``/admin``).

Callbacks are ``ba:<action>:...``; free-text answers go through a small state machine kept in
``UserSession.state`` (states start with ``ba_``). Admins are the owner plus the Telegram IDs
added from the constructor bot.
"""
from datetime import datetime, time, timedelta

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from engine import booking as core  # circular import: attributes are only used at call time
from engine import cinema
from engine.booking_time import (
    HOURS_HINT, UTC, WEEKDAYS, WD_SHORT, fmt_intervals, fmt_minutes, fmt_reminders, local,
    parse_day_range, parse_duration, parse_intervals, parse_price, parse_reminders, tz_of, utcnow, valid_tz,
)
from models.booking import (
    ACTIVE_STATUSES, CANCELLED, CONFIRMED, DONE, NO_SHOW, PENDING, REJECTED, Booking, BookingDayOff,
    BookingHours, BookingService, BookingStaff, BookingStaffService,
)

esc = cinema.esc
show = cinema._show
PAGE = 8

STEPS = (15, 20, 30, 45, 60)
NOTICES = (0, 30, 60, 120, 240, 720, 1440)
AHEAD = (7, 14, 30, 60, 90)
DEADLINES = (0, 60, 120, 240, 720, 1440)


def back(target="ba:home", label="⬅️ Orqaga"):
    return [Btn(label, callback_data=target)]


def _next(values, current):
    return values[(values.index(current) + 1) % len(values)] if current in values else values[0]


async def _own(session, model, bot, item_id):
    item = await session.get(model, item_id)
    return item if item is not None and item.bot_id == bot.id else None


async def _ask(session, us, tg, callback, chat_id, state, data, prompt, target):
    await core.set_state(session, us, state, data)
    await show(tg, callback, chat_id, prompt + "\nBekor qilish: /cancel", Markup([[Btn("✖️ Bekor qilish", callback_data=target)]]))


async def _done(tg, chat_id, text, target, label="⬅️ Orqaga"):
    await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=Markup([back(target, label)]))


# ------------------------------------------------------------------ home

async def show_home(tg, callback, chat_id, session, bot):
    pending = (await session.execute(select(func.count(Booking.id)).where(
        Booking.bot_id == bot.id, Booking.status == PENDING, Booking.end_at >= utcnow()))).scalar() or 0
    rows = [
        [Btn("📅 Bugungi bronlar", callback_data="ba:today"), Btn("🗓 Kelgusi", callback_data="ba:up:0")],
        [Btn(f"⏳ Tasdiq kutayotganlar ({pending})", callback_data="ba:pend")],
        [Btn("🧾 Xizmatlar", callback_data="ba:sv"), Btn("👤 Mutaxassislar", callback_data="ba:st")],
        [Btn("🕒 Ish vaqti", callback_data="ba:h:0"), Btn("🏖 Dam kunlari", callback_data="ba:do:0")],
        [Btn("⚙️ Sozlamalar", callback_data="ba:set"), Btn("📊 Statistika", callback_data="ba:stats")],
        [Btn("🏠 Mijoz menyusi", callback_data="bk:home")],
    ]
    await show(tg, callback, chat_id, "🛠 <b>Bron admin paneli</b>", Markup(rows))


# ------------------------------------------------------------------ bookings

async def list_bookings(tg, callback, chat_id, session, bot, kind: str, page: int = 0):
    st = await core.get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    now = utcnow()
    q = select(Booking).where(Booking.bot_id == bot.id)
    if kind == "today":
        day = local(now, tz).date()
        lo = datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC)
        q = q.where(Booking.status.in_(ACTIVE_STATUSES), Booking.start_at >= lo, Booking.start_at < lo + timedelta(days=1))
        title = "📅 <b>Bugungi bronlar</b>"
    elif kind == "pend":
        q = q.where(Booking.status == PENDING, Booking.end_at >= now)
        title = "⏳ <b>Tasdiq kutayotgan bronlar</b>"
    else:
        q = q.where(Booking.status.in_(ACTIVE_STATUSES), Booking.end_at >= now)
        title = "🗓 <b>Kelgusi bronlar</b>"
    total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    items = (await session.execute(q.order_by(Booking.start_at).limit(PAGE).offset(page * PAGE))).scalars().all()
    if not items:
        await show(tg, callback, chat_id, f"{title}\n\n📭 Bronlar yo‘q.", Markup([back()]))
        return
    fmt = "%H:%M" if kind == "today" else "%d.%m %H:%M"
    rows = [[Btn(f"{core.STATUS_ICON[b.status]} {local(b.start_at, tz).strftime(fmt)} · {b.client_name} · {b.service_name}"[:62],
                 callback_data=f"ba:b:{b.id}")] for b in items]
    nav = ([Btn("◀️", callback_data=f"ba:up:{page - 1}")] if kind == "up" and page else []) + \
          ([Btn("▶️", callback_data=f"ba:up:{page + 1}")] if kind == "up" and (page + 1) * PAGE < total else [])
    if nav:
        rows.append(nav)
    rows.append(back())
    await show(tg, callback, chat_id, f"{title} ({total})", Markup(rows))


def booking_markup(b) -> Markup:
    rows = []
    if b.status == PENDING:
        rows.append([Btn("✅ Tasdiqlash", callback_data=f"ba:bs:{b.id}:ok"), Btn("🚫 Rad etish", callback_data=f"ba:bs:{b.id}:no")])
    if b.status == CONFIRMED:
        rows.append([Btn("✔️ Bajarildi", callback_data=f"ba:bs:{b.id}:done"), Btn("👻 Kelmadi", callback_data=f"ba:bs:{b.id}:ns")])
    if b.status in ACTIVE_STATUSES:
        rows.append([Btn("❌ Bekor qilish", callback_data=f"ba:bs:{b.id}:cx")])
    rows.append(back("ba:up:0", "⬅️ Bronlar"))
    return Markup(rows)


TRANSITIONS = {  # action -> (allowed from, new status, client message)
    "ok": ((PENDING,), CONFIRMED, "✅ <b>Broningiz tasdiqlandi!</b>"),
    "no": ((PENDING,), REJECTED, "🚫 Afsus, broningiz rad etildi. Boshqa vaqtni tanlashingiz mumkin."),
    "cx": (ACTIVE_STATUSES, CANCELLED, "❌ Broningiz admin tomonidan bekor qilindi."),
    "done": ((CONFIRMED,), DONE, None),
    "ns": ((CONFIRMED,), NO_SHOW, None),
}


async def change_status(tg, callback, chat_id, session, bot, booking, action):
    allowed, new, message = TRANSITIONS[action]
    tz = tz_of((await core.get_settings(session, bot.id)).timezone)
    if booking.status not in allowed:
        await show(tg, callback, chat_id, "ℹ️ Bu bron allaqachon o‘zgargan.\n\n" + core.card(booking, tz, with_client=True), booking_markup(booking))
        return
    booking.status = new
    if new == CANCELLED:
        booking.cancelled_by = "admin"
    await session.commit()
    await show(tg, callback, chat_id, core.card(booking, tz, with_client=True), booking_markup(booking))
    if message:
        await core.tell(tg, booking.tg_user_id, f"{message}\n\n{core.card(booking, tz)}",
                        Markup([[Btn("📋 Mening bronlarim", callback_data="bk:my")]]))


# ------------------------------------------------------------------ services

async def show_services(tg, callback, chat_id, session, bot):
    items = (await session.execute(select(BookingService).where(BookingService.bot_id == bot.id)
                                   .order_by(BookingService.position, BookingService.id))).scalars().all()
    rows = [[Btn(f"{'' if s.is_active else '⏸ '}{s.name} · {s.duration_min} daq"[:60], callback_data=f"ba:svo:{s.id}")] for s in items]
    rows += [[Btn("➕ Yangi xizmat", callback_data="ba:svn")], back()]
    text = "🧾 <b>Xizmatlar</b>" + ("" if items else "\n\nHali xizmat yo‘q. Mijozlar bron qilishi uchun kamida bittasini qo‘shing.")
    await show(tg, callback, chat_id, text, Markup(rows))


async def show_service(tg, callback, chat_id, session, bot, s):
    price = core.money(s.price) or "kiritilmagan"
    text = (f"🧾 <b>{esc(s.name)}</b>\n⏱ Davomiyligi: {s.duration_min} daqiqa\n💰 Narxi: {price}\n"
            f"📝 {esc(s.description) if s.description else 'Tavsif yo‘q'}\nHolati: {'faol' if s.is_active else '⏸ o‘chirilgan (mijozlar ko‘rmaydi)'}")
    i = s.id
    rows = [[Btn("✏️ Nomi", callback_data=f"ba:sve:{i}:name"), Btn("⏱ Davomiyligi", callback_data=f"ba:sve:{i}:dur")],
            [Btn("💰 Narxi", callback_data=f"ba:sve:{i}:price"), Btn("📝 Tavsifi", callback_data=f"ba:sve:{i}:desc")],
            [Btn("⏸ O‘chirib qo‘yish" if s.is_active else "▶️ Yoqish", callback_data=f"ba:svt:{i}")],
            [Btn("🗑 O‘chirish", callback_data=f"ba:svd:{i}")], back("ba:sv", "⬅️ Xizmatlar")]
    await show(tg, callback, chat_id, text, Markup(rows))


async def _has_future(session, bot_id, **where) -> int:
    q = select(func.count(Booking.id)).where(Booking.bot_id == bot_id, Booking.status.in_(ACTIVE_STATUSES), Booking.end_at >= utcnow())
    for column, value in where.items():
        q = q.where(getattr(Booking, column) == value)
    return (await session.execute(q)).scalar() or 0


# ------------------------------------------------------------------ specialists

async def show_staff_list(tg, callback, chat_id, session, bot):
    items = (await session.execute(select(BookingStaff).where(BookingStaff.bot_id == bot.id)
                                   .order_by(BookingStaff.position, BookingStaff.id))).scalars().all()
    rows = [[Btn(f"{'' if s.is_active else '⏸ '}👤 {s.name}"[:60], callback_data=f"ba:sto:{s.id}")] for s in items]
    rows += [[Btn("➕ Yangi mutaxassis", callback_data="ba:stn")], back()]
    text = ("👤 <b>Mutaxassislar</b>\n\nMutaxassis (usta, shifokor, o‘qituvchi) qo‘shsangiz, mijoz tanlay oladi va har biriga alohida jadval qo‘yiladi. "
            "Hech kim qo‘shilmasa, bitta umumiy jadval ishlaydi.")
    await show(tg, callback, chat_id, text, Markup(rows))


async def show_staff(tg, callback, chat_id, session, bot, s):
    links = (await session.execute(select(BookingService.name).join(
        BookingStaffService, BookingStaffService.service_id == BookingService.id).where(BookingStaffService.staff_id == s.id))).scalars().all()
    own = (await session.execute(select(func.count(BookingHours.id)).where(BookingHours.staff_id == s.id))).scalar()
    text = (f"👤 <b>{esc(s.name)}</b>\nHolati: {'faol' if s.is_active else '⏸ o‘chirilgan'}\n"
            f"🧾 Xizmatlar: {esc(', '.join(links)) if links else 'hammasi'}\n🕒 Jadval: {'o‘z jadvali' if own else 'umumiy ish vaqti'}")
    i = s.id
    rows = [[Btn("✏️ Ismi", callback_data=f"ba:ste:{i}"), Btn("🧾 Xizmatlari", callback_data=f"ba:sts:{i}")],
            [Btn("🕒 Ish vaqti", callback_data=f"ba:h:{i}"), Btn("🏖 Dam kunlari", callback_data=f"ba:do:{i}")],
            [Btn("⏸ O‘chirib qo‘yish" if s.is_active else "▶️ Yoqish", callback_data=f"ba:stt:{i}")],
            [Btn("🗑 O‘chirish", callback_data=f"ba:std:{i}")], back("ba:st", "⬅️ Mutaxassislar")]
    await show(tg, callback, chat_id, text, Markup(rows))


async def show_staff_services(tg, callback, chat_id, session, bot, s):
    services = (await session.execute(select(BookingService).where(BookingService.bot_id == bot.id)
                                      .order_by(BookingService.position, BookingService.id))).scalars().all()
    chosen = set((await session.execute(select(BookingStaffService.service_id).where(BookingStaffService.staff_id == s.id))).scalars().all())
    rows = [[Btn(f"{'☑️' if x.id in chosen else '⬜'} {x.name}"[:60], callback_data=f"ba:stx:{s.id}:{x.id}")] for x in services]
    rows.append(back(f"ba:sto:{s.id}"))
    await show(tg, callback, chat_id, f"🧾 <b>{esc(s.name)}</b> qaysi xizmatlarni bajaradi?\nHech biri belgilanmasa — hammasini.", Markup(rows))


# ------------------------------------------------------------------ hours & days off

async def scope_title(session, bot, scope: int):
    if not scope:
        return "Umumiy ish vaqti", "ba:home"
    s = await _own(session, BookingStaff, bot, scope)
    return (f"{s.name} — ish vaqti", f"ba:sto:{scope}") if s else (None, None)


async def show_hours(tg, callback, chat_id, session, bot, scope: int):
    title, target = await scope_title(session, bot, scope)
    if title is None:
        return await show_home(tg, callback, chat_id, session, bot)
    cond = BookingHours.staff_id.is_(None) if not scope else BookingHours.staff_id == scope
    rows_db = (await session.execute(select(BookingHours).where(BookingHours.bot_id == bot.id, cond)
                                     .order_by(BookingHours.start_min))).scalars().all()
    week: dict[int, list] = {}
    for r in rows_db:
        week.setdefault(r.weekday, []).append((r.start_min, r.end_min))
    note = "" if (rows_db or not scope) else "\n<i>Hozir umumiy ish vaqti ishlatiladi. Kunni o‘zgartirsangiz, shaxsiy jadval yaratiladi.</i>"
    lines = [f"🕒 <b>{esc(title)}</b>", ""] + [f"<b>{WD_SHORT[d]}</b>: {fmt_intervals(week.get(d, []))}" if rows_db or not scope else f"<b>{WD_SHORT[d]}</b>: —" for d in range(7)]
    buttons = [[Btn(f"✏️ {WEEKDAYS[d]}", callback_data=f"ba:hd:{scope}:{d}")] for d in range(7)]
    buttons.append([Btn("⚡ Du–Ju", callback_data=f"ba:hall:{scope}:5"), Btn("⚡ Du–Sha", callback_data=f"ba:hall:{scope}:6"), Btn("⚡ Har kuni", callback_data=f"ba:hall:{scope}:7")])
    if scope and rows_db:
        buttons.append([Btn("↩️ Umumiy jadvalga qaytish", callback_data=f"ba:hreset:{scope}")])
    buttons.append(back(target))
    await show(tg, callback, chat_id, "\n".join(lines) + note, Markup(buttons))


async def _ensure_own_schedule(session, bot_id, scope):
    """A specialist's first edit copies the business hours, so other weekdays do not become days off."""
    if not scope:
        return
    has = (await session.execute(select(func.count(BookingHours.id)).where(BookingHours.staff_id == scope))).scalar()
    if has:
        return
    base = (await session.execute(select(BookingHours).where(BookingHours.bot_id == bot_id, BookingHours.staff_id.is_(None)))).scalars().all()
    session.add_all(BookingHours(bot_id=bot_id, staff_id=scope, weekday=r.weekday, start_min=r.start_min, end_min=r.end_min) for r in base)
    await session.flush()


async def save_hours(session, bot_id, scope, weekdays, intervals):
    await _ensure_own_schedule(session, bot_id, scope)
    cond = BookingHours.staff_id.is_(None) if not scope else BookingHours.staff_id == scope
    await session.execute(delete(BookingHours).where(BookingHours.bot_id == bot_id, cond, BookingHours.weekday.in_(list(weekdays))))
    for wd in weekdays:
        session.add_all(BookingHours(bot_id=bot_id, staff_id=scope or None, weekday=wd, start_min=a, end_min=b) for a, b in intervals)
    await session.commit()


async def show_days_off(tg, callback, chat_id, session, bot, scope: int):
    title, target = await scope_title(session, bot, scope)
    if title is None:
        return await show_home(tg, callback, chat_id, session, bot)
    tz = tz_of((await core.get_settings(session, bot.id)).timezone)
    cond = BookingDayOff.staff_id.is_(None) if not scope else BookingDayOff.staff_id == scope
    today = local(utcnow(), tz).date()
    items = (await session.execute(select(BookingDayOff).where(BookingDayOff.bot_id == bot.id, cond, BookingDayOff.day >= today)
                                   .order_by(BookingDayOff.day).limit(20))).scalars().all()
    who = "butun biznes" if not scope else title.split(" — ")[0]
    rows = [[Btn(f"❌ {d.day:%d.%m.%Y} ({WD_SHORT[d.day.weekday()]})", callback_data=f"ba:dod:{d.id}")] for d in items]
    rows += [[Btn("➕ Dam kunini qo‘shish", callback_data=f"ba:doa:{scope}")], back(target)]
    await show(tg, callback, chat_id, f"🏖 <b>Dam kunlari — {esc(who)}</b>\n\nBu kunlarda bron qilib bo‘lmaydi (bayram, ta’til). Olib tashlash uchun kunni bosing."
               + ("" if items else "\n\n📭 Kelgusi dam kunlari yo‘q."), Markup(rows))


# ------------------------------------------------------------------ settings & stats

async def show_settings(tg, callback, chat_id, session, bot):
    st = await core.get_settings(session, bot.id)
    text = (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"✅ Tasdiqlash: <b>{'avtomatik' if st.auto_confirm else 'admin qo‘lda'}</b>\n"
        f"🧩 Vaqt qadami: <b>{st.slot_step_min} daq</b>\n"
        f"⏳ Eng kam oldindan: <b>{fmt_minutes(st.min_notice_min) if st.min_notice_min else 'cheklov yo‘q'}</b>\n"
        f"📆 Necha kun oldin: <b>{st.max_days_ahead} kun</b>\n"
        f"🚫 Bekor qilish muddati: <b>{fmt_minutes(st.cancel_deadline_min) + ' qolguncha' if st.cancel_deadline_min else 'istalgan payt'}</b>\n"
        f"⏰ Eslatmalar: <b>{fmt_reminders(st.reminders)}</b>\n"
        f"🌍 Vaqt mintaqasi: <b>{esc(st.timezone)}</b>\n"
        f"ℹ️ Aloqa: {esc(st.contact_text) if st.contact_text else '—'}"
    )
    rows = [
        [Btn("✅ Tasdiqlash usuli", callback_data="ba:sa"), Btn("🧩 Vaqt qadami", callback_data="ba:sstep")],
        [Btn("⏳ Eng kam oldindan", callback_data="ba:snotice"), Btn("📆 Necha kun oldin", callback_data="ba:sahead")],
        [Btn("🚫 Bekor qilish muddati", callback_data="ba:scancel")],
        [Btn("⏰ Eslatmalar", callback_data="ba:srem"), Btn("🌍 Vaqt mintaqasi", callback_data="ba:stz")],
        [Btn("ℹ️ Aloqa ma’lumoti", callback_data="ba:sc")], back(),
    ]
    await show(tg, callback, chat_id, text, Markup(rows))


async def show_stats(tg, callback, chat_id, session, bot):
    st = await core.get_settings(session, bot.id)
    tz = tz_of(st.timezone)
    now = utcnow()
    today = local(now, tz).date()
    day0 = datetime.combine(today, time(0), tzinfo=tz).astimezone(UTC)
    month0 = datetime.combine(today.replace(day=1), time(0), tzinfo=tz).astimezone(UTC)

    async def count(*conds):
        return (await session.execute(select(func.count(Booking.id)).where(Booking.bot_id == bot.id, *conds))).scalar() or 0

    today_n = await count(Booking.status.in_(ACTIVE_STATUSES), Booking.start_at >= day0, Booking.start_at < day0 + timedelta(days=1))
    week_n = await count(Booking.status.in_(ACTIVE_STATUSES), Booking.start_at >= now, Booking.start_at < now + timedelta(days=7))
    pending = await count(Booking.status == PENDING, Booking.end_at >= now)
    month_all = await count(Booking.start_at >= month0)
    by_status = dict((await session.execute(select(Booking.status, func.count(Booking.id)).where(
        Booking.bot_id == bot.id, Booking.start_at >= month0).group_by(Booking.status))).all())
    revenue = (await session.execute(select(func.coalesce(func.sum(Booking.price), 0)).where(
        Booking.bot_id == bot.id, Booking.start_at >= month0, Booking.status.in_((CONFIRMED, DONE))))).scalar() or 0
    clients = (await session.execute(select(func.count(func.distinct(Booking.tg_user_id))).where(Booking.bot_id == bot.id))).scalar() or 0
    top = (await session.execute(select(Booking.service_name, func.count(Booking.id).label("n")).where(
        Booking.bot_id == bot.id, Booking.status.in_((CONFIRMED, DONE))).group_by(Booking.service_name)
        .order_by(func.count(Booking.id).desc()).limit(5))).all()
    lines = [
        "📊 <b>Statistika</b>", "",
        f"📅 Bugun: <b>{today_n}</b>   🗓 Keyingi 7 kun: <b>{week_n}</b>   ⏳ Kutayotgan: <b>{pending}</b>", "",
        f"<b>Shu oy</b> ({month_all} ta bron)",
        f"✅ Tasdiqlangan: {by_status.get(CONFIRMED, 0)}   ✔️ Bajarilgan: {by_status.get(DONE, 0)}",
        f"❌ Bekor: {by_status.get(CANCELLED, 0)}   🚫 Rad: {by_status.get(REJECTED, 0)}   👻 Kelmagan: {by_status.get(NO_SHOW, 0)}",
    ]
    if revenue:
        lines.append(f"💰 Taxminiy tushum: {core.money(revenue)}")
    lines.append(f"\n🙋 Jami mijozlar: <b>{clients}</b>")
    if top:
        lines += ["", "🔥 <b>Mashhur xizmatlar:</b>"] + [f"{n}. {esc(name)} — {c}" for n, (name, c) in enumerate(top, 1)]
    await show(tg, callback, chat_id, "\n".join(lines), Markup([back()]))


# ------------------------------------------------------------------ callbacks

async def on_callback(bot, callback, session, tg, us):
    chat_id = callback["from"]["id"]
    parts = callback["data"].split(":")
    act = parts[1] if len(parts) > 1 else ""
    num = [int(p) for p in parts[2:] if p.lstrip("-").isdigit()]
    arg = parts[2:]

    async def home():
        await core.set_state(session, us)
        await show_home(tg, callback, chat_id, session, bot)

    if act in ("home", "cancel"):
        return await home()
    if act in ("today", "pend"):
        return await list_bookings(tg, callback, chat_id, session, bot, act)
    if act == "up":
        return await list_bookings(tg, callback, chat_id, session, bot, "up", num[0] if num else 0)
    if act in ("b", "bs") and num:
        booking = await _own(session, Booking, bot, num[0])
        if booking is None:
            return await show(tg, callback, chat_id, "Bron topilmadi.", Markup([back()]))
        if act == "bs" and len(arg) > 1 and arg[1] in TRANSITIONS:
            return await change_status(tg, callback, chat_id, session, bot, booking, arg[1])
        tz = tz_of((await core.get_settings(session, bot.id)).timezone)
        return await show(tg, callback, chat_id, core.card(booking, tz, with_client=True), booking_markup(booking))

    # --- services
    if act == "sv":
        return await show_services(tg, callback, chat_id, session, bot)
    if act == "svn":
        return await _ask(session, us, tg, callback, chat_id, "ba_svn_name", {}, "🧾 Yangi xizmat <b>nomini</b> yuboring (masalan: Soch olish).", "ba:sv")
    if act in ("svo", "sve", "svt", "svd", "svdy") and num:
        s = await _own(session, BookingService, bot, num[0])
        if s is None:
            return await show_services(tg, callback, chat_id, session, bot)
        if act == "svo":
            await core.set_state(session, us)
            return await show_service(tg, callback, chat_id, session, bot, s)
        if act == "svt":
            s.is_active = not s.is_active
            await session.commit()
            return await show_service(tg, callback, chat_id, session, bot, s)
        if act == "sve":
            field = arg[1] if len(arg) > 1 else ""
            prompts = {"name": "✏️ Yangi <b>nomni</b> yuboring.", "dur": "⏱ Yangi <b>davomiylikni</b> daqiqada yuboring (masalan 45).",
                       "price": "💰 Yangi <b>narxni</b> so‘mda yuboring (olib tashlash: /skip).", "desc": "📝 Qisqa <b>tavsif</b> yuboring (olib tashlash: /skip)."}
            if field in prompts:
                await _ask(session, us, tg, callback, chat_id, "ba_sve", {"id": s.id, "field": field}, prompts[field], f"ba:svo:{s.id}")
            return
        if act == "svd":
            future = await _has_future(session, bot.id, service_id=s.id)
            if future:
                return await show(tg, callback, chat_id, f"⚠️ Bu xizmatda {future} ta kelgusi bron bor, o‘chirib bo‘lmaydi. Hozircha «o‘chirib qo‘yish» dan foydalaning.",
                                  Markup([back(f"ba:svo:{s.id}")]))
            return await show(tg, callback, chat_id, f"🗑 <b>{esc(s.name)}</b> o‘chirilsinmi?",
                              Markup([[Btn("✅ Ha", callback_data=f"ba:svdy:{s.id}"), Btn("❌ Yo‘q", callback_data=f"ba:svo:{s.id}")]]))
        if await _has_future(session, bot.id, service_id=s.id):  # re-check: the confirm button may be stale/forged
            return await show_service(tg, callback, chat_id, session, bot, s)
        await session.execute(delete(BookingStaffService).where(BookingStaffService.service_id == s.id))
        await session.delete(s)
        await session.commit()
        return await show_services(tg, callback, chat_id, session, bot)

    # --- specialists
    if act == "st":
        return await show_staff_list(tg, callback, chat_id, session, bot)
    if act == "stn":
        return await _ask(session, us, tg, callback, chat_id, "ba_stn", {}, "👤 Mutaxassis <b>ismini</b> yuboring.", "ba:st")
    if act in ("sto", "ste", "stt", "sts", "stx", "std", "stdy") and num:
        s = await _own(session, BookingStaff, bot, num[0])
        if s is None:
            return await show_staff_list(tg, callback, chat_id, session, bot)
        if act == "sto":
            await core.set_state(session, us)
            return await show_staff(tg, callback, chat_id, session, bot, s)
        if act == "ste":
            return await _ask(session, us, tg, callback, chat_id, "ba_ste", {"id": s.id}, "✏️ Yangi <b>ismni</b> yuboring.", f"ba:sto:{s.id}")
        if act == "stt":
            s.is_active = not s.is_active
            await session.commit()
            return await show_staff(tg, callback, chat_id, session, bot, s)
        if act == "sts":
            return await show_staff_services(tg, callback, chat_id, session, bot, s)
        if act == "stx" and len(num) > 1:
            service = await _own(session, BookingService, bot, num[1])
            if service:
                link = await session.get(BookingStaffService, (s.id, service.id))
                if link:
                    await session.delete(link)
                else:
                    session.add(BookingStaffService(staff_id=s.id, service_id=service.id))
                await session.commit()
            return await show_staff_services(tg, callback, chat_id, session, bot, s)
        if act == "std":
            future = await _has_future(session, bot.id, staff_id=s.id)
            if future:
                return await show(tg, callback, chat_id, f"⚠️ {esc(s.name)} da {future} ta kelgusi bron bor, o‘chirib bo‘lmaydi. Hozircha «o‘chirib qo‘yish» dan foydalaning.",
                                  Markup([back(f"ba:sto:{s.id}")]))
            return await show(tg, callback, chat_id, f"🗑 <b>{esc(s.name)}</b> o‘chirilsinmi? (jadvali va dam kunlari ham o‘chadi)",
                              Markup([[Btn("✅ Ha", callback_data=f"ba:stdy:{s.id}"), Btn("❌ Yo‘q", callback_data=f"ba:sto:{s.id}")]]))
        if await _has_future(session, bot.id, staff_id=s.id):
            return await show_staff(tg, callback, chat_id, session, bot, s)
        for model in (BookingStaffService, BookingHours, BookingDayOff):
            await session.execute(delete(model).where(model.staff_id == s.id))
        await session.delete(s)
        await session.commit()
        return await show_staff_list(tg, callback, chat_id, session, bot)

    # --- hours / days off
    if act == "h" and num:
        await core.set_state(session, us)
        return await show_hours(tg, callback, chat_id, session, bot, num[0])
    if act in ("hd", "hall", "hreset") and num:
        scope = num[0]
        title, target = await scope_title(session, bot, scope)
        if title is None:
            return await home()
        if act == "hreset":
            await session.execute(delete(BookingHours).where(BookingHours.staff_id == scope))
            await session.commit()
            return await show_hours(tg, callback, chat_id, session, bot, scope)
        if act == "hd" and len(num) > 1 and 0 <= num[1] <= 6:
            return await _ask(session, us, tg, callback, chat_id, "ba_hd", {"scope": scope, "wd": num[1]},
                              f"🕒 <b>{WEEKDAYS[num[1]]}</b> uchun ish vaqtini yuboring.\n{HOURS_HINT}", f"ba:h:{scope}")
        if act == "hall" and len(num) > 1 and num[1] in (5, 6, 7):
            return await _ask(session, us, tg, callback, chat_id, "ba_hall", {"scope": scope, "n": num[1]},
                              f"🕒 Hamma kunlar ({WD_SHORT[0]}–{WD_SHORT[num[1] - 1]}) uchun bir xil ish vaqtini yuboring.\n{HOURS_HINT}", f"ba:h:{scope}")
        return
    if act == "do" and num:
        await core.set_state(session, us)
        return await show_days_off(tg, callback, chat_id, session, bot, num[0])
    if act == "doa" and num:
        return await _ask(session, us, tg, callback, chat_id, "ba_doa", {"scope": num[0]},
                          "🏖 Dam kunini yuboring: <code>25.12.2026</code> yoki oraliq: <code>25.12.2026 - 05.01.2027</code>.", f"ba:do:{num[0]}")
    if act == "dod" and num:
        item = await _own(session, BookingDayOff, bot, num[0])
        scope = (item.staff_id or 0) if item else 0
        if item:
            await session.delete(item)
            await session.commit()
        return await show_days_off(tg, callback, chat_id, session, bot, scope)

    # --- settings
    if act == "set":
        await core.set_state(session, us)
        return await show_settings(tg, callback, chat_id, session, bot)
    if act in ("sa", "sstep", "snotice", "sahead", "scancel"):
        st = await core.get_settings(session, bot.id)
        if act == "sa":
            st.auto_confirm = not st.auto_confirm
        elif act == "sstep":
            st.slot_step_min = _next(STEPS, st.slot_step_min)
        elif act == "snotice":
            st.min_notice_min = _next(NOTICES, st.min_notice_min)
        elif act == "sahead":
            st.max_days_ahead = _next(AHEAD, st.max_days_ahead)
        else:
            st.cancel_deadline_min = _next(DEADLINES, st.cancel_deadline_min)
        await session.commit()
        return await show_settings(tg, callback, chat_id, session, bot)
    if act == "srem":
        return await _ask(session, us, tg, callback, chat_id, "ba_srem", {},
                          "⏰ Mijozga bron oldidan qachon eslatma yuborilsin? Vaqtlarni vergul bilan yozing.\n"
                          "Masalan: <code>1 kun, 2 soat</code> yoki <code>24h, 30m</code>. O‘chirish: <code>yo‘q</code>.", "ba:set")
    if act == "sc":
        return await _ask(session, us, tg, callback, chat_id, "ba_sc", {},
                          "ℹ️ Mijozlarga ko‘rsatiladigan <b>aloqa ma’lumotini</b> yuboring (manzil, telefon, ish vaqti...). Olib tashlash: /skip.", "ba:set")
    if act == "stz":
        return await _ask(session, us, tg, callback, chat_id, "ba_stz", {},
                          "🌍 Vaqt mintaqasini yuboring, masalan <code>Asia/Tashkent</code>, <code>Europe/Moscow</code>.", "ba:set")
    if act == "stats":
        return await show_stats(tg, callback, chat_id, session, bot)


# ------------------------------------------------------------------ free-text answers

async def on_message(bot, message, session, tg, us) -> bool:
    state, data = us.state or "", dict(us.state_data or {})
    chat_id = message["from"]["id"]
    text = (message.get("text") or "").strip()
    if not text:
        await tg.send_message(chat_id=chat_id, text="Matn yuboring. Bekor qilish: /cancel")
        return True

    async def fail(error):
        await tg.send_message(chat_id=chat_id, text=f"❌ {error}", parse_mode="HTML")
        return True

    try:
        if state == "ba_svn_name":
            data["name"] = text[:120]
            await core.set_state(session, us, "ba_svn_dur", data)
            await tg.send_message(chat_id=chat_id, parse_mode="HTML", text="⏱ Davomiyligini <b>daqiqada</b> yuboring (masalan 45).")
        elif state == "ba_svn_dur":
            data["dur"] = parse_duration(text)
            await core.set_state(session, us, "ba_svn_price", data)
            await tg.send_message(chat_id=chat_id, parse_mode="HTML", text="💰 <b>Narxini</b> so‘mda yuboring (masalan 80000). Narx ko‘rsatilmasin: /skip")
        elif state == "ba_svn_price":
            price = parse_price(text)
            position = ((await session.execute(select(func.max(BookingService.position)).where(BookingService.bot_id == bot.id))).scalar() or 0) + 1
            service = BookingService(bot_id=bot.id, name=data["name"], duration_min=data["dur"], price=price, position=position)
            session.add(service)
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, f"✅ Xizmat qo‘shildi: <b>{esc(service.name)}</b>", f"ba:svo:{service.id}", "🧾 Xizmatga o‘tish")
        elif state == "ba_sve":
            s = await _own(session, BookingService, bot, data.get("id"))
            if s is None:
                await core.set_state(session, us)
                return await fail("Xizmat topilmadi.")
            field = data["field"]
            if field == "name":
                s.name = text[:120]
            elif field == "dur":
                s.duration_min = parse_duration(text)
            elif field == "price":
                s.price = parse_price(text)
            else:
                s.description = None if text == "/skip" else text[:500]
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, "✅ Saqlandi.", f"ba:svo:{s.id}", "🧾 Xizmatga qaytish")
        elif state == "ba_stn":
            position = ((await session.execute(select(func.max(BookingStaff.position)).where(BookingStaff.bot_id == bot.id))).scalar() or 0) + 1
            staff = BookingStaff(bot_id=bot.id, name=text[:120], position=position)
            session.add(staff)
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, f"✅ Mutaxassis qo‘shildi: <b>{esc(staff.name)}</b>\nEndi uning xizmatlari va ish vaqtini sozlang.", f"ba:sto:{staff.id}", "👤 Mutaxassisga o‘tish")
        elif state == "ba_ste":
            s = await _own(session, BookingStaff, bot, data.get("id"))
            if s is None:
                await core.set_state(session, us)
                return await fail("Mutaxassis topilmadi.")
            s.name = text[:120]
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, "✅ Saqlandi.", f"ba:sto:{s.id}", "👤 Qaytish")
        elif state in ("ba_hd", "ba_hall"):
            intervals = parse_intervals(text)
            scope = data.get("scope", 0)
            days = [data["wd"]] if state == "ba_hd" else list(range(data["n"]))
            await save_hours(session, bot.id, scope, days, intervals)
            await core.set_state(session, us)
            await _done(tg, chat_id, "✅ Ish vaqti saqlandi.", f"ba:h:{scope}", "🕒 Jadvalga qaytish")
        elif state == "ba_doa":
            scope = data.get("scope", 0)
            tz = tz_of((await core.get_settings(session, bot.id)).timezone)
            today = local(utcnow(), tz).date()
            days = [d for d in parse_day_range(text, today) if d >= today]
            if not days:
                return await fail("Bu sana o‘tib ketgan.")
            cond = BookingDayOff.staff_id.is_(None) if not scope else BookingDayOff.staff_id == scope
            have = set((await session.execute(select(BookingDayOff.day).where(BookingDayOff.bot_id == bot.id, cond))).scalars().all())
            session.add_all(BookingDayOff(bot_id=bot.id, staff_id=scope or None, day=d) for d in days if d not in have)
            await session.commit()
            await core.set_state(session, us)
            clash = await _has_future(session, bot.id)
            await _done(tg, chat_id, f"✅ Dam kuni qo‘shildi ({len(days)} kun)." + ("\n⚠️ Bu kunlarda oldindan olingan bronlar bo‘lishi mumkin — ularni «Kelgusi bronlar»dan tekshiring." if clash else ""),
                        f"ba:do:{scope}", "🏖 Ro‘yxatga qaytish")
        elif state == "ba_srem":
            st = await core.get_settings(session, bot.id)
            st.reminders = parse_reminders(text)
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, f"✅ Eslatmalar: {fmt_reminders(st.reminders)}", "ba:set", "⚙️ Sozlamalar")
        elif state == "ba_sc":
            st = await core.get_settings(session, bot.id)
            st.contact_text = None if text == "/skip" else text[:1000]
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, "✅ Saqlandi.", "ba:set", "⚙️ Sozlamalar")
        elif state == "ba_stz":
            if not valid_tz(text):
                return await fail("Bunday vaqt mintaqasi topilmadi. Masalan: <code>Asia/Tashkent</code>")
            st = await core.get_settings(session, bot.id)
            st.timezone = text
            await session.commit()
            await core.set_state(session, us)
            await _done(tg, chat_id, f"✅ Vaqt mintaqasi: {esc(text)}", "ba:set", "⚙️ Sozlamalar")
        else:
            await core.set_state(session, us)
            return False
    except ValueError as exc:
        return await fail(exc)
    return True
