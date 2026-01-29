from telegram import Bot as TgBot, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from models.menus import Menu
from models.buttons import Button
from models.user_sessions import UserSession
from models.admin_links import AdminLink
from models.button_actions import ActionType

async def execute_action(bot_model, action_type, value, tg_user_id, session):
    tg_bot = TgBot(bot_model.token)

    if action_type == ActionType.text:
        await tg_bot.send_message(chat_id=tg_user_id, text=value)

    elif action_type == ActionType.link:
        await tg_bot.send_message(chat_id=tg_user_id, text=value)

    elif action_type == ActionType.menu:
        await open_menu(tg_bot, bot_model.id, int(value), tg_user_id, session)

    elif action_type == ActionType.admin:
        await send_to_admins(tg_bot, bot_model.id, tg_user_id, value, session)


async def open_menu(tg_bot, bot_id, menu_id, tg_user_id, session):
    result = await session.execute(
        select(Menu).where(Menu.id == menu_id)
    )
    menu = result.scalar_one()

    result = await session.execute(
        select(Button).where(Button.menu_id == menu.id).order_by(Button.position)
    )
    buttons = result.scalars().all()

    keyboard = [
        [InlineKeyboardButton(b.text, callback_data=str(b.id))]
        for b in buttons
    ]

    await tg_bot.send_message(
        chat_id=tg_user_id,
        text=menu.title,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # SESSION shu yerda yangilanadi (to‘g‘ri joy)
    await save_session(bot_id, tg_user_id, menu_id, session)


async def save_session(bot_id, tg_user_id, menu_id, session):
    result = await session.execute(
        select(UserSession).where(
            UserSession.bot_id == bot_id,
            UserSession.tg_user_id == tg_user_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.current_menu_id = menu_id
    else:
        session.add(
            UserSession(
                bot_id=bot_id,
                tg_user_id=tg_user_id,
                current_menu_id=menu_id,
            )
        )

    await session.commit()


async def send_to_admins(tg_bot, bot_id, tg_user_id, text, session):
    result = await session.execute(
        select(AdminLink).where(AdminLink.bot_id == bot_id)
    )
    admins = result.scalars().all()

    for admin in admins:
        await tg_bot.send_message(
            chat_id=admin.admin_tg_id,
            text=f"User {tg_user_id}:\n{text}"
        )
