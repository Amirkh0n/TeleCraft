"""Builder panel for paid-channel mode: switch it on/off. Channels, plans, payments, subscribers and
promo codes are managed inside the child bot by its admins (``/admin``)."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from models.movies import KIND_STANDARD
from models.paid import KIND_PAID, SUB_ACTIVE, PaidPlan, PaidSub

OTHER_MODES = {"cinema": "kino", "booking": "bron", "quiz": "test", "course": "kurs", "shop": "do‘kon", "join": "ariza"}


async def paid_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        plans = (await session.execute(select(func.count(PaidPlan.id)).where(PaidPlan.bot_id == bot.id))).scalar() or 0
        live = (await session.execute(select(func.count(PaidSub.id)).where(PaidSub.bot_id == bot.id, PaidSub.status == SUB_ACTIVE))).scalar() or 0
    if bot.kind == KIND_PAID:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "💎 <b>Pullik kanal rejimi: yoqilgan</b>\n\n"
            f"Tariflar: <b>{plans}</b> · Faol obunachilar: <b>{live}</b>\n\n"
            "Ishga tushirish:\n"
            f"1. {username} ni yopiq kanalingizga <b>administrator</b> qiling («Foydalanuvchilarni taklif qilish» va "
            "«Foydalanuvchilarni cheklash» huquqlari bilan).\n"
            "2. Botga kirib <code>/admin</code> yozing: kanal paydo bo‘ladi. «Sozlamalar»da karta raqamini kiriting, "
            "«Tariflar»da tarif yarating.\n\n"
            "Imkoniyatlar: bir nechta tarif va kanal, karta + chek rasmi bilan to‘lov (admin tasdiqlaydi), promokodlar, "
            "bepul sinov, bir martalik kirish havolalari, tugashidan 3 va 1 kun oldin eslatma, muddat tugagach kanaldan "
            "avtomatik chiqarish (ban qilinmaydi), obunachilar ro‘yxati va statistika.\n\n"
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="pdc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "💎 <b>Pullik yopiq kanal</b>\n\nObunachilar tarif tanlab to‘laydi, bot ularga kanalga kirish havolasini beradi "
            "va muddat tugagach avtomatik chiqaradi.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga shu oqim ishlaydi (menyularingiz o‘chmaydi)."
            + (f"\n\n⚠️ Hozir <b>{OTHER_MODES[bot.kind]} bot</b> rejimi yoqilgan; pullik kanalga o‘tsangiz, u o‘chadi (ma’lumotlar saqlanadi)."
               if bot.kind in OTHER_MODES else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Pullik kanal botiga aylantirish", callback_data="pdc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def paid_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_PAID if update.callback_query.data == "pdc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await paid_home(update, context)
