from telegram import Bot as TgBot, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from models.menus import Menu
from models.buttons import Button
from models.user_sessions import UserSession
from models.admin_links import AdminLink
from models.button_actions import ActionType

async def execute_action(bot_model, action_type, value, tg_user_id, session, callback_id=None):
    async with TgBot(bot_model.plain_token) as tg_bot:
        if callback_id:
            await tg_bot.answer_callback_query(callback_id)
        if action_type == ActionType.text:
            await tg_bot.send_message(chat_id=tg_user_id, text=value)

        elif action_type == ActionType.link:
            await tg_bot.send_message(
                chat_id=tg_user_id,
                text="Havolani ochish uchun tugmani bosing.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Havolani ochish", url=value)]
                ]),
            )

        elif action_type == ActionType.menu:
            await open_menu(tg_bot, bot_model.id, int(value), tg_user_id, session)

        elif action_type == ActionType.admin:
            if value.startswith("reply:"):
                _, admin_id, message = value.split(":", 2)
                await send_admin_message(tg_bot, bot_model.id, tg_user_id, int(admin_id), message, session)
            else:
                await begin_admin_message(tg_bot, bot_model.id, tg_user_id, int(value), session)


async def open_menu(tg_bot, bot_id, menu_id, tg_user_id, session):
    result = await session.execute(
        select(Menu).where(Menu.id == menu_id, Menu.bot_id == bot_id)
    )
    menu = result.scalar_one_or_none()
    if menu is None:
        await tg_bot.send_message(chat_id=tg_user_id, text="Bu bo‘lim hozir mavjud emas.")
        return

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
        text=menu.message_text or menu.title,
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


async def begin_admin_message(tg_bot, bot_id, tg_user_id, admin_id, session):
    result = await session.execute(
        select(UserSession).where(
            UserSession.bot_id == bot_id,
            UserSession.tg_user_id == tg_user_id,
        )
    )
    user_session = result.scalar_one_or_none()
    if user_session:
        user_session.pending_admin_id = admin_id
        await session.commit()
    await tg_bot.send_message(chat_id=tg_user_id, text="✍️ Xabaringizni yuboring. U adminga yetkaziladi.")


async def send_admin_message(tg_bot, bot_id, tg_user_id, admin_id, message, session):
    await tg_bot.send_message(chat_id=admin_id, text=f"📩 Foydalanuvchi {tg_user_id}:\n\n{message}")
    result = await session.execute(
        select(UserSession).where(
            UserSession.bot_id == bot_id,
            UserSession.tg_user_id == tg_user_id,
        )
    )
    user_session = result.scalar_one_or_none()
    if user_session:
        user_session.pending_admin_id = None
        await session.commit()
    await tg_bot.send_message(chat_id=tg_user_id, text="✅ Xabaringiz adminga yuborildi.")
