from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from constructor.states import WAITING_FOR_TOKEN
from core.database import AsyncSessionLocal
from models.users import User
from models.bots import Bot


from constructor.flows.bots import show_user_bots


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_user_bots(update, context)



async def add_bot_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    context.user_data["state"] = WAITING_FOR_TOKEN

    await update.callback_query.message.reply_text(
        "BotFather’dan olgan tokenni yuboring:"
    )


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_TOKEN:
        return

    token = update.message.text
    tg_user = update.effective_user

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.tg_id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(tg_id=tg_user.id, full_name=tg_user.full_name)
            session.add(user)
            await session.flush()

        bot = Bot(
            owner_id=user.id,
            name="My Bot",
            token=token,
            is_active=True,
        )
        session.add(bot)
        await session.commit()

    await update.message.reply_text("Bot muvaffaqiyatli qo‘shildi ✅")
    context.user_data.clear()


