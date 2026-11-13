"""Builder panel for course mode: switch it on/off. Courses, lessons, payments and students are
managed inside the child bot by its admins (``/admin``)."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from models.course import KIND_COURSE, Course, Enrollment
from models.movies import KIND_STANDARD

OTHER_MODES = {"cinema": "kino", "booking": "bron", "quiz": "test", "shop": "do‘kon"}


async def course_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        courses = (await session.execute(select(func.count(Course.id)).where(Course.bot_id == bot.id))).scalar() or 0
        students = (await session.execute(select(func.count(Enrollment.id)).where(Enrollment.bot_id == bot.id))).scalar() or 0
    if bot.kind == KIND_COURSE:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "🎓 <b>Kurs bot rejimi: yoqilgan</b>\n\n"
            f"Kurslar: <b>{courses}</b> · O‘quvchilar: <b>{students}</b>\n\n"
            f"{username} ga kirib, <code>/admin</code> yozing:\n"
            "• kurs → modul → dars tuzilmasi; dars = matn + video/audio/PDF/rasm (bir nechta fayl);\n"
            "• kirish: <b>bepul</b>, <b>kod</b> bilan yoki <b>pullik</b> (karta raqamiga o‘tkazma + chek rasmi, admin tasdiqlaydi);\n"
            "• darslar: <b>hammasi ochiq</b>, <b>ketma-ket</b> yoki <b>jadval bo‘yicha</b> (masalan har kuni bittadan, eslatma bilan);\n"
            "• o‘quvchi progressi, sertifikat, dars bo‘yicha savollar va statistika.\n\n"
            "Darslar o‘quvchilarga nusxalash/uzatishdan himoyalangan holda yuboriladi. "
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="crsc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "🎓 <b>Kurs bot</b>\n\nO‘quv markaz, ustoz yoki bloger uchun: video darslarni modul va darslarga bo‘lib joylang, "
            "kursni bepul, kod bilan yoki pullik qiling, o‘quvchilar progressini kuzating.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga kurs oqimi ishlaydi (menyularingiz o‘chmaydi)."
            + (f"\n\n⚠️ Hozir <b>{OTHER_MODES[bot.kind]} bot</b> rejimi yoqilgan; kurs botga o‘tsangiz, u o‘chadi (ma’lumotlar saqlanadi)."
               if bot.kind in OTHER_MODES else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Kurs botga aylantirish", callback_data="crsc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def course_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_COURSE if update.callback_query.data == "crsc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await course_home(update, context)
