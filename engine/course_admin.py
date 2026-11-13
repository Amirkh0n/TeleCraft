"""Admin side of the course bot, inside the child bot itself (``/admin``, ``ca:`` callbacks, ``ca_*`` states).

Admins create courses, modules and lessons, upload lesson files (stored by ``file_id``), review payment
receipts, answer students' questions and see statistics. Admins are the bot owner and the people added
from the constructor bot.
"""
from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.logger import get_logger
from engine import cinema
from engine.booking_time import utcnow, valid_tz
from models.course import (
    ACCESS_CODE, ACCESS_FREE, ACCESS_PAID, PAY_APPROVED, PAY_PENDING, PAY_REJECTED, UNLOCK_ALL, UNLOCK_DRIP, UNLOCK_SEQ,
    VIA_ADMIN, VIA_PAID, Course, CourseModule, CoursePayment, CourseQuestion, Enrollment, Lesson, LessonFile, LessonProgress,
)

logger = get_logger("course.admin")
esc = cinema.esc
show = cinema._show
PAGE = 8

ACCESS_NAMES = {ACCESS_FREE: "🆓 Bepul", ACCESS_CODE: "🔑 Kod bilan", ACCESS_PAID: "💰 Pullik"}
UNLOCK_NAMES = {UNLOCK_ALL: "🔓 Hammasi ochiq", UNLOCK_SEQ: "➡️ Ketma-ket", UNLOCK_DRIP: "📅 Jadval bo‘yicha"}

# (entity, field) -> (label, kind, limit). kinds: text, long, int, code, photo, card, tz, hour
FIELDS = {
    ("course", "title"): ("Kurs nomi", "text", 120),
    ("course", "description"): ("Kurs tavsifi", "long", 700),
    ("course", "cover"): ("Muqova rasmi", "photo", 0),
    ("course", "code"): ("Kirish kodi", "code", 40),
    ("course", "price"): ("Narx (so‘mda)", "int", 100_000_000),
    ("course", "days"): ("Necha kunda bitta dars ochilsin", "int", 30),
    ("module", "title"): ("Modul nomi", "text", 120),
    ("lesson", "title"): ("Dars nomi", "text", 120),
    ("lesson", "text"): ("Dars matni", "long", 3500),
    ("set", "card"): ("Karta raqami", "card", 40),
    ("set", "holder"): ("Karta egasi", "text", 120),
    ("set", "note"): ("To‘lov bo‘yicha izoh", "long", 500),
    ("set", "tz"): ("Vaqt mintaqasi (masalan Asia/Tashkent)", "tz", 64),
    ("set", "hour"): ("Yangi dars ochiladigan soat (0-23)", "hour", 23),
}


def core():
    from engine import course
    return course


def media_of(message):
    """(file_type, file_id, file_name) of a lesson attachment, or None."""
    if message.get("video"):
        return "video", message["video"]["file_id"], message["video"].get("file_name")
    if message.get("animation"):
        return "video", message["animation"]["file_id"], None
    if message.get("audio"):
        return "audio", message["audio"]["file_id"], message["audio"].get("file_name") or message["audio"].get("title")
    if message.get("document"):
        return "document", message["document"]["file_id"], message["document"].get("file_name")
    if message.get("photo"):
        return "photo", message["photo"][-1]["file_id"], None
    return None


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


def kb_of(rows):
    return Markup(rows)


def back(data, text="⬅️ Orqaga"):
    return [Btn(text, callback_data=data)]


# ------------------------------------------------------------------ home

async def show_home(tg, callback, chat_id, session, bot):
    pend = (await session.execute(select(func.count(CoursePayment.id)).where(
        CoursePayment.bot_id == bot.id, CoursePayment.status == PAY_PENDING))).scalar() or 0
    qs = (await session.execute(select(func.count(CourseQuestion.id)).where(
        CourseQuestion.bot_id == bot.id, CourseQuestion.answer.is_(None)))).scalar() or 0
    rows = [[Btn("📚 Kurslar", callback_data="ca:cl:0"), Btn("➕ Yangi kurs", callback_data="ca:cn")],
            [Btn(f"💳 To‘lovlar ({pend})", callback_data="ca:pays:0"), Btn(f"❓ Savollar ({qs})", callback_data="ca:qs:0")],
            [Btn("📊 Statistika", callback_data="ca:stats"), Btn("⚙️ Sozlamalar", callback_data="ca:set")],
            [Btn("🏠 Talaba ko‘rinishi", callback_data="cr:home")]]
    await show(tg, callback, chat_id, "🛠 <b>Admin panel</b>\nKurslar, to‘lovlar va savollarni shu yerda boshqarasiz.", kb_of(rows))


async def cancel(bot, session, tg, us, uid):
    await tg.send_message(chat_id=uid, text="Bekor qilindi.")


# ------------------------------------------------------------------ notifications

async def notify_payment(tg, session, bot, course, pay, user):
    caption = (f"💳 <b>Yangi to‘lov #{pay.id}</b>\n📘 {esc(course.title)} — {core().fmt_price(pay.amount)}\n"
               f"👤 {esc(pay.user_name)}  <code>{pay.tg_user_id}</code>")
    markup = kb_of([[Btn("✅ Tasdiqlash", callback_data=f"ca:pok:{pay.id}"), Btn("❌ Rad etish", callback_data=f"ca:prj:{pay.id}")]])
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            if pay.receipt_type == "photo":
                await tg.send_photo(chat_id=admin_id, photo=pay.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                await tg.send_document(chat_id=admin_id, document=pay.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=markup)
        except TelegramError as exc:
            logger.info("payment notice to %s failed: %s", admin_id, exc)


async def notify_question(tg, session, bot, q, lesson):
    text = (f"❓ <b>Yangi savol #{q.id}</b>\n📘 {esc(lesson.title)}\n👤 {esc(q.user_name)}  <code>{q.tg_user_id}</code>\n\n{esc(q.text)}")
    markup = kb_of([[Btn("💬 Javob berish", callback_data=f"ca:qo:{q.id}")]])
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await tg.send_message(chat_id=admin_id, text=text, parse_mode="HTML", reply_markup=markup)
        except TelegramError as exc:
            logger.info("question notice to %s failed: %s", admin_id, exc)


# ------------------------------------------------------------------ helpers

async def own_course(session, bot, course_id):
    c = await session.get(Course, course_id)
    return c if c and c.bot_id == bot.id else None


async def own_module(session, bot, module_id):
    m = await session.get(CourseModule, module_id)
    if m is None:
        return None, None
    c = await own_course(session, bot, m.course_id)
    return (m, c) if c else (None, None)


async def own_lesson(session, bot, lesson_id):
    ls = await session.get(Lesson, lesson_id)
    if ls is None:
        return None, None
    c = await own_course(session, bot, ls.course_id)
    return (ls, c) if c else (None, None)


async def move(session, items, item_id, delta):
    """Swap an item with its neighbour and renumber positions 0..n-1."""
    ids = [i.id for i in items]
    if item_id not in ids:
        return
    i = ids.index(item_id)
    j = i + delta
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
    for pos, item in enumerate(items):
        item.position = pos
    await session.commit()


async def confirm(tg, callback, uid, text, yes, no):
    await show(tg, callback, uid, text, kb_of([[Btn("✅ Ha", callback_data=yes), Btn("✖️ Yo‘q", callback_data=no)]]))


# ------------------------------------------------------------------ course screens

async def courses_list(tg, callback, uid, session, bot, page):
    total = (await session.execute(select(func.count(Course.id)).where(Course.bot_id == bot.id))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(Course).where(Course.bot_id == bot.id).order_by(Course.position, Course.id)
                                  .limit(PAGE).offset(page * PAGE))).scalars().all()
    kb = [[Btn(f"{'🟢' if c.is_published else '🚧'} {c.title}"[:60], callback_data=f"ca:c:{c.id}")] for c in rows]
    nav = ([Btn("⬅️", callback_data=f"ca:cl:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"ca:cl:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append([Btn("➕ Yangi kurs", callback_data="ca:cn")])
    kb.append(back("ca:home"))
    await show(tg, callback, uid, f"📚 <b>Kurslar</b> ({total})\n🟢 e’lon qilingan · 🚧 qoralama" if total else "Hali kurs yo‘q. «Yangi kurs» tugmasini bosing.", kb_of(kb))


async def course_card(tg, callback, uid, session, bot, course):
    mods = (await session.execute(select(func.count(CourseModule.id)).where(CourseModule.course_id == course.id))).scalar() or 0
    lessons = (await session.execute(select(func.count(Lesson.id)).where(Lesson.course_id == course.id))).scalar() or 0
    studs = (await session.execute(select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id))).scalar() or 0
    lines = [f"📘 <b>{esc(course.title)}</b> {'🟢 e’lon qilingan' if course.is_published else '🚧 qoralama'}",
             esc(course.description[:300]) if course.description else "<i>Tavsif yo‘q</i>",
             f"\n{ACCESS_NAMES[course.access]}" + (f" · {core().fmt_price(course.price)}" if course.access == ACCESS_PAID else "")
             + (f" · kod: <code>{esc(course.access_code)}</code>" if course.access == ACCESS_CODE and course.access_code else ""),
             f"{UNLOCK_NAMES[course.unlock_mode]}" + (f" (har {course.drip_days} kunda)" if course.unlock_mode == UNLOCK_DRIP else ""),
             f"📦 {mods} modul · {lessons} dars · 👥 {studs} o‘quvchi"]
    link = core().deep_link(bot, course)
    if link:
        lines.append(f"🔗 {link}")
    f = f"ca:ef:course:{course.id}:"
    rows = [[Btn("📦 Modullar va darslar", callback_data=f"ca:m:{course.id}")],
            [Btn("✏️ Nomi", callback_data=f + "title"), Btn("📝 Tavsif", callback_data=f + "description"), Btn("🖼 Muqova", callback_data=f + "cover")],
            [Btn("🆓", callback_data=f"ca:acc:{course.id}:free"), Btn("🔑", callback_data=f"ca:acc:{course.id}:code"), Btn("💰", callback_data=f"ca:acc:{course.id}:paid")]]
    if course.access == ACCESS_CODE:
        rows.append([Btn("🔑 Kodni o‘zgartirish", callback_data=f + "code")])
    if course.access == ACCESS_PAID:
        rows.append([Btn("💰 Narxni o‘zgartirish", callback_data=f + "price")])
    rows.append([Btn("🔓", callback_data=f"ca:um:{course.id}:all"), Btn("➡️", callback_data=f"ca:um:{course.id}:seq"), Btn("📅", callback_data=f"ca:um:{course.id}:drip")])
    if course.unlock_mode == UNLOCK_DRIP:
        rows.append([Btn("📅 Necha kunda bitta dars", callback_data=f + "days")])
    rows.append([Btn("🙈 Qoralamaga olish" if course.is_published else "🚀 E’lon qilish", callback_data=f"ca:pub:{course.id}"),
                 Btn("👥 O‘quvchilar", callback_data=f"ca:st:{course.id}:0")])
    rows.append([Btn("👁 Talaba ko‘rinishi", callback_data=f"cr:c:{course.id}"), Btn("🗑 O‘chirish", callback_data=f"ca:del:{course.id}")])
    rows.append(back("ca:cl:0", "⬅️ Kurslar"))
    lines.append("\n<i>Kirish: 🆓 bepul · 🔑 kod · 💰 pullik. Ochilish: 🔓 hammasi · ➡️ ketma-ket · 📅 jadval.</i>")
    await show(tg, callback, uid, "\n".join(lines), kb_of(rows))


async def modules_screen(tg, callback, uid, session, course):
    mods = await core().modules_of(session, course.id)
    kb = [[Btn(f"📂 {m.title}"[:60], callback_data=f"ca:mo:{m.id}")] for m in mods]
    kb.append([Btn("➕ Modul qo‘shish", callback_data=f"ca:mn:{course.id}")])
    kb.append(back(f"ca:c:{course.id}", "⬅️ Kurs"))
    await show(tg, callback, uid, f"📦 <b>{esc(course.title)}</b> — modullar" if mods else "Modul yo‘q. Avval modul qo‘shing (masalan «1-hafta»).", kb_of(kb))


async def module_screen(tg, callback, uid, session, module, course):
    lessons = list((await session.execute(select(Lesson).where(Lesson.module_id == module.id).order_by(Lesson.position, Lesson.id))).scalars().all())
    kb = [[Btn(f"{i + 1}. {ls.title}"[:60], callback_data=f"ca:lo:{ls.id}")] for i, ls in enumerate(lessons)]
    kb.append([Btn("➕ Dars qo‘shish", callback_data=f"ca:ln:{module.id}")])
    kb.append([Btn("✏️ Nomi", callback_data=f"ca:ef:module:{module.id}:title"), Btn("⬆️", callback_data=f"ca:mup:{module.id}"),
               Btn("⬇️", callback_data=f"ca:mdn:{module.id}"), Btn("🗑", callback_data=f"ca:mdel:{module.id}")])
    kb.append(back(f"ca:m:{course.id}", "⬅️ Modullar"))
    await show(tg, callback, uid, f"📂 <b>{esc(module.title)}</b>\nDarslar: {len(lessons)}", kb_of(kb))


async def lesson_screen(tg, callback, uid, session, lesson, course):
    files = await core().files_of(session, lesson.id)
    kinds = {}
    for f in files:
        kinds[f.file_type] = kinds.get(f.file_type, 0) + 1
    icons = {"video": "🎬", "audio": "🎧", "document": "📄", "photo": "🖼"}
    fl = " ".join(f"{icons.get(k, '📎')}×{v}" for k, v in kinds.items()) or "fayl yo‘q"
    text = (f"📘 <b>{esc(lesson.title)}</b>\n{esc(lesson.text[:300]) if lesson.text else '<i>Matn yo‘q</i>'}\n\n📎 {fl}"
            f"\n👁 Tanishuv darsi: {'ha' if lesson.is_preview else 'yo‘q'}")
    f = f"ca:ef:lesson:{lesson.id}:"
    kb = [[Btn("👁 Ko‘rish", callback_data=f"ca:lv:{lesson.id}")],
          [Btn("✏️ Nomi", callback_data=f + "title"), Btn("📝 Matn", callback_data=f + "text")],
          [Btn("📎 Fayl qo‘shish", callback_data=f"ca:lf:{lesson.id}"), Btn("🧹 Fayllarni tozalash", callback_data=f"ca:lfc:{lesson.id}")],
          [Btn("🎁 Tanishuv darsi" + (" ✅" if lesson.is_preview else ""), callback_data=f"ca:lpv:{lesson.id}")],
          [Btn("⬆️", callback_data=f"ca:lup:{lesson.id}"), Btn("⬇️", callback_data=f"ca:ldn:{lesson.id}"), Btn("🗑 O‘chirish", callback_data=f"ca:ldel:{lesson.id}")],
          back(f"ca:mo:{lesson.module_id}", "⬅️ Modul")]
    await show(tg, callback, uid, text, kb_of(kb))


async def settings_screen(tg, callback, uid, session, bot):
    st = await core().get_settings(session, bot.id)
    text = (f"⚙️ <b>Sozlamalar</b>\n\n💳 Karta: <code>{esc(st.card_number or '—')}</code>\n👤 Egasi: {esc(st.card_holder or '—')}\n"
            f"📝 Izoh: {esc(st.pay_note or '—')}\n🕘 Vaqt mintaqasi: {esc(st.timezone)}\n⏰ Jadvalli dars ochilish soati: {st.drip_hour:02d}:00\n"
            f"❓ Savollar: {'yoqilgan' if st.questions_enabled else 'o‘chiq'}")
    f = "ca:ef:set:0:"
    kb = [[Btn("💳 Karta", callback_data=f + "card"), Btn("👤 Egasi", callback_data=f + "holder")],
          [Btn("📝 To‘lov izohi", callback_data=f + "note")],
          [Btn("🕘 Mintaqa", callback_data=f + "tz"), Btn("⏰ Soat", callback_data=f + "hour")],
          [Btn("❓ Savollarni yoq/o‘chir", callback_data="ca:qt")], back("ca:home")]
    await show(tg, callback, uid, text, kb_of(kb))


# ------------------------------------------------------------------ callbacks

async def on_callback(bot, callback, session, tg, us):
    uid = callback["from"]["id"]
    parts = (callback.get("data") or "").split(":")
    act, arg = parts[1], parts[2:]
    num = [int(p) for p in arg if p.lstrip("-").isdigit()]
    if us.state and us.state.startswith("ca_"):
        await set_state(session, us)
    n0 = num[0] if num else 0

    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "cl":
        return await courses_list(tg, callback, uid, session, bot, n0)
    if act == "cn":
        await set_state(session, us, "ca_new")
        return await show(tg, callback, uid, "📘 Yangi kurs nomini yozing.", kb_of([back("ca:cl:0", "✖️ Bekor qilish")]))
    if act == "set":
        return await settings_screen(tg, callback, uid, session, bot)
    if act == "qt":
        st = await core().get_settings(session, bot.id)
        st.questions_enabled = not st.questions_enabled
        await session.commit()
        return await settings_screen(tg, callback, uid, session, bot)
    if act == "stats":
        return await stats_screen(tg, callback, uid, session, bot)
    if act == "pays":
        return await payments_list(tg, callback, uid, session, bot)
    if act in ("pok", "prj", "pv"):
        return await payment_action(tg, callback, uid, session, bot, us, act, n0)
    if act == "qs":
        return await questions_list(tg, callback, uid, session, bot)
    if act in ("qo", "qa"):
        return await question_action(tg, callback, uid, session, bot, us, act, n0)
    if act == "ef":
        return await edit_field(tg, callback, uid, session, bot, us, arg)
    if not num:
        return

    course_acts = {"c", "acc", "um", "pub", "del", "delok", "m", "mn", "st", "sa", "sr", "srok"}
    if act in course_acts:
        if act in ("sr", "srok"):
            en = await session.get(Enrollment, n0)
            course = await own_course(session, bot, en.course_id) if en else None
        else:
            en, course = None, await own_course(session, bot, n0)
        if course is None:
            return await courses_list(tg, callback, uid, session, bot, 0)
        return await course_action(tg, callback, uid, session, bot, us, act, course, arg, en)
    if act in ("mo", "mup", "mdn", "mdel", "mdelok", "ln"):
        module, course = await own_module(session, bot, n0)
        if module is None:
            return await courses_list(tg, callback, uid, session, bot, 0)
        return await module_action(tg, callback, uid, session, bot, us, act, module, course)
    if act in ("lo", "lv", "lf", "lfc", "lpv", "lup", "ldn", "ldel", "ldelok"):
        lesson, course = await own_lesson(session, bot, n0)
        if lesson is None:
            return await courses_list(tg, callback, uid, session, bot, 0)
        return await lesson_action(tg, callback, uid, session, bot, us, act, lesson, course)


async def course_action(tg, callback, uid, session, bot, us, act, course, arg, en):
    if act == "c":
        return await course_card(tg, callback, uid, session, bot, course)
    if act == "acc":
        mode = arg[1] if len(arg) > 1 else ""
        if mode not in ACCESS_NAMES:
            return
        course.access = mode
        await session.commit()
        if mode == ACCESS_CODE and not course.access_code:
            return await ask(tg, callback, uid, session, us, "course", course.id, "code")
        if mode == ACCESS_PAID and course.price <= 0:
            return await ask(tg, callback, uid, session, us, "course", course.id, "price")
        return await course_card(tg, callback, uid, session, bot, course)
    if act == "um":
        mode = arg[1] if len(arg) > 1 else ""
        if mode not in UNLOCK_NAMES:
            return
        course.unlock_mode = mode
        await session.commit()
        return await course_card(tg, callback, uid, session, bot, course)
    if act == "pub":
        if not course.is_published:
            count = (await session.execute(select(func.count(Lesson.id)).where(Lesson.course_id == course.id))).scalar() or 0
            if not count:
                await tg.send_message(chat_id=uid, text="⚠️ Avval kamida bitta dars qo‘shing.")
                return await course_card(tg, callback, uid, session, bot, course)
            st = await core().get_settings(session, bot.id)
            if course.access == ACCESS_PAID and (course.price <= 0 or not st.card_number):
                await tg.send_message(chat_id=uid, text="⚠️ Pullik kurs uchun narx va karta raqami (⚙️ Sozlamalar) kerak.")
                return await course_card(tg, callback, uid, session, bot, course)
            if course.access == ACCESS_CODE and not course.access_code:
                await tg.send_message(chat_id=uid, text="⚠️ Avval kirish kodini belgilang.")
                return await course_card(tg, callback, uid, session, bot, course)
        course.is_published = not course.is_published
        await session.commit()
        return await course_card(tg, callback, uid, session, bot, course)
    if act == "del":
        return await confirm(tg, callback, uid, f"🗑 «{esc(course.title)}» kursi, uning darslari va o‘quvchilar yozuvlari o‘chiriladi. Davom etasizmi?",
                             f"ca:delok:{course.id}", f"ca:c:{course.id}")
    if act == "delok":
        await delete_course(session, course)
        return await courses_list(tg, callback, uid, session, bot, 0)
    if act == "m":
        return await modules_screen(tg, callback, uid, session, course)
    if act == "mn":
        await set_state(session, us, "ca_mn", {"course": course.id})
        return await show(tg, callback, uid, "📂 Modul nomini yozing (masalan «1-hafta»).", kb_of([back(f"ca:m:{course.id}", "✖️ Bekor qilish")]))
    if act == "st":
        return await students_screen(tg, callback, uid, session, course, int(arg[1]) if len(arg) > 1 and arg[1].isdigit() else 0)
    if act == "sa":
        await set_state(session, us, "ca_addst", {"course": course.id})
        return await show(tg, callback, uid, "👤 O‘quvchining Telegram ID raqamini yozing.", kb_of([back(f"ca:st:{course.id}:0", "✖️ Bekor qilish")]))
    if act == "sr":
        return await confirm(tg, callback, uid, f"🚫 {esc(en.user_name)} kursdan chiqarilsinmi? (Progress ham o‘chadi)", f"ca:srok:{en.id}", f"ca:st:{course.id}:0")
    if act == "srok":
        await session.execute(delete(LessonProgress).where(LessonProgress.course_id == course.id, LessonProgress.tg_user_id == en.tg_user_id))
        await session.delete(en)
        await session.commit()
        return await students_screen(tg, callback, uid, session, course, 0)


async def delete_course(session, course):
    for model in (CourseQuestion, CoursePayment, LessonProgress, Enrollment):
        await session.execute(delete(model).where(model.course_id == course.id))
    lesson_ids = select(Lesson.id).where(Lesson.course_id == course.id)
    await session.execute(delete(LessonFile).where(LessonFile.lesson_id.in_(lesson_ids)))
    await session.execute(delete(Lesson).where(Lesson.course_id == course.id))
    await session.execute(delete(CourseModule).where(CourseModule.course_id == course.id))
    await session.delete(course)
    await session.commit()


async def delete_lessons(session, lesson_ids):
    if not lesson_ids:
        return
    for model in (LessonFile, LessonProgress):
        await session.execute(delete(model).where(model.lesson_id.in_(lesson_ids)))
    await session.execute(delete(CourseQuestion).where(CourseQuestion.lesson_id.in_(lesson_ids)))
    await session.execute(delete(Lesson).where(Lesson.id.in_(lesson_ids)))
    await session.commit()


async def module_action(tg, callback, uid, session, bot, us, act, module, course):
    if act == "mo":
        return await module_screen(tg, callback, uid, session, module, course)
    if act in ("mup", "mdn"):
        await move(session, await core().modules_of(session, course.id), module.id, -1 if act == "mup" else 1)
        return await modules_screen(tg, callback, uid, session, course)
    if act == "mdel":
        return await confirm(tg, callback, uid, f"🗑 «{esc(module.title)}» moduli va undagi darslar o‘chiriladi. Davom etasizmi?",
                             f"ca:mdelok:{module.id}", f"ca:mo:{module.id}")
    if act == "mdelok":
        ids = list((await session.execute(select(Lesson.id).where(Lesson.module_id == module.id))).scalars().all())
        await delete_lessons(session, ids)
        await session.delete(module)
        await session.commit()
        return await modules_screen(tg, callback, uid, session, course)
    if act == "ln":
        await set_state(session, us, "ca_ln", {"module": module.id})
        return await show(tg, callback, uid, "📘 Yangi dars nomini yozing.", kb_of([back(f"ca:mo:{module.id}", "✖️ Bekor qilish")]))


async def lesson_action(tg, callback, uid, session, bot, us, act, lesson, course):
    if act == "lo":
        return await lesson_screen(tg, callback, uid, session, lesson, course)
    if act == "lv":
        await core().open_lesson(tg, None, uid, session, bot, lesson, True)
        return
    if act == "lf":
        await set_state(session, us, "ca_files", {"lesson": lesson.id, "added": 0})
        return await show(tg, callback, uid, "📎 Fayllarni yuboring (video, audio, PDF/hujjat, rasm) — bir nechta bo‘lishi mumkin.\nTugagach /done yozing.",
                          kb_of([back(f"ca:lo:{lesson.id}", "✖️ Bekor qilish")]))
    if act == "lfc":
        await session.execute(delete(LessonFile).where(LessonFile.lesson_id == lesson.id))
        await session.commit()
        return await lesson_screen(tg, callback, uid, session, lesson, course)
    if act == "lpv":
        lesson.is_preview = not lesson.is_preview
        await session.commit()
        return await lesson_screen(tg, callback, uid, session, lesson, course)
    if act in ("lup", "ldn"):
        items = list((await session.execute(select(Lesson).where(Lesson.module_id == lesson.module_id).order_by(Lesson.position, Lesson.id))).scalars().all())
        await move(session, items, lesson.id, -1 if act == "lup" else 1)
        module = await session.get(CourseModule, lesson.module_id)
        return await module_screen(tg, callback, uid, session, module, course)
    if act == "ldel":
        return await confirm(tg, callback, uid, f"🗑 «{esc(lesson.title)}» darsi o‘chirilsinmi?", f"ca:ldelok:{lesson.id}", f"ca:lo:{lesson.id}")
    if act == "ldelok":
        module = await session.get(CourseModule, lesson.module_id)
        await delete_lessons(session, [lesson.id])
        return await module_screen(tg, callback, uid, session, module, course)


# ------------------------------------------------------------------ editing fields

async def ask(tg, callback, uid, session, us, entity, ent_id, field):
    label, kind, limit = FIELDS[(entity, field)]
    await set_state(session, us, "ca_ef", {"entity": entity, "id": ent_id, "field": field})
    hint = {"photo": "Rasm yuboring.", "int": "Raqam yuboring.", "hour": "0 dan 23 gacha raqam yuboring."}.get(kind, f"Matn yuboring (≤ {limit} belgi)." if limit else "")
    extra = "\nTozalash: /clear" if field in ("description", "text", "cover", "note", "holder") else ""
    await show(tg, callback, uid, f"✏️ <b>{esc(label)}</b>\n{hint}{extra}\nBekor qilish: /cancel", None)


async def edit_field(tg, callback, uid, session, bot, us, arg):
    if len(arg) < 3 or (arg[0], arg[2]) not in FIELDS or not arg[1].isdigit():
        return
    entity, ent_id, field = arg[0], int(arg[1]), arg[2]
    if entity == "course" and not await own_course(session, bot, ent_id):
        return
    if entity == "module" and (await own_module(session, bot, ent_id))[0] is None:
        return
    if entity == "lesson" and (await own_lesson(session, bot, ent_id))[0] is None:
        return
    await ask(tg, callback, uid, session, us, entity, ent_id, field)


async def after_edit(tg, uid, session, bot, entity, ent_id):
    if entity == "course":
        return await course_card(tg, None, uid, session, bot, await session.get(Course, ent_id))
    if entity == "module":
        module, course = await own_module(session, bot, ent_id)
        return await module_screen(tg, None, uid, session, module, course)
    if entity == "lesson":
        lesson, course = await own_lesson(session, bot, ent_id)
        return await lesson_screen(tg, None, uid, session, lesson, course)
    return await settings_screen(tg, None, uid, session, bot)


def parse_value(kind, limit, text, message):
    """-> (value, error). ``None`` value with no error means "clear"."""
    if kind == "photo":
        if message.get("photo"):
            return message["photo"][-1]["file_id"], None
        return None, "🖼 Rasm yuboring."
    if not text:
        return None, "Matn yuboring."
    if kind == "int":
        digits = "".join(ch for ch in text if ch not in " ,._")
        if not digits.isdigit() or not 1 <= int(digits) <= limit:
            return None, f"Raqam 1 dan {limit} gacha bo‘lsin."
        return int(digits), None
    if kind == "hour":
        if not text.isdigit() or not 0 <= int(text) <= 23:
            return None, "0 dan 23 gacha raqam yuboring."
        return int(text), None
    if kind == "tz":
        if not valid_tz(text):
            return None, "Noto‘g‘ri mintaqa. Masalan: Asia/Tashkent"
        return text, None
    if kind == "card":
        digits = "".join(ch for ch in text if ch.isdigit())
        if not 8 <= len(digits) <= 20:
            return None, "Karta raqamini to‘g‘ri yuboring (16 xonali)."
        return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4)), None
    if kind == "code":
        code = text.strip()
        if not code or len(code) > limit or " " in code:
            return None, f"Kod bo‘shliqsiz, {limit} belgigacha bo‘lsin."
        return code, None
    if len(text) > limit:
        return None, f"Juda uzun (≤ {limit} belgi)."
    return text, None


async def apply_field(session, bot, entity, ent_id, field, value):
    st = None
    if entity == "course":
        obj = await session.get(Course, ent_id)
        attr = {"title": "title", "description": "description", "cover": "cover_file_id", "code": "access_code", "price": "price", "days": "drip_days"}[field]
    elif entity == "module":
        obj, attr = await session.get(CourseModule, ent_id), "title"
    elif entity == "lesson":
        obj, attr = await session.get(Lesson, ent_id), field
    else:
        obj = st = await core().get_settings(session, bot.id)
        attr = {"card": "card_number", "holder": "card_holder", "note": "pay_note", "tz": "timezone", "hour": "drip_hour"}[field]
    if value is None and attr in ("title", "price", "drip_days", "timezone", "drip_hour", "card_number"):
        return False
    setattr(obj, attr, value)
    await session.commit()
    return True


async def clash_code(session, bot, course_id, code):
    other = (await session.execute(select(Course).where(
        Course.bot_id == bot.id, Course.id != course_id, func.lower(Course.access_code) == code.lower()))).scalars().first()
    return other


# ------------------------------------------------------------------ messages

async def on_message(bot, message, session, tg, us) -> bool:
    uid = message["from"]["id"]
    text = (message.get("text") or "").strip()
    state, data = us.state, us.state_data or {}

    if state == "ca_new":
        if not text or len(text) > 120:
            await tg.send_message(chat_id=uid, text="Nom 1–120 belgi bo‘lsin.")
            return True
        pos = (await session.execute(select(func.count(Course.id)).where(Course.bot_id == bot.id))).scalar() or 0
        course = Course(bot_id=bot.id, title=text, position=pos)
        session.add(course)
        await session.commit()
        await set_state(session, us)
        await tg.send_message(chat_id=uid, text="✅ Kurs yaratildi. Endi tavsif, modul va darslar qo‘shing.")
        await course_card(tg, None, uid, session, bot, course)
        return True

    if state == "ca_mn":
        course = await own_course(session, bot, data.get("course"))
        if course is None or not text or len(text) > 120:
            await tg.send_message(chat_id=uid, text="Modul nomi 1–120 belgi bo‘lsin.")
            return True
        count = (await session.execute(select(func.count(CourseModule.id)).where(CourseModule.course_id == course.id))).scalar() or 0
        module = CourseModule(course_id=course.id, title=text, position=count)
        session.add(module)
        await session.commit()
        await set_state(session, us)
        await module_screen(tg, None, uid, session, module, course)
        return True

    if state == "ca_ln":
        module, course = await own_module(session, bot, data.get("module"))
        if module is None or not text or len(text) > 120:
            await tg.send_message(chat_id=uid, text="Dars nomi 1–120 belgi bo‘lsin.")
            return True
        count = (await session.execute(select(func.count(Lesson.id)).where(Lesson.module_id == module.id))).scalar() or 0
        lesson = Lesson(course_id=course.id, module_id=module.id, title=text, position=count)
        session.add(lesson)
        await session.commit()
        await set_state(session, us, "ca_ltext", {"lesson": lesson.id})
        await tg.send_message(chat_id=uid, text="📝 Dars matnini yuboring (≤ 3500 belgi). O‘tkazib yuborish: /skip")
        return True

    if state == "ca_ltext":
        lesson, course = await own_lesson(session, bot, data.get("lesson"))
        if lesson is None:
            await set_state(session, us)
            return True
        if text != "/skip":
            if not text or len(text) > 3500:
                await tg.send_message(chat_id=uid, text="Matn 1–3500 belgi bo‘lsin yoki /skip.")
                return True
            lesson.text = text
            await session.commit()
        await set_state(session, us, "ca_files", {"lesson": lesson.id, "added": 0})
        await tg.send_message(chat_id=uid, text="📎 Endi fayllarni yuboring (video, audio, PDF/hujjat, rasm) — bir nechta bo‘lishi mumkin.\nTugagach /done yozing.")
        return True

    if state == "ca_files":
        lesson, course = await own_lesson(session, bot, data.get("lesson"))
        if lesson is None:
            await set_state(session, us)
            return True
        if text == "/done":
            await set_state(session, us)
            await lesson_screen(tg, None, uid, session, lesson, course)
            return True
        found = media_of(message)
        if not found:
            await tg.send_message(chat_id=uid, text="📎 Fayl yuboring (video, audio, hujjat yoki rasm). Tugatish: /done")
            return True
        count = (await session.execute(select(func.count(LessonFile.id)).where(LessonFile.lesson_id == lesson.id))).scalar() or 0
        session.add(LessonFile(lesson_id=lesson.id, position=count, file_type=found[0], file_id=found[1], file_name=(found[2] or None)))
        await session.commit()
        data["added"] = int(data.get("added", 0)) + 1
        await set_state(session, us, "ca_files", dict(data))
        await tg.send_message(chat_id=uid, text=f"✅ {data['added']}-fayl qo‘shildi. Yana yuboring yoki /done.")
        return True

    if state == "ca_ef":
        entity, ent_id, field = data.get("entity"), data.get("id"), data.get("field")
        if (entity, field) not in FIELDS:
            await set_state(session, us)
            return True
        label, kind, limit = FIELDS[(entity, field)]
        if text == "/clear":
            value, err = None, None
        else:
            value, err = parse_value(kind, limit, text, message)
        if err:
            await tg.send_message(chat_id=uid, text=f"❌ {err}")
            return True
        if field == "code" and value:
            other = await clash_code(session, bot, ent_id, value)
            if other:
                await tg.send_message(chat_id=uid, parse_mode="HTML", text=f"❌ Bu kod «{esc(other.title)}» kursida ishlatilgan. Boshqa kod yuboring.")
                return True
        if not await apply_field(session, bot, entity, ent_id, field, value):
            await tg.send_message(chat_id=uid, text="❌ Bu maydonni bo‘sh qoldirib bo‘lmaydi.")
            return True
        await set_state(session, us)
        await after_edit(tg, uid, session, bot, entity, ent_id)
        return True

    if state == "ca_addst":
        course = await own_course(session, bot, data.get("course"))
        digits = text.lstrip("-")
        if course is None or not digits.isdigit() or int(text) <= 0:
            await tg.send_message(chat_id=uid, text="Telegram ID raqamini yuboring (masalan 123456789).")
            return True
        await set_state(session, us)
        target = int(text)
        c = core()
        if await c.enrollment_of(session, course.id, target) is None:
            await c.enroll(session, bot, course, {"id": target, "first_name": f"ID {target}"}, VIA_ADMIN)
            try:
                await c.welcome_enrolled(tg, bot, course, target)
            except TelegramError as exc:
                logger.info("admin-added student %s not notified: %s", target, exc)
        await students_screen(tg, None, uid, session, course, 0)
        return True

    if state == "ca_reject":
        pay = await session.get(CoursePayment, data.get("pay"))
        await set_state(session, us)
        if pay is None or pay.bot_id != bot.id or pay.status != PAY_PENDING:
            await tg.send_message(chat_id=uid, text="Bu to‘lov allaqachon ko‘rib chiqilgan.")
            return True
        await decide_payment(tg, session, bot, pay, uid, approve=False, reason=None if text in ("/skip", "") else text[:500])
        return True

    if state == "ca_answer":
        q = await session.get(CourseQuestion, data.get("q"))
        await set_state(session, us)
        if q is None or q.bot_id != bot.id:
            return True
        if not text or text.startswith("/"):
            await tg.send_message(chat_id=uid, text="Javob matnini yuboring.")
            await set_state(session, us, "ca_answer", data)
            return True
        q.answer, q.answered_by = text[:3500], uid
        await session.commit()
        lesson = await session.get(Lesson, q.lesson_id) if q.lesson_id else None
        try:
            await tg.send_message(chat_id=q.tg_user_id, parse_mode="HTML",
                                  text=f"💬 <b>Savolingizga javob</b>\n\n❓ {esc(q.text)}\n\n✅ {esc(q.answer)}",
                                  reply_markup=kb_of([[Btn("📘 Darsga qaytish", callback_data=f"cr:l:{lesson.id}")]]) if lesson else None)
            note = "✅ Javob yuborildi."
        except TelegramError:
            note = "✅ Javob saqlandi, lekin foydalanuvchiga yetkazib bo‘lmadi."
        await tg.send_message(chat_id=uid, text=note, reply_markup=kb_of([[Btn("❓ Savollar", callback_data="ca:qs:0")]]))
        return True
    return False


# ------------------------------------------------------------------ students, payments, questions, stats

async def students_screen(tg, callback, uid, session, course, page):
    total = (await session.execute(select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id))).scalar() or 0
    pages = max(1, (total + 9) // 10)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(Enrollment).where(Enrollment.course_id == course.id)
                                  .order_by(Enrollment.enrolled_at.desc(), Enrollment.id.desc()).limit(10).offset(page * 10))).scalars().all()
    lessons = (await session.execute(select(func.count(Lesson.id)).where(Lesson.course_id == course.id))).scalar() or 0
    from engine import course_logic as logic
    lines, kb = [f"👥 <b>{esc(course.title)}</b> — o‘quvchilar ({total})\n"], []
    for en in rows:
        done = (await session.execute(select(func.count(LessonProgress.id)).where(
            LessonProgress.course_id == course.id, LessonProgress.tg_user_id == en.tg_user_id))).scalar() or 0
        lines.append(f"{'🎓' if en.completed_at else '•'} {esc(en.user_name)} — {logic.percent(done, lessons)}% · {en.via}")
        kb.append([Btn(f"🚫 {en.user_name}"[:60], callback_data=f"ca:sr:{en.id}")])
    nav = ([Btn("⬅️", callback_data=f"ca:st:{course.id}:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"ca:st:{course.id}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append([Btn("➕ Qo‘lda qo‘shish", callback_data=f"ca:sa:{course.id}")])
    kb.append(back(f"ca:c:{course.id}", "⬅️ Kurs"))
    await show(tg, callback, uid, "\n".join(lines), kb_of(kb))


async def payments_list(tg, callback, uid, session, bot):
    rows = (await session.execute(select(CoursePayment, Course).join(Course, Course.id == CoursePayment.course_id).where(
        CoursePayment.bot_id == bot.id, CoursePayment.status == PAY_PENDING).order_by(CoursePayment.id).limit(20))).all()
    kb = [[Btn(f"#{p.id} {p.user_name} · {c.title}"[:60], callback_data=f"ca:pv:{p.id}")] for p, c in rows]
    kb.append(back("ca:home"))
    await show(tg, callback, uid, "💳 <b>Kutilayotgan to‘lovlar</b>" if rows else "Kutilayotgan to‘lov yo‘q. ✅", kb_of(kb))


async def payment_action(tg, callback, uid, session, bot, us, act, pay_id):
    pay = await session.get(CoursePayment, pay_id)
    if pay is None or pay.bot_id != bot.id:
        return await payments_list(tg, callback, uid, session, bot)
    if act == "pv":
        course = await session.get(Course, pay.course_id)
        await notify_one(tg, uid, course, pay)
        return
    if pay.status != PAY_PENDING:
        return await tg.send_message(chat_id=uid, text=f"ℹ️ To‘lov #{pay.id} allaqachon ko‘rib chiqilgan ({pay.status}).")
    if act == "pok":
        return await decide_payment(tg, session, bot, pay, uid, approve=True)
    await set_state(session, us, "ca_reject", {"pay": pay.id})
    await tg.send_message(chat_id=uid, text=f"❌ To‘lov #{pay.id} rad etiladi. Sababini yozing (o‘quvchiga yuboriladi) yoki /skip.")


async def notify_one(tg, uid, course, pay):
    caption = (f"💳 <b>To‘lov #{pay.id}</b>\n📘 {esc(course.title if course else '')} — {core().fmt_price(pay.amount)}\n"
               f"👤 {esc(pay.user_name)}  <code>{pay.tg_user_id}</code>")
    markup = kb_of([[Btn("✅ Tasdiqlash", callback_data=f"ca:pok:{pay.id}"), Btn("❌ Rad etish", callback_data=f"ca:prj:{pay.id}")]])
    if pay.receipt_type == "photo":
        await tg.send_photo(chat_id=uid, photo=pay.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=markup)
    else:
        await tg.send_document(chat_id=uid, document=pay.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=markup)


async def decide_payment(tg, session, bot, pay, admin_id, *, approve, reason=None):
    c = core()
    course = await session.get(Course, pay.course_id)
    pay.status = PAY_APPROVED if approve else PAY_REJECTED
    pay.decided_by, pay.decided_at, pay.reason = admin_id, utcnow(), reason
    await session.commit()
    if approve and course:
        await c.enroll(session, bot, course, {"id": pay.tg_user_id, "first_name": pay.user_name}, VIA_PAID)
    try:
        if approve:
            await tg.send_message(chat_id=pay.tg_user_id, parse_mode="HTML",
                                  text=f"✅ To‘lovingiz tasdiqlandi! <b>{esc(course.title if course else '')}</b> kursi ochildi.",
                                  reply_markup=kb_of([[Btn("▶️ Boshlash", callback_data=f"cr:go:{pay.course_id}")]]))
        else:
            why = f"\nSabab: {esc(reason)}" if reason else ""
            await tg.send_message(chat_id=pay.tg_user_id, parse_mode="HTML",
                                  text=f"❌ To‘lovingiz tasdiqlanmadi.{why}\nTo‘g‘ri chek bilan qayta urinib ko‘rishingiz mumkin.",
                                  reply_markup=kb_of([[Btn("📘 Kurs", callback_data=f"cr:c:{pay.course_id}")]]))
    except TelegramError as exc:
        logger.info("payment %s result not delivered: %s", pay.id, exc)
    await tg.send_message(chat_id=admin_id, text=f"{'✅ Tasdiqlandi' if approve else '❌ Rad etildi'}: to‘lov #{pay.id} ({pay.user_name}).",
                          reply_markup=kb_of([[Btn("💳 Boshqa to‘lovlar", callback_data="ca:pays:0")]]))


async def questions_list(tg, callback, uid, session, bot):
    rows = (await session.execute(select(CourseQuestion).where(CourseQuestion.bot_id == bot.id, CourseQuestion.answer.is_(None))
                                  .order_by(CourseQuestion.id).limit(20))).scalars().all()
    kb = [[Btn(f"#{q.id} {q.user_name}: {q.text}"[:60], callback_data=f"ca:qo:{q.id}")] for q in rows]
    kb.append(back("ca:home"))
    await show(tg, callback, uid, "❓ <b>Javobsiz savollar</b>" if rows else "Javobsiz savol yo‘q. ✅", kb_of(kb))


async def question_action(tg, callback, uid, session, bot, us, act, q_id):
    q = await session.get(CourseQuestion, q_id)
    if q is None or q.bot_id != bot.id:
        return await questions_list(tg, callback, uid, session, bot)
    if q.answer:
        return await tg.send_message(chat_id=uid, parse_mode="HTML", text=f"ℹ️ Savol #{q.id} javob berilgan:\n\n{esc(q.answer)}")
    await set_state(session, us, "ca_answer", {"q": q.id})
    await tg.send_message(chat_id=uid, parse_mode="HTML", text=f"💬 <b>Savol #{q.id}</b> — {esc(q.user_name)}\n\n{esc(q.text)}\n\nJavobingizni yozing. Bekor qilish: /cancel")


async def stats_screen(tg, callback, uid, session, bot):
    async def count(model, *conds):
        return (await session.execute(select(func.count(model.id)).where(*conds))).scalar() or 0
    courses = (await session.execute(select(Course).where(Course.bot_id == bot.id).order_by(Course.position, Course.id))).scalars().all()
    lines = ["📊 <b>Statistika</b>\n",
             f"📚 Kurslar: {len(courses)}",
             f"👥 Yozilishlar: {await count(Enrollment, Enrollment.bot_id == bot.id)}",
             f"🎓 Tugatganlar: {await count(Enrollment, Enrollment.bot_id == bot.id, Enrollment.completed_at.is_not(None))}",
             f"💳 Kutilayotgan to‘lovlar: {await count(CoursePayment, CoursePayment.bot_id == bot.id, CoursePayment.status == PAY_PENDING)}"]
    total_rev = (await session.execute(select(func.coalesce(func.sum(CoursePayment.amount), 0)).where(
        CoursePayment.bot_id == bot.id, CoursePayment.status == PAY_APPROVED))).scalar() or 0
    lines.append(f"💰 Tasdiqlangan tushum: {core().fmt_price(total_rev)}\n")
    for c in courses[:15]:
        e = await count(Enrollment, Enrollment.course_id == c.id)
        d = await count(Enrollment, Enrollment.course_id == c.id, Enrollment.completed_at.is_not(None))
        rev = (await session.execute(select(func.coalesce(func.sum(CoursePayment.amount), 0)).where(
            CoursePayment.course_id == c.id, CoursePayment.status == PAY_APPROVED))).scalar() or 0
        lines.append(f"• <b>{esc(c.title)}</b>: {e} yozilgan, {d} tugatgan" + (f", {core().fmt_price(rev)}" if rev else ""))
    await show(tg, callback, uid, "\n".join(lines), kb_of([back("ca:home")]))
