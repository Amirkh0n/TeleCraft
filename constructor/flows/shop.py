"""Builder panel for shop mode: switch it on/off. Categories, products, orders and settings are
managed inside the child bot by its admins (``/admin``)."""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor.flows.cinema import _back, _current_bot, _no_bot, set_kind
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from models.movies import KIND_STANDARD
from models.shop import KIND_SHOP, Order, ShopProduct

OTHER_MODES = {"cinema": "kino", "booking": "bron", "quiz": "test", "course": "kurs"}


async def shop_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        products = (await session.execute(select(func.count(ShopProduct.id)).where(ShopProduct.bot_id == bot.id))).scalar() or 0
        orders = (await session.execute(select(func.count(Order.id)).where(Order.bot_id == bot.id))).scalar() or 0
    if bot.kind == KIND_SHOP:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "🛒 <b>Do‘kon bot rejimi: yoqilgan</b>\n\n"
            f"Mahsulotlar: <b>{products}</b> · Buyurtmalar: <b>{orders}</b>\n\n"
            f"{username} ga kirib, <code>/admin</code> yozing:\n"
            "• bo‘lim → mahsulot (bir nechta rasm, narx, eski narx/chegirma, ombor soni) → variantlar (o‘lcham/rang);\n"
            "• xaridor: katalog, qidiruv, savat, buyurtma (telefon, yetkazish yoki olib ketish, naqd yoki karta cheki);\n"
            "• buyurtma holatlari (tasdiqlandi → tayyorlanmoqda → yo‘lda → yetkazildi) xaridorga xabar sifatida boradi;\n"
            "• yetkazish narxi, bepul yetkazish chegarasi, minimal buyurtma, statistika.\n\n"
            "Ombor qoldig‘i buyurtma paytida avtomatik kamayadi, bekor qilinsa qaytadi. "
            "Adminlarni «👮 Adminlar» bo‘limidan qo‘shing."
        )
        keyboard = [[InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
                    [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="shpc:off")]]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "🛒 <b>Onlayn do‘kon</b>\n\nMahsulotlaringizni katalogga joylang, mijozlar savatga yig‘ib buyurtma beradi: "
            "yetkazib berish yoki olib ketish, naqd yoki karta orqali to‘lov (chek rasmi bilan).\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga do‘kon oqimi ishlaydi (menyularingiz o‘chmaydi)."
            + (f"\n\n⚠️ Hozir <b>{OTHER_MODES[bot.kind]} bot</b> rejimi yoqilgan; do‘kon botga o‘tsangiz, u o‘chadi (ma’lumotlar saqlanadi)."
               if bot.kind in OTHER_MODES else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Do‘kon botga aylantirish", callback_data="shpc:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def shop_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_SHOP if update.callback_query.data == "shpc:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await shop_home(update, context)
