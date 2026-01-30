from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.users import User
from models.bots import Bot


async def show_user_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, back=False):
    tg_user = update.effective_user

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.tg_id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text("Sizda hali botlar yo‘q.")
            return

        result = await session.execute(
            select(Bot).where(Bot.owner_id == user.id)
        )
        bots = result.scalars().all()

    keyboard = []

    for bot in bots:
        keyboard.append(
            [InlineKeyboardButton(bot.name, callback_data=f"bot_{bot.id}")]
        )

    keyboard.append(
        [InlineKeyboardButton("➕ Bot qo‘shish", callback_data="add_bot")]
    )

    if back:
        await update.callback_query.edit_message_text(
            "Sizning botlaringiz:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    await update.message.reply_text(
        "Sizning botlaringiz:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def open_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    data = update.callback_query.data
    try:
        bot_id = int(data.split("_")[1])
    except:
        bot_id = context.user_data.get("current_bot_id")

    # botni contextda saqlaymiz
    context.user_data["current_bot_id"] = bot_id

    keyboard = [
        [InlineKeyboardButton("📁 Menular", callback_data="menus")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_bots")],
    ]

    await update.callback_query.message.edit_text(
        "Bot boshqaruvi:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def back_to_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await show_user_bots(update, context, back=True)