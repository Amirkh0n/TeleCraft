"""Builder panel for booking mode: switch it on/off. Everything else (services, specialists,
schedule, reminders) is managed by admins inside the child bot with ``/admin``."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from engine.booking_time import fmt_reminders
from models.booking import KIND_BOOKING, BookingService, BookingSettings
from models.movies import KIND_STANDARD


async def booking_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        services = (await session.execute(select(func.count(BookingService.id)).where(BookingService.bot_id == bot.id))).scalar() or 0
        st = (await session.execute(select(BookingSettings).where(BookingSettings.bot_id == bot.id))).scalar_one_or_none()
    if bot.kind == KIND_BOOKING:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "📅 <b>Bron bot rejimi: yoqilgan</b>\n\n"
            f"Xizmatlar: <b>{services}</b>\n"
            f"Tasdiqlash: <b>{'avtomatik' if (st is None or st.auto_confirm) else 'admin qo‘lda'}</b>\n"
            f"Eslatmalar: <b>{fmt_reminders(st.reminders) if st else '—'}</b>\n\n"
            f"Sozlash <b>child botning o‘zida</b>: {username} → <code>/admin</code>.\n"
            "1. 🧾 Xizmatlar (nomi, davomiyligi, narxi)\n2. 👤 Mutaxassislar (ixtiyoriy)\n"
            "3. 🕒 Ish vaqti va 🏖 dam kunlari\n4. ⚙️ Sozlamalar: tasdiqlash usuli, eslatma vaqti, bekor qilish muddati.\n\n"
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing: ular bronlarni tasdiqlaydi va bildirishnoma oladi."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="bkc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "📅 <b>Bron bot</b>\n\nMijozlar xizmat, mutaxassis, kun va vaqtni tanlab joy band qiladi. "
            "Bot band vaqtni yopadi, adminga xabar beradi va bron oldidan mijozga eslatma yuboradi.\n\n"
            "Sartaroshxona, klinika, o‘quv markaz, avto servis va boshqalar uchun.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga bron oqimi ishlaydi (menyularingiz o‘chmaydi)."
            + ("\n\n⚠️ Hozir <b>kino bot</b> rejimi yoqilgan; bron botga o‘tsangiz, u o‘chadi (kinolar saqlanadi)." if bot.kind == "cinema" else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Bron botga aylantirish", callback_data="bkc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def booking_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_BOOKING if update.callback_query.data == "bkc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await booking_home(update, context)
