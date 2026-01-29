from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.menus import Menu
from constructor.flows.bots import open_bot

from constructor.states import WAITING_FOR_MENU_NAME


async def show_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    bot_id = context.user_data.get("current_bot_id")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Menu).where(Menu.bot_id == bot_id)
        )
        menus = result.scalars().all()

    keyboard = []

    for menu in menus:
        keyboard.append(
            [InlineKeyboardButton(menu.title, callback_data=f"menu_{menu.id}")]
        )

    keyboard.append(
        [InlineKeyboardButton("➕ Menu qo‘shish", callback_data="add_menu")]
    )
    keyboard.append(
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_bot")]
    )

    await update.callback_query.message.edit_text(
        "Menular ro‘yxati:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def back_to_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    bot_id = context.user_data.get("current_bot_id")
    await open_bot(update, context, bot_id)


async def add_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_MENU_NAME

    await update.callback_query.message.reply_text(
        "Yangi menu nomini yuboring:"
    )


async def handle_menu_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_MENU_NAME:
        return

    title = update.message.text
    bot_id = context.user_data.get("current_bot_id")

    async with AsyncSessionLocal() as session:
        menu = Menu(
            bot_id=bot_id,
            title=title,
            is_start=False,
        )
        session.add(menu)
        await session.commit()

    context.user_data.clear()

    await update.message.reply_text("Menu qo‘shildi ✅")
