"""Builder panel for quiz mode: switch it on/off. Tests are created and managed inside the child
bot (by any user, or only admins if the admins restrict it)."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from core.logger import get_logger
from core.webhook_manager import build_webhook_url, set_webhook
from models.movies import KIND_STANDARD
from models.quiz import KIND_QUIZ, QuizSettings, QuizTest

logger = get_logger("constructor.quiz")


async def quiz_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        tests = (await session.execute(select(func.count(QuizTest.id)).where(QuizTest.bot_id == bot.id))).scalar() or 0
        st = (await session.execute(select(QuizSettings).where(QuizSettings.bot_id == bot.id))).scalar_one_or_none()
    if bot.kind == KIND_QUIZ:
        username = f"@{bot.username}" if bot.username else "child bot"
        who = "faqat adminlar" if st and st.who_can_create == "admins" else "hamma foydalanuvchi"
        text = (
            "🧠 <b>Test bot rejimi: yoqilgan</b>\n\n"
            f"Testlar: <b>{tests}</b>\nTest yaratish: <b>{who}</b>\n\n"
            f"{username} ga kirib, test yaratish mumkin:\n"
            "• nom, tavsif va <b>har bir savol uchun vaqt</b>ni kiriting;\n"
            "• savollarni <b>.txt fayl</b> (<code>#savol</code>, <code>+to‘g‘ri</code>, <code>-xato</code>), matn yoki Telegram «Quiz» so‘rovi sifatida yuboring;\n"
            "• test havolasi (<code>t.me/bot?start=t1</code>) orqali ulashiladi.\n\n"
            "Admin paneli (<code>/admin</code>): barcha testlarni boshqarish/yashirish, kim test yaratishi, limitlar, statistika. "
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="qzc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "🧠 <b>Test bot</b>\n\nFoydalanuvchilar Telegram so‘rovnomalari ko‘rinishida vaqt bilan test ishlaydi: natija, reyting, "
            "xatolar tahlili. Test yaratishni bitta <b>txt fayl</b> bilan qilish mumkin, hamma o‘z testini yarata oladi.\n\n"
            "O‘quv markaz, maktab, universitet, bilim bellashuvi uchun.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga test oqimi ishlaydi (menyularingiz o‘chmaydi)."
            + (f"\n\n⚠️ Hozir <b>{'kino' if bot.kind == 'cinema' else 'bron'} bot</b> rejimi yoqilgan; test botga o‘tsangiz, u o‘chadi (ma’lumotlar saqlanadi)."
               if bot.kind in ("cinema", "booking") else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Test botga aylantirish", callback_data="qzc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def quiz_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_QUIZ if update.callback_query.data == "qzc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
        token = bot.plain_token
    if kind == KIND_QUIZ:
        try:  # poll answers only arrive if the webhook allows the poll_answer update type
            await set_webhook(token, build_webhook_url(token))
        except Exception:
            logger.warning("Could not refresh the webhook for a quiz bot", exc_info=True)
    await quiz_home(update, context)
