"""Course bots: a catalog of courses (module -> lesson), free / code-protected / paid by card receipt,
lessons that open all at once, one after another or on a schedule, progress and a completion certificate.

Lesson media is stored by ``file_id`` (uploaded by admins through this very bot) and always sent with
``protect_content`` to students. Admin side lives in ``engine/course_admin.py`` (``ca:`` callbacks,
``ca_*`` states); student side uses ``cr:`` callbacks and ``cr_*`` states.
"""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import Forbidden, TelegramError

from core.logger import get_logger
from engine import cinema, course_admin, course_logic as logic, subscription
from engine.audience import touch_user
from engine.booking_time import fmt_dt, tz_of, utcnow
from models.course import (
    ACCESS_CODE, ACCESS_FREE, ACCESS_PAID, PAY_PENDING, UNLOCK_DRIP, UNLOCK_SEQ, VIA_CODE, VIA_FREE,
    Course, CourseModule, CoursePayment, CourseQuestion, CourseSettings, Enrollment, Lesson, LessonFile, LessonProgress,
)
from models.user_sessions import UserSession

logger = get_logger("course")
esc = cinema.esc
show = cinema._show

WELCOME = ("🎓 <b>Kurs botiga xush kelibsiz!</b>\n\nVideo darslar, materiallar va natijalar — hammasi shu yerda. "
           "Kursni tanlang va o‘qishni boshlang.")
HELP = ("❓ <b>Yordam</b>\n\n📚 <b>Kurslar</b> — mavjud kurslar ro‘yxati.\n🎓 <b>Mening kurslarim</b> — yozilgan kurslaringiz va jarayon.\n\n"
        "Kurs bepul, kod bilan yoki to‘lov evaziga bo‘lishi mumkin. To‘lovda karta raqamiga o‘tkazib, chek rasmini yuborasiz — "
        "admin tasdiqlagach dars ochiladi.\nDarslarni yuborish/ko‘chirish cheklangan.")
PAGE = 8
MAX_CODE_TRIES = 5
MEDIA_SENDERS = {"video": ("send_video", "video"), "audio": ("send_audio", "audio"),
                 "document": ("send_document", "document"), "photo": ("send_photo", "photo")}


# ------------------------------------------------------------------ basics

async def get_settings(session, bot_id: int) -> CourseSettings:
    st = (await session.execute(select(CourseSettings).where(CourseSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = CourseSettings(bot_id=bot_id)
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> CourseSettings:
    st = await get_settings(session, bot.id)
    await cinema.ensure_start_menu(session, bot, WELCOME)
    return st


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


def display_name(user: dict) -> str:
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return (name or user.get("username") or "Foydalanuvchi")[:120]


def fmt_price(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so‘m"


def deep_link(bot, course) -> str:
    return f"https://t.me/{bot.username}?start=c{course.id}" if bot.username else ""


async def lessons_of(session, course_id: int) -> list:
    """Lessons in creation order: modules by id, then lessons by id inside each module."""
    rows = (await session.execute(
        select(Lesson).join(CourseModule, CourseModule.id == Lesson.module_id)
        .where(Lesson.course_id == course_id)
        .order_by(CourseModule.id, Lesson.id)  # creation order: first created is first
    )).scalars().all()
    return list(rows)


async def modules_of(session, course_id: int) -> list:
    return list((await session.execute(
        select(CourseModule).where(CourseModule.course_id == course_id).order_by(CourseModule.id)
    )).scalars().all())


async def files_of(session, lesson_id: int) -> list:
    return list((await session.execute(
        select(LessonFile).where(LessonFile.lesson_id == lesson_id).order_by(LessonFile.id)
    )).scalars().all())


async def enrollment_of(session, course_id: int, uid: int):
    return (await session.execute(
        select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.tg_user_id == uid)
    )).scalar_one_or_none()


async def done_ids(session, course_id: int, uid: int) -> set:
    return set((await session.execute(
        select(LessonProgress.lesson_id).where(LessonProgress.course_id == course_id, LessonProgress.tg_user_id == uid)
    )).scalars().all())


async def enroll(session, bot, course, user: dict, via: str) -> Enrollment:
    """Idempotent: a second call returns the existing enrollment."""
    uid = user["id"]
    en = await enrollment_of(session, course.id, uid)
    if en is None:
        en = Enrollment(bot_id=bot.id, course_id=course.id, tg_user_id=uid, user_name=display_name(user), via=via)
        session.add(en)
        await session.commit()
    return en


class Ctx:
    """Everything needed to decide what a student may open in one course."""

    def __init__(self, course, lessons, done, enrollment, opened, tz, settings, admin):
        self.course, self.lessons, self.done, self.enrollment = course, lessons, done, enrollment
        self.opened, self.tz, self.settings, self.admin = opened, tz, settings, admin

    @property
    def total(self):
        return len(self.lessons)

    @property
    def done_count(self):
        return sum(1 for ls in self.lessons if ls.id in self.done)

    def index(self, lesson_id):
        return next((i for i, ls in enumerate(self.lessons) if ls.id == lesson_id), -1)

    def can_open(self, lesson) -> bool:
        if self.admin or lesson.is_preview:
            return True
        i = self.index(lesson.id)
        return self.enrollment is not None and 0 <= i < self.opened

    def next_open(self):
        if self.enrollment is None:
            return None
        return logic.next_open_at(self.course.unlock_mode, self.opened, self.total, enrolled_at=self.enrollment.enrolled_at,
                                  drip_days=self.course.drip_days, drip_hour=self.settings.drip_hour, tz=self.tz)


async def context(session, bot, course, uid: int, admin: bool = False, now=None) -> Ctx:
    settings = await get_settings(session, bot.id)
    lessons = await lessons_of(session, course.id)
    done = await done_ids(session, course.id, uid)
    en = await enrollment_of(session, course.id, uid)
    tz = tz_of(settings.timezone)
    opened = 0
    if en is not None:
        opened = logic.unlocked_count(
            course.unlock_mode, [ls.id in done for ls in lessons], enrolled_at=en.enrolled_at, now=now or utcnow(),
            drip_days=course.drip_days, drip_hour=settings.drip_hour, tz=tz)
    return Ctx(course, lessons, done, en, opened, tz, settings, admin)


async def visible_course(session, bot, course_id: int, uid: int, admin: bool):
    course = await session.get(Course, course_id)
    if course is None or course.bot_id != bot.id:
        return None
    if course.is_published or admin or await enrollment_of(session, course.id, uid):
        return course
    return None


# ------------------------------------------------------------------ home, catalog

async def home_markup(session, bot, uid: int) -> Markup:
    rows = [[Btn("📚 Kurslar", callback_data="cr:cat:0"), Btn("🎓 Mening kurslarim", callback_data="cr:my")],
            [Btn("🔑 Kod kiritish", callback_data="cr:codeany"), Btn("❓ Yordam", callback_data="cr:help")]]
    if await cinema.is_admin(session, bot, uid):
        rows.append([Btn("🛠 Admin panel", callback_data="ca:home")])
    return Markup(rows)


async def show_home(tg, callback, chat_id, session, bot):
    menu = await cinema.ensure_start_menu(session, bot, WELCOME)
    await show(tg, callback, chat_id, menu.message_text or WELCOME, await home_markup(session, bot, chat_id))


def access_label(course) -> str:
    if course.access == ACCESS_PAID:
        return f"💰 {fmt_price(course.price)}"
    return "🔑 Kod bilan" if course.access == ACCESS_CODE else "🆓 Bepul"


async def show_catalog(tg, callback, chat_id, session, bot, page: int, admin: bool):
    conds = [Course.bot_id == bot.id]
    if not admin:
        conds.append(Course.is_published.is_(True))
    total = (await session.execute(select(func.count(Course.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(Course).where(*conds).order_by(Course.id)
                                  .limit(PAGE).offset(page * PAGE))).scalars().all()
    if not rows:
        return await show(tg, callback, chat_id, "Hozircha kurslar yo‘q. Tez orada qo‘shiladi!",
                          Markup([[Btn("🏠 Bosh sahifa", callback_data="cr:home")]]))
    kb = [[Btn(f"{'' if c.is_published else '🚧 '}{c.title} · {access_label(c)}"[:60], callback_data=f"cr:c:{c.id}")] for c in rows]
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"cr:cat:{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"cr:cat:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([Btn("🏠 Bosh sahifa", callback_data="cr:home")])
    await show(tg, callback, chat_id, f"📚 <b>Kurslar</b> ({total})", Markup(kb))


async def show_my(tg, callback, chat_id, session, bot):
    ens = (await session.execute(
        select(Enrollment, Course).join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.bot_id == bot.id, Enrollment.tg_user_id == chat_id).order_by(Enrollment.enrolled_at.desc()).limit(30)
    )).all()
    if not ens:
        return await show(tg, callback, chat_id, "Siz hali birorta kursga yozilmagansiz.",
                          Markup([[Btn("📚 Kurslar", callback_data="cr:cat:0")], [Btn("🏠 Bosh sahifa", callback_data="cr:home")]]))
    kb = []
    for en, course in ens:
        total = (await session.execute(select(func.count(Lesson.id)).where(Lesson.course_id == course.id))).scalar() or 0
        done = len(await done_ids(session, course.id, chat_id))
        mark = "🎓" if en.completed_at else f"{logic.percent(done, total)}%"
        kb.append([Btn(f"{course.title} · {mark}"[:60], callback_data=f"cr:c:{course.id}")])
    kb.append([Btn("🏠 Bosh sahifa", callback_data="cr:home")])
    await show(tg, callback, chat_id, "🎓 <b>Mening kurslarim</b>", Markup(kb))


# ------------------------------------------------------------------ course page

async def pending_payment(session, course_id: int, uid: int):
    return (await session.execute(select(CoursePayment).where(
        CoursePayment.course_id == course_id, CoursePayment.tg_user_id == uid, CoursePayment.status == PAY_PENDING))).scalars().first()


def unlock_note(course) -> str:
    if course.unlock_mode == UNLOCK_SEQ:
        return "🔓 Darslar ketma-ket ochiladi: avvalgisini tugatsangiz keyingisi ochiladi."
    if course.unlock_mode == UNLOCK_DRIP:
        every = "har kuni" if course.drip_days == 1 else f"har {course.drip_days} kunda"
        return f"📅 Yangi dars {every} ochiladi."
    return "🔓 Barcha darslar birdaniga ochiq."


async def show_course(tg, callback, chat_id, session, bot, course, admin: bool):
    ctx = await context(session, bot, course, chat_id, admin)
    modules = await modules_of(session, course.id)
    lines = [f"📘 <b>{esc(course.title)}</b>"]
    if course.description:
        lines.append(esc(course.description[:700]))
    lines.append(f"\n📦 {len(modules)} modul · {ctx.total} dars\n{access_label(course)}\n{unlock_note(course)}")
    kb = []
    if ctx.enrollment:
        pct = logic.percent(ctx.done_count, ctx.total)
        lines.append(f"\n📈 {logic.bar(pct)} {pct}% ({ctx.done_count}/{ctx.total})")
        if ctx.enrollment.completed_at:
            kb.append([Btn("🎓 Sertifikat", callback_data=f"cr:cert:{course.id}")])
        kb.append([Btn("▶️ Davom etish" if ctx.done_count else "▶️ Boshlash", callback_data=f"cr:go:{course.id}")])
    else:
        pend = await pending_payment(session, course.id, chat_id)
        if course.access == ACCESS_FREE:
            kb.append([Btn("🆓 Kursga yozilish", callback_data=f"cr:join:{course.id}")])
        elif course.access == ACCESS_CODE:
            kb.append([Btn("🔑 Kod kiritish", callback_data=f"cr:code:{course.id}")])
        elif pend:
            lines.append("\n⏳ To‘lovingiz tekshirilmoqda. Tasdiqlansa xabar beramiz.")
        else:
            kb.append([Btn(f"💳 To‘lov qilish ({fmt_price(course.price)})", callback_data=f"cr:pay:{course.id}")])
    kb.append([Btn("📖 Dastur", callback_data=f"cr:syl:{course.id}:0")])
    if admin:
        kb.append([Btn("🛠 Tahrirlash", callback_data=f"ca:c:{course.id}")])
    kb.append([Btn("⬅️ Kurslar", callback_data="cr:cat:0")])
    text, markup = "\n".join(lines), Markup(kb)
    if course.cover_file_id:
        try:
            await tg.send_photo(chat_id=chat_id, photo=course.cover_file_id, caption=text[:1024], parse_mode="HTML", reply_markup=markup)
            return
        except Forbidden:
            raise
        except TelegramError as exc:
            logger.info("cover not sent: %s", exc)
    await show(tg, callback, chat_id, text, markup)


async def show_syllabus(tg, callback, chat_id, session, bot, course, page: int, admin: bool):
    ctx = await context(session, bot, course, chat_id, admin)
    pages = max(1, (ctx.total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = ctx.lessons[page * PAGE:(page + 1) * PAGE]
    mods = {m.id: m.title for m in await modules_of(session, course.id)}
    lines, kb, last = [f"📖 <b>{esc(course.title)}</b> — dastur"], [], None
    if not chunk:
        lines.append("\nDarslar hali qo‘shilmagan.")
    for ls in chunk:
        if ls.module_id != last:
            last = ls.module_id
            lines.append(f"\n📂 <b>{esc(mods.get(ls.module_id, ''))}</b>")
        i = ctx.index(ls.id)
        if ls.id in ctx.done:
            icon = "✅"
        elif ctx.can_open(ls):
            icon = "▶️" if ctx.enrollment or ctx.admin else "👁"
        else:
            icon = "🔒"
        lines.append(f"{icon} {i + 1}. {esc(ls.title)}")
        kb.append([Btn(f"{icon} {i + 1}. {ls.title}"[:60], callback_data=f"cr:l:{ls.id}")])
    nxt = ctx.next_open()
    if nxt and ctx.enrollment:
        lines.append(f"\n⏰ Keyingi dars: {fmt_dt(nxt, ctx.tz)}")
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"cr:syl:{course.id}:{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"cr:syl:{course.id}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([Btn("⬅️ Kurs", callback_data=f"cr:c:{course.id}")])
    await show(tg, callback, chat_id, "\n".join(lines), Markup(kb))


# ------------------------------------------------------------------ joining

async def welcome_enrolled(tg, bot, course, uid):
    await tg.send_message(
        chat_id=uid, parse_mode="HTML",
        text=f"✅ Siz <b>{esc(course.title)}</b> kursiga yozildingiz!",
        reply_markup=Markup([[Btn("▶️ Boshlash", callback_data=f"cr:go:{course.id}")]]))


async def payment_info(tg, callback, chat_id, session, bot, course):
    st = await get_settings(session, bot.id)
    if not st.card_number:
        return await show(tg, callback, chat_id, "To‘lov ma’lumotlari hali kiritilmagan. Admin bilan bog‘laning.",
                          Markup([[Btn("⬅️ Kurs", callback_data=f"cr:c:{course.id}")]]))
    lines = [f"💳 <b>{esc(course.title)}</b>", f"Narxi: <b>{fmt_price(course.price)}</b>", "",
             f"Karta: <code>{esc(st.card_number)}</code>"]
    if st.card_holder:
        lines.append(f"Egasi: {esc(st.card_holder)}")
    if st.pay_note:
        lines += ["", esc(st.pay_note)]
    lines += ["", "To‘lovni amalga oshirib, <b>chek rasmini</b> yuboring. Admin tekshirib, kursni ochadi."]
    await show(tg, callback, chat_id, "\n".join(lines), Markup([
        [Btn("📸 Chek yuborish", callback_data=f"cr:rcpt:{course.id}")], [Btn("⬅️ Kurs", callback_data=f"cr:c:{course.id}")]]))


async def on_receipt(bot, message, session, tg, us, user: dict) -> bool:
    data = us.state_data or {}
    uid = user["id"]
    course = await session.get(Course, data.get("course"))
    if course is None or course.bot_id != bot.id or course.access != ACCESS_PAID:
        await set_state(session, us)
        return False
    if message.get("photo"):
        file_id, kind = message["photo"][-1]["file_id"], "photo"
    elif (message.get("document") or {}).get("mime_type", "").startswith("image/"):
        file_id, kind = message["document"]["file_id"], "document"
    else:
        await tg.send_message(chat_id=uid, text="📸 Chekning rasmini (skrinshot) yuboring. Bekor qilish: /cancel")
        return True
    await set_state(session, us)
    if await enrollment_of(session, course.id, uid):
        await tg.send_message(chat_id=uid, text="Siz allaqachon kursga yozilgansiz.")
        return True
    if await pending_payment(session, course.id, uid):
        await tg.send_message(chat_id=uid, text="⏳ Oldingi chekingiz hali tekshirilmoqda.")
        return True
    pay = CoursePayment(bot_id=bot.id, course_id=course.id, tg_user_id=uid, user_name=display_name(user),
                        amount=course.price, receipt_file_id=file_id, receipt_type=kind)
    session.add(pay)
    await session.commit()
    await tg.send_message(chat_id=uid, text="✅ Chek yuborildi. Admin tekshirgach sizga xabar beramiz.")
    await course_admin.notify_payment(tg, session, bot, course, pay, user)
    return True


# ------------------------------------------------------------------ lessons

def lesson_markup(ctx: Ctx, lesson, enrolled: bool, settings) -> Markup:
    rows = []
    if enrolled and lesson.id not in ctx.done:
        rows.append([Btn("✅ Tugatdim", callback_data=f"cr:done:{lesson.id}")])
    i = ctx.index(lesson.id)
    nav = []
    if i > 0:
        nav.append(Btn("⬅️ Oldingi", callback_data=f"cr:l:{ctx.lessons[i - 1].id}"))
    if 0 <= i < ctx.total - 1:
        nav.append(Btn("Keyingi ➡️", callback_data=f"cr:l:{ctx.lessons[i + 1].id}"))
    if nav:
        rows.append(nav)
    extra = []
    if enrolled and settings.questions_enabled:
        extra.append(Btn("❓ Savol", callback_data=f"cr:ask:{lesson.id}"))
    extra.append(Btn("📖 Dastur", callback_data=f"cr:syl:{ctx.course.id}:{max(0, i) // PAGE}"))
    rows.append(extra)
    return Markup(rows)


async def locked_message(tg, callback, uid, session, bot, course, lesson, ctx: Ctx):
    back = Markup([[Btn("📖 Dastur", callback_data=f"cr:syl:{course.id}:0")]])
    if ctx.enrollment is None:
        if course.access == ACCESS_FREE:
            text = "🔒 Bu dars yopiq. Avval kursga yoziling."
        else:
            text = "🔒 Bu dars yopiq. Kursga kirish uchun kurs sahifasiga o‘ting."
        return await show(tg, callback, uid, text, Markup([[Btn("📘 Kurs", callback_data=f"cr:c:{course.id}")]]))
    if course.unlock_mode == UNLOCK_SEQ:
        text = "🔒 Bu dars hali yopiq: avvalgi darsni tugatganingizdan keyin ochiladi."
    else:
        nxt = logic.drip_open_at(ctx.enrollment.enrolled_at, ctx.index(lesson.id), course.drip_days, ctx.settings.drip_hour, ctx.tz)
        text = f"🔒 Bu dars hali yopiq. Ochilish vaqti: <b>{fmt_dt(nxt, ctx.tz)}</b>"
    await show(tg, callback, uid, text, back)


async def open_lesson(tg, callback, uid, session, bot, lesson, admin: bool):
    course = await visible_course(session, bot, lesson.course_id, uid, admin)
    if course is None:
        return await show(tg, callback, uid, "Kurs topilmadi.", Markup([[Btn("📚 Kurslar", callback_data="cr:cat:0")]]))
    ctx = await context(session, bot, course, uid, admin)
    if not ctx.can_open(lesson):
        return await locked_message(tg, callback, uid, session, bot, course, lesson, ctx)
    protect = not admin
    first = True
    for f in await files_of(session, lesson.id):
        method, field = MEDIA_SENDERS.get(f.file_type, ("send_document", "document"))
        kw = {"chat_id": uid, field: f.file_id, "protect_content": protect}
        if first:
            kw["caption"], kw["parse_mode"] = f"📘 <b>{esc(lesson.title)}</b>"[:200], "HTML"
            first = False
        try:
            await getattr(tg, method)(**kw)
        except Forbidden:
            raise
        except TelegramError as exc:
            logger.warning("lesson %s file %s not sent: %s", lesson.id, f.id, exc)
            await tg.send_message(chat_id=uid, text="⚠️ Fayllardan biri yuborilmadi. Admin bilan bog‘laning.")
    head = f"📘 <b>{esc(lesson.title)}</b>" if first else f"📍 <b>{esc(lesson.title)}</b>"
    body = f"{head}\n\n{esc(lesson.text)}" if lesson.text else head
    if lesson.is_preview and ctx.enrollment is None and not admin:
        body += "\n\n👁 <i>Bu — tanishuv darsi.</i>"
    await tg.send_message(chat_id=uid, text=body[:4096], parse_mode="HTML", protect_content=protect,
                          reply_markup=lesson_markup(ctx, lesson, ctx.enrollment is not None, ctx.settings))


async def go_next(tg, callback, uid, session, bot, course, admin: bool):
    ctx = await context(session, bot, course, uid, admin)
    if not ctx.lessons:
        return await show(tg, callback, uid, "Darslar hali qo‘shilmagan.", Markup([[Btn("⬅️ Kurs", callback_data=f"cr:c:{course.id}")]]))
    target = next((ls for ls in ctx.lessons if ls.id not in ctx.done), ctx.lessons[0])
    if not ctx.can_open(target):
        nxt = ctx.next_open()
        text = "⏳ Hozircha ochiq darslarning hammasini tugatdingiz."
        if nxt:
            text += f"\nKeyingi dars: <b>{fmt_dt(nxt, ctx.tz)}</b>"
        return await show(tg, callback, uid, text, Markup([[Btn("📖 Dastur", callback_data=f"cr:syl:{course.id}:0")]]))
    await open_lesson(tg, callback, uid, session, bot, target, admin)


async def mark_done(tg, uid, session, bot, lesson, user: dict):
    course = await session.get(Course, lesson.course_id)
    if course is None or course.bot_id != bot.id:
        return
    ctx = await context(session, bot, course, uid)
    if ctx.enrollment is None or not ctx.can_open(lesson):
        return
    if lesson.id not in ctx.done:
        session.add(LessonProgress(course_id=course.id, lesson_id=lesson.id, tg_user_id=uid))
        await session.commit()
        ctx.done.add(lesson.id)
    pct = logic.percent(ctx.done_count, ctx.total)
    if ctx.done_count >= ctx.total and ctx.enrollment.completed_at is None:
        ctx.enrollment.completed_at = utcnow()
        await session.commit()
        return await send_certificate(tg, uid, course, ctx.enrollment, user)
    kb = []
    ctx2 = await context(session, bot, course, uid)
    i = ctx.index(lesson.id)
    if i + 1 < ctx.total and ctx2.can_open(ctx.lessons[i + 1]):
        kb.append([Btn("Keyingi dars ➡️", callback_data=f"cr:l:{ctx.lessons[i + 1].id}")])
    text = f"✅ Dars yakunlandi!\n📈 {logic.bar(pct)} {pct}% ({ctx.done_count}/{ctx.total})"
    nxt = ctx2.next_open()
    if nxt and not kb:
        text += f"\n⏰ Keyingi dars: <b>{fmt_dt(nxt, ctx.tz)}</b>"
    kb.append([Btn("📖 Dastur", callback_data=f"cr:syl:{course.id}:0")])
    await tg.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=Markup(kb))


async def send_certificate(tg, uid, course, enrollment, user: dict):
    when = enrollment.completed_at.strftime("%d.%m.%Y") if enrollment.completed_at else ""
    await tg.send_message(
        chat_id=uid, parse_mode="HTML",
        text=(f"🎓 <b>SERTIFIKAT</b>\n\n{esc(display_name(user) if user else enrollment.user_name)}\n"
              f"«<b>{esc(course.title)}</b>» kursini muvaffaqiyatli yakunladi.\n\n📅 {when}\n\nTabriklaymiz! 🎉"),
        reply_markup=Markup([[Btn("📚 Boshqa kurslar", callback_data="cr:cat:0")]]))


# ------------------------------------------------------------------ updates

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
    if data.startswith("ca:"):
        if admin:
            await course_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    if data == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, uid, session, use_cache=False):
            await show_home(tg, None, uid, session, bot)
        return
    if not data.startswith("cr:"):
        return
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)
    parts = data.split(":")
    act, arg = parts[1], parts[2:]
    num = [int(p) for p in arg if p.lstrip("-").isdigit()]
    if act != "ask" and us.state and us.state.startswith("cr_"):
        await set_state(session, us)

    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "help":
        return await show(tg, callback, uid, HELP, Markup([[Btn("🏠 Bosh sahifa", callback_data="cr:home")]]))
    if act == "cat":
        return await show_catalog(tg, callback, uid, session, bot, num[0] if num else 0, admin)
    if act == "my":
        return await show_my(tg, callback, uid, session, bot)
    if act == "codeany":
        await set_state(session, us, "cr_code", {"course": None, "tries": 0})
        return await show(tg, callback, uid, "🔑 Kurs kodini yozing.", Markup([[Btn("✖️ Bekor qilish", callback_data="cr:home")]]))
    if not num:
        return
    if act in ("l", "done", "ask"):
        lesson = await session.get(Lesson, num[0])
        if lesson is None:
            return await show(tg, callback, uid, "Dars topilmadi.", Markup([[Btn("📚 Kurslar", callback_data="cr:cat:0")]]))
        if act == "l":
            return await open_lesson(tg, callback, uid, session, bot, lesson, admin)
        if act == "done":
            return await mark_done(tg, uid, session, bot, lesson, user)
        return await start_question(tg, uid, session, bot, us, lesson)
    course = await visible_course(session, bot, num[0], uid, admin)
    if course is None:
        return await show(tg, callback, uid, "Kurs topilmadi yoki yashirilgan.", Markup([[Btn("📚 Kurslar", callback_data="cr:cat:0")]]))
    if act == "c":
        return await show_course(tg, callback, uid, session, bot, course, admin)
    if act == "syl":
        return await show_syllabus(tg, callback, uid, session, bot, course, num[1] if len(num) > 1 else 0, admin)
    if act == "go":
        return await go_next(tg, callback, uid, session, bot, course, admin)
    if act == "cert":
        en = await enrollment_of(session, course.id, uid)
        if en and en.completed_at:
            return await send_certificate(tg, uid, course, en, user)
        return
    if await enrollment_of(session, course.id, uid):
        return await show_course(tg, callback, uid, session, bot, course, admin)
    if act == "join" and course.access == ACCESS_FREE:
        await enroll(session, bot, course, user, VIA_FREE)
        return await welcome_enrolled(tg, bot, course, uid)
    if act == "code" and course.access == ACCESS_CODE:
        await set_state(session, us, "cr_code", {"course": course.id, "tries": 0})
        return await show(tg, callback, uid, f"🔑 <b>{esc(course.title)}</b> kursining kodini yozing.",
                          Markup([[Btn("✖️ Bekor qilish", callback_data=f"cr:c:{course.id}")]]))
    if act == "pay" and course.access == ACCESS_PAID:
        if await pending_payment(session, course.id, uid):
            return await show_course(tg, callback, uid, session, bot, course, admin)
        return await payment_info(tg, callback, uid, session, bot, course)
    if act == "rcpt" and course.access == ACCESS_PAID:
        await set_state(session, us, "cr_receipt", {"course": course.id})
        return await show(tg, callback, uid, "📸 Chek rasmini yuboring.", Markup([[Btn("✖️ Bekor qilish", callback_data=f"cr:c:{course.id}")]]))


async def start_question(tg, uid, session, bot, us, lesson):
    st = await get_settings(session, bot.id)
    if not st.questions_enabled or await enrollment_of(session, lesson.course_id, uid) is None:
        return
    await set_state(session, us, "cr_ask", {"lesson": lesson.id})
    await tg.send_message(chat_id=uid, parse_mode="HTML", text=f"❓ <b>{esc(lesson.title)}</b> bo‘yicha savolingizni yozing. Bekor qilish: /cancel")


async def _on_code(bot, text, session, tg, us, user):
    uid = user["id"]
    data = us.state_data or {}
    code = text.strip().lower()
    if data.get("course"):
        courses = [await session.get(Course, data["course"])]
    else:
        courses = list((await session.execute(select(Course).where(
            Course.bot_id == bot.id, Course.access == ACCESS_CODE, Course.is_published.is_(True)))).scalars().all())
    match = next((c for c in courses if c and c.bot_id == bot.id and c.access == ACCESS_CODE
                  and c.access_code and c.access_code.strip().lower() == code), None)
    if match is None:
        tries = int(data.get("tries", 0)) + 1
        if tries >= MAX_CODE_TRIES:
            await set_state(session, us)
            return await tg.send_message(chat_id=uid, text="❌ Kod noto‘g‘ri. Urinishlar tugadi. Kodni admindan oling.")
        await set_state(session, us, "cr_code", {**data, "tries": tries})
        return await tg.send_message(chat_id=uid, text=f"❌ Kod noto‘g‘ri ({MAX_CODE_TRIES - tries} ta urinish qoldi). Qayta yozing yoki /cancel.")
    await set_state(session, us)
    await enroll(session, bot, match, user, VIA_CODE)
    await welcome_enrolled(tg, bot, match, uid)


async def _on_question(bot, text, session, tg, us, user):
    uid = user["id"]
    lesson = await session.get(Lesson, (us.state_data or {}).get("lesson"))
    await set_state(session, us)
    if lesson is None or await enrollment_of(session, lesson.course_id, uid) is None:
        return
    q = CourseQuestion(bot_id=bot.id, course_id=lesson.course_id, lesson_id=lesson.id, tg_user_id=uid,
                       user_name=display_name(user), text=text[:2000])
    session.add(q)
    await session.commit()
    await tg.send_message(chat_id=uid, text="✅ Savolingiz yuborildi. Javob kelgach xabar beramiz.")
    await course_admin.notify_question(tg, session, bot, q, lesson)


async def _on_message(bot, message, session, tg):
    if (message.get("chat") or {}).get("type") != "private":
        return
    sender = message["from"]
    uid = sender["id"]
    if sender.get("is_bot"):
        return
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    payload = text.split(maxsplit=1)[1].strip() if cmd == "/start" and len(text.split()) > 1 else None
    await touch_user(session, bot.id, sender, source=payload)
    admin = await cinema.is_admin(session, bot, uid)
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)

    if cmd in ("/start", "/cancel"):
        if us.state and us.state.startswith("ca_") and cmd == "/cancel" and admin:
            await course_admin.cancel(bot, session, tg, us, uid)
        await set_state(session, us)
        if cmd == "/start" and payload and payload[0] == "c" and payload[1:].isdigit():
            course = await visible_course(session, bot, int(payload[1:]), uid, admin)
            if course:
                return await show_course(tg, None, uid, session, bot, course, admin)
        return await show_home(tg, None, uid, session, bot)
    if admin and cmd == "/admin":
        await set_state(session, us)
        return await course_admin.show_home(tg, None, uid, session, bot)
    if us.state and us.state.startswith("ca_") and admin:
        if await course_admin.on_message(bot, message, session, tg, us):
            return
    if us.state == "cr_receipt":
        if await on_receipt(bot, message, session, tg, us, sender):
            return
    if us.state == "cr_code" and text:
        return await _on_code(bot, text, session, tg, us, sender)
    if us.state == "cr_ask" and text:
        return await _on_question(bot, text, session, tg, us, sender)
    await show_home(tg, None, uid, session, bot)
