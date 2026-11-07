from telegram import InlineKeyboardButton, Update, Bot as TgBot
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.logger import get_logger
from core.validators import validate_bot_token, validate_menu_title, validate_text_length
from core.config import settings
from core.webhook_manager import set_webhook
from constructor.flows.bots import open_bot, resume_or_show_bots
from constructor.session import (
    ensure_constructor_user,
    restore_builder_session,
    save_builder_session,
)
from constructor.states import (
    WAITING_FOR_TOKEN,
    WAITING_FOR_START_MESSAGE,
    WAITING_FOR_MENU_NAME,
    WAITING_FOR_MENU_MESSAGE,
    WAITING_FOR_BUTTON_TEXT,
    WAITING_FOR_ACTION_TEXT,
    WAITING_FOR_ACTION_LINK,
    WAITING_FOR_ADMIN_ID,
)
from constructor.ui import show_screen
from models.bots import Bot
from models.menus import Menu

logger = get_logger("handlers")


def build_webhook_url(token: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhooks/{token}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register the constructor user and resume their most recent builder context."""
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    builder_session = await restore_builder_session(user.id, context)
    if builder_session.pending_state:
        await show_resume_prompt(update, context)
    else:
        await resume_or_show_bots(update, context)
    logger.info("Constructor opened by user_id=%s", tg_user.id)


async def add_bot_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(
        user.id,
        context,
        pending_state=WAITING_FOR_TOKEN,
        draft={"flow": "create_bot"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🤖 <b>1/3 — Bot tokeni</b>\n\n"
        "BotFather’da <code>/newbot</code> yuboring va u bergan tokenni shu chatga jo‘nating.\n\n"
        "Token faqat botni ulash uchun ishlatiladi.",
        parse_mode="HTML",
        reply_markup=None,
    )


async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await resume_or_show_bots(update, context)


async def show_resume_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    descriptions = {
        WAITING_FOR_TOKEN: "bot tokenini kiritish",
        WAITING_FOR_START_MESSAGE: "child botning bosh xabarini yozish",
        WAITING_FOR_MENU_NAME: "yangi menu nomini yozish",
        WAITING_FOR_MENU_MESSAGE: "menu xabarini yozish",
        WAITING_FOR_BUTTON_TEXT: "tugma matnini yozish",
        WAITING_FOR_ACTION_TEXT: "action matnini yozish",
        WAITING_FOR_ACTION_LINK: "action havolasini yozish",
        WAITING_FOR_ADMIN_ID: "admin ID raqamini yozish",
    }
    description = descriptions.get(state, "oldingi sozlashni davom ettirish")
    bot_id = context.user_data.get("current_bot_id")
    keyboard = [[InlineKeyboardButton("▶️ Davom ettirish", callback_data="resume_draft")]]
    if bot_id:
        keyboard.append([InlineKeyboardButton("⚙️ Bot boshqaruvi", callback_data=f"bot_{bot_id}")])
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel")])
    await show_screen(
        update,
        f"⏸ Siz {description} bosqichida to‘xtagansiz.\n\nDavom ettirasizmi?",
        keyboard,
        edit=bool(update.callback_query),
    )


async def resume_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompts = {
        WAITING_FOR_TOKEN: "🤖 BotFather bergan tokenni yuboring.",
        WAITING_FOR_START_MESSAGE: "📝 Child botning <code>/start</code> xabarini yuboring.",
        WAITING_FOR_MENU_NAME: "📂 Yangi menu nomini yuboring.",
        WAITING_FOR_MENU_MESSAGE: "📝 Menu ochilganda ko‘rinadigan xabarni yuboring.",
        WAITING_FOR_BUTTON_TEXT: "🔘 Tugma ustida yoziladigan matnni yuboring.",
        WAITING_FOR_ACTION_TEXT: "📝 Tugma bosilganda yuboriladigan matnni yuboring.",
        WAITING_FOR_ACTION_LINK: "🔗 URL manzilini yuboring.",
        WAITING_FOR_ADMIN_ID: "👨‍💼 Adminning Telegram ID raqamini yuboring.",
    }
    await update.callback_query.answer()
    prompt = prompts.get(context.user_data.get("state"))
    if prompt:
        await update.callback_query.message.reply_text(prompt, parse_mode="HTML")
    else:
        await resume_or_show_bots(update, context)


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_TOKEN:
        return

    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        token = validate_bot_token(update.message.text.strip())
    except Exception:
        await update.message.reply_text(
            "❌ Token formati noto‘g‘ri. BotFather bergan tokenni to‘liq nusxalab yuboring."
        )
        return

    try:
        async with TgBot(token) as telegram_bot:
            bot_info = await telegram_bot.get_me()
    except Exception:
        await update.message.reply_text(
            "❌ Token tekshirilmadi. U to‘g‘ri ekanini BotFather orqali tekshirib, qayta yuboring."
        )
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Bot).where(Bot.token == token))
        bot = result.scalar_one_or_none()
        if bot and bot.owner_id != user.id:
            await update.message.reply_text(
                "❌ Bu bot boshqa TeleCraft hisobiga ulangan. Boshqa token yuboring."
            )
            return

        if bot is None:
            bot = Bot(
                owner_id=user.id,
                name=bot_info.first_name or bot_info.username or "Yangi bot",
                username=bot_info.username,
                token=token,
                is_active=True,
                webhook_url=build_webhook_url(token),
                webhook_set=False,
                onboarding_completed=False,
            )
            session.add(bot)
            await session.flush()
        else:
            bot.name = bot_info.first_name or bot_info.username or bot.name
            bot.username = bot_info.username
            bot.is_active = True
            bot.webhook_url = build_webhook_url(token)
            bot.webhook_set = False

        menu_result = await session.execute(
            select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True)
        )
        start_menu = menu_result.scalar_one_or_none()
        if start_menu is None:
            start_menu = Menu(
                bot_id=bot.id,
                title="Bosh menyu",
                message_text=None,
                is_start=True,
                position=0,
            )
            session.add(start_menu)
            await session.flush()
        await session.commit()
        bot_id = bot.id
        start_menu_id = start_menu.id

    webhook_ok = await set_webhook(token, build_webhook_url(token))
    await save_builder_session(
        user.id,
        context,
        current_bot_id=bot_id,
        current_menu_id=start_menu_id,
        pending_state=WAITING_FOR_START_MESSAGE,
        draft={"flow": "new_bot", "webhook_ok": webhook_ok},
    )

    hook_message = "✅ Telegram bilan ulanish tayyor." if webhook_ok else "⚠️ Ulanish hali tekshirilmoqda."
    await update.message.reply_text(
        f"✅ <b>{bot_info.first_name or bot_info.username}</b> qo‘shildi.\n{hook_message}\n\n"
        "<b>2/3 — Bosh xabar</b>\n\n"
        "Foydalanuvchi child botga <code>/start</code> yozganda qanday xabar ko‘rsin? "
        "Matnni hozir yuboring.",
        parse_mode="HTML",
    )


async def edit_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    if not context.user_data.get("current_menu_id"):
        await open_bot(update, context)
        return
    await save_builder_session(
        user.id,
        context,
        pending_state=WAITING_FOR_START_MESSAGE,
        draft={"flow": "edit_start"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "📝 Child botning <code>/start</code> xabarini yuboring.", parse_mode="HTML"
    )


async def handle_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_START_MESSAGE:
        return

    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        message_text = validate_text_length(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Xabar bo‘sh bo‘lmasin. Matnni qayta yuboring.")
        return

    menu_id = context.user_data.get("current_menu_id")
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Menu).where(Menu.id == menu_id, Menu.bot_id == bot_id)
        )
        menu = result.scalar_one_or_none()
        if menu is None:
            await update.message.reply_text("❌ Bosh menyu topilmadi. Bot boshqaruviga qayting.")
            return
        menu.message_text = message_text
        result = await session.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.onboarding_completed = True
        await session.commit()

    await save_builder_session(
        user.id,
        context,
        current_bot_id=bot_id,
        current_menu_id=menu_id,
        pending_state="",
        draft={},
    )
    await show_screen(
        update,
        "🎉 <b>Boshlang‘ich sozlash tugadi.</b>\n\n"
        "Endi child botga <code>/start</code> yuborilganda shu xabar chiqadi. "
        "Xohlasangiz birinchi tugmani hozir qo‘shing.",
        [[InlineKeyboardButton("➕ Birinchi tugma", callback_data="start_buttons")],
         [InlineKeyboardButton("⚙️ Bot boshqaruvi", callback_data=f"bot_{bot_id}")]],
        edit=False,
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_screen(
        update,
        "❓ <b>TeleCraft qanday ishlaydi?</b>\n\n"
        "1. BotFather’da bot yarating.\n"
        "2. Tokenni shu yerga yuboring.\n"
        "3. Bosh xabar, menu va tugmalarni sozlang.\n"
        "4. Child botga <code>/start</code> yuborib sinang.",
        [[InlineKeyboardButton("🤖 Botlarim", callback_data="back_to_bots")],
         [InlineKeyboardButton("➕ Bot yaratish", callback_data="add_bot")]],
    )


async def show_bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            await update.callback_query.answer("Bot topilmadi.", show_alert=True)
            return
        start_result = await session.execute(
            select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True)
        )
        start_menu = start_result.scalar_one_or_none()
    state = "🟢 Ulangan" if bot.webhook_set else "🔴 Ulanmagan"
    start_state = "✅ Tayyor" if start_menu and start_menu.message_text else "⚠️ Sozlanmagan"
    username = f"@{bot.username}" if bot.username else bot.name
    await show_screen(
        update,
        f"📊 <b>{bot.name}</b>\n\n"
        f"Bot: {username}\nWebhook: {state}\nBosh xabar: {start_state}",
        [[InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")]],
    )


async def test_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
    if bot is None or not bot.username:
        await update.callback_query.answer("Bot username’i topilmadi.", show_alert=True)
        return
    await show_screen(
        update,
        "🧪 Sinash uchun child botni oching va unga <code>/start</code> yuboring.",
        [[InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")],
         [InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")]],
    )
