"""Builder panel for join-request mode: switch it on/off. Channels/groups, modes, questions, links and
pending requests are managed inside the child bot by its admins (``/admin``)."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from models.join import KIND_JOIN, OPEN_STATUSES, JoinChat, JoinRequest
from models.movies import KIND_STANDARD

OTHER_MODES = {"cinema": "kino", "booking": "bron", "quiz": "test", "course": "kurs", "shop": "do‘kon", "paid": "pullik kanal"}


async def join_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        chats = (await session.execute(select(func.count(JoinChat.id)).where(JoinChat.bot_id == bot.id))).scalar() or 0
        waiting = (await session.execute(select(func.count(JoinRequest.id)).where(
            JoinRequest.bot_id == bot.id, JoinRequest.status.in_(OPEN_STATUSES)))).scalar() or 0
    if bot.kind == KIND_JOIN:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "📨 <b>Ariza bot rejimi: yoqilgan</b>\n\n"
            f"Ulangan kanal/guruhlar: <b>{chats}</b> · Kutilayotgan arizalar: <b>{waiting}</b>\n\n"
            "Ishga tushirish:\n"
            f"1. {username} ni kanal/guruhingizga <b>administrator</b> qiling («Foydalanuvchilarni taklif qilish» huquqi kerak).\n"
            "2. Botga kirib <code>/admin</code> yozing: kanal o‘zi paydo bo‘ladi.\n"
            "3. «Havolalar» bo‘limida «so‘rov bilan qo‘shilish» havolasini yarating va tarqating.\n\n"
            "Imkoniyatlar: avto-qabul (darhol yoki kechikish bilan), qo‘lda qabul (✅/❌), captcha, 1–3 ta anketa savoli, "
            "nomlangan havolalar bo‘yicha statistika, hammasini birdan qabul/rad qilish, o‘z salomlashish matnlari.\n\n"
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="jnpc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "📨 <b>Ariza qabul qiluvchi bot</b>\n\nKanal yoki guruhga «so‘rov bilan qo‘shilish» orqali kelgan arizalarni "
            "avtomatik yoki qo‘lda qabul qiladi, captcha va savollar bilan botlardan himoya qiladi.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga shu oqim ishlaydi (menyularingiz o‘chmaydi)."
            + (f"\n\n⚠️ Hozir <b>{OTHER_MODES[bot.kind]} bot</b> rejimi yoqilgan; ariza botga o‘tsangiz, u o‘chadi (ma’lumotlar saqlanadi)."
               if bot.kind in OTHER_MODES else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Ariza botga aylantirish", callback_data="jnpc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def join_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_JOIN if update.callback_query.data == "jnpc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await join_home(update, context)
