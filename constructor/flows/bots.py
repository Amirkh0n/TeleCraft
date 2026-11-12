from telegram import InlineKeyboardButton, Update, WebAppInfo
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.database import AsyncSessionLocal
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from models.bots import Bot
from webapp import editor_url
from models.menus import Menu


def bot_status(bot: Bot) -> str:
    if not bot.webhook_set:
        return "🟡 Ulanish kutilmoqda"
    if not bot.onboarding_completed:
        return "🟠 Sozlash tugallanmagan"
    return "🟢 Tayyor"


def _editor_row():
    url = editor_url()
    return [[InlineKeyboardButton("🎨 Vizual muharrir", web_app=WebAppInfo(url=url))]] if url else []


async def show_user_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, back: bool = False):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(Bot.owner_id == user.id).order_by(Bot.id.desc())
        )
        bots = result.scalars().all()

    if not bots:
        await show_screen(
            update,
            "👋 Xush kelibsiz!\n\nKod yozmasdan Telegram bot yarating. "
            "Boshlash uchun BotFather’dan olgan tokeningiz kerak bo‘ladi.",
            [[InlineKeyboardButton("➕ Birinchi botimni yaratish", callback_data="add_bot")],
             [InlineKeyboardButton("📖 Qanday ishlaydi?", callback_data="help")]],
            edit=bool(update.callback_query),
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"{bot.name} · {bot_status(bot)}", callback_data=f"bot_{bot.id}")]
        for bot in bots
    ]
    keyboard.append([InlineKeyboardButton("➕ Yangi bot", callback_data="add_bot")])
    keyboard.append([InlineKeyboardButton("❓ Yordam", callback_data="help")])
    await show_screen(
        update,
        "🤖 Botlarim\n\nBoshqarish uchun botni tanlang.",
        keyboard,
        edit=bool(update.callback_query),
    )


async def open_bot(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: int | None = None):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    if bot_id is None:
        data = update.callback_query.data if update.callback_query else ""
        try:
            bot_id = int(data.split("_", 1)[1])
        except (IndexError, ValueError):
            bot_id = context.user_data.get("current_bot_id")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id)
        )
        bot = result.scalar_one_or_none()
        if bot is None:
            await show_user_bots(update, context)
            return
        start_result = await session.execute(
            select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True)
        )
        start_menu = start_result.scalar_one_or_none()

    await save_builder_session(
        user.id,
        context,
        current_bot_id=bot.id,
        current_menu_id=start_menu.id if start_menu else None,
    )

    start_state = "✅ Sozlangan" if start_menu and start_menu.message_text else "⚠️ Matn kutilmoqda"
    mode = {"cinema": "🎬 Kino bot", "booking": "📅 Bron bot"}.get(bot.kind, "🧩 Oddiy bot")
    text = (
        f"🤖 {bot.name}\n"
        f"{bot_status(bot)} · {mode}\n\n"
        f"Bosh xabar: {start_state}\n"
        "Kerakli bo‘limni tanlang."
    )
    keyboard = [
        [InlineKeyboardButton("📝 Bosh xabar", callback_data="edit_start_message")],
        [InlineKeyboardButton("📂 Menyular", callback_data="menus")],
        *_editor_row(),
        [InlineKeyboardButton("🔘 Tugmalar", callback_data="start_buttons")],
        [InlineKeyboardButton("📋 Formalar", callback_data="frm:list")],
        [InlineKeyboardButton("👥 Auditoriya", callback_data="aud:home"),
         InlineKeyboardButton("📣 Broadcast", callback_data="bc:home")],
        [InlineKeyboardButton("🔒 Majburiy obuna", callback_data="sub:home")],
        [InlineKeyboardButton("🎬 Kino bot", callback_data="cin:home"),
         InlineKeyboardButton("📅 Bron bot", callback_data="bkc:home")],
        [InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
        [InlineKeyboardButton("🧪 Sinab ko‘rish", callback_data="test_bot")],
        [InlineKeyboardButton("📊 Holat", callback_data="bot_status")],
        [InlineKeyboardButton("⬅️ Botlarim", callback_data="back_to_bots")],
    ]
    await show_screen(update, text, keyboard, edit=bool(update.callback_query))


async def resume_or_show_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    if bot_id:
        await open_bot(update, context, bot_id=bot_id)
    else:
        await show_user_bots(update, context)
