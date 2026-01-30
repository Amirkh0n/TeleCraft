from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from constructor.states import WAITING_FOR_ACTION_TEXT, WAITING_FOR_ACTION_LINK, WAITING_FOR_ADMIN_ID
from core.database import AsyncSessionLocal
from models.button_actions import ButtonAction, ActionType
from models.admin_links import AdminLink
from models.menus import Menu


async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    data = update.callback_query.data
    button_id = int(data.split("_")[1])

    context.user_data["current_button_id"] = button_id

    keyboard = [
        [InlineKeyboardButton("📝 Text", callback_data="action_text")],
        [InlineKeyboardButton("🔗 Link", callback_data="action_link")],
        [InlineKeyboardButton("📂 Menu ochish", callback_data="action_menu")],
        [InlineKeyboardButton("👨‍💼 Adminga yozish", callback_data="action_admin")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_buttons")],
    ]

    await update.callback_query.message.edit_text(
        "Action turini tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def action_text_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_ACTION_TEXT

    await update.callback_query.message.reply_text(
        "Yuboriladigan matnni kiriting:"
    )

async def save_button_action(session, button_id, action_type, value):
    result = await session.execute(
        select(ButtonAction).where(ButtonAction.button_id == button_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.action_type = action_type
        existing.value = value
    else:
        session.add(
            ButtonAction(
                button_id=button_id,
                action_type=action_type,
                value=value,
            )
        )

    await session.commit()


async def handle_action_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ACTION_TEXT:
        return

    text = update.message.text
    button_id = context.user_data.get("current_button_id")

    async with AsyncSessionLocal() as session:
        await save_button_action(
            session,
            button_id,
            ActionType.text,
            text,
        )

    context.user_data.clear()

    await update.message.reply_text("Text action saqlandi ✅")


async def action_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    bot_id = context.user_data.get("current_bot_id")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Menu).where(Menu.bot_id == bot_id)
        )
        menus = result.scalars().all()

    keyboard = [
        [InlineKeyboardButton(menu.title, callback_data=f"select_menu_{menu.id}")]
        for menu in menus
    ]

    await update.callback_query.message.edit_text(
        "Qaysi menu ochilsin?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_menu_for_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    data = update.callback_query.data
    menu_id = int(data.split("_")[2])
    button_id = context.user_data.get("current_button_id")

    async with AsyncSessionLocal() as session:
        await save_button_action(
            session,
            button_id,
            ActionType.menu,
            str(menu_id),
        )

    await update.callback_query.message.reply_text("Menu action saqlandi ✅")


async def action_link_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_ACTION_LINK

    await update.callback_query.message.reply_text(
        "URL manzilni yuboring (https://...):"
    )


async def handle_action_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ACTION_LINK:
        return

    url = update.message.text
    button_id = context.user_data.get("current_button_id")

    async with AsyncSessionLocal() as session:
        await save_button_action(
            session,
            button_id,
            ActionType.link,
            url,
        )

    context.user_data.clear()

    await update.message.reply_text("Link action saqlandi ✅")


# Admin Actiions
async def action_admin_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_ADMIN_ID

    await update.callback_query.message.reply_text(
        "Admin Telegram ID sini yuboring (raqam):"
    )

async def handle_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ADMIN_ID:
        return

    admin_id = int(update.message.text)
    button_id = context.user_data.get("current_button_id")
    bot_id = context.user_data.get("current_bot_id")

    async with AsyncSessionLocal() as session:
        # admin_links ga qo‘shamiz (agar yo‘q bo‘lsa)
        session.add(
            AdminLink(
                bot_id=bot_id,
                admin_tg_id=admin_id,
            )
        )

        # button action saqlaymiz
        await save_button_action(
            session,
            button_id,
            ActionType.admin,
            str(admin_id),
        )

        await session.commit()

    context.user_data.clear()

    await update.message.reply_text("Admin action saqlandi ✅")
