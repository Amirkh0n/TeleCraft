from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.database import AsyncSessionLocal
from constructor.states import WAITING_FOR_BUTTON_TEXT
from models.buttons import Button


async def show_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    data = update.callback_query.data
    menu_id = int(data.split("_")[1])

    # current menu ni saqlaymiz
    context.user_data["current_menu_id"] = menu_id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Button).where(Button.menu_id == menu_id)
        )
        buttons = result.scalars().all()

    keyboard = []

    for btn in buttons:
        keyboard.append(
            [InlineKeyboardButton(btn.text, callback_data=f"button_{btn.id}")]
        )

    keyboard.append(
        [InlineKeyboardButton("➕ Tugma qo‘shish", callback_data="add_button")]
    )
    keyboard.append(
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_menus")]
    )

    await update.callback_query.message.edit_text(
        "Tugmalar ro‘yxati:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def add_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_BUTTON_TEXT

    await update.callback_query.message.reply_text(
        "Tugma nomini yuboring:"
    )


async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_BUTTON_TEXT:
        return

    text = update.message.text
    menu_id = context.user_data.get("current_menu_id")

    async with AsyncSessionLocal() as session:
        button = Button(
            menu_id=menu_id,
            text=text,
            position=1,
        )
        session.add(button)
        await session.commit()

    context.user_data.clear()

    await update.message.reply_text("Tugma qo‘shildi ✅")
