from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.logger import get_logger
from engine.forms import start_form
from engine.render import parse_media_value, send_media, send_screen, send_text
from models.admin_links import AdminLink
from models.button_actions import ActionType
from models.buttons import Button
from models.menus import Menu
from models.user_sessions import UserSession

logger = get_logger("actions")


async def get_user_session(session, bot_id, tg_user_id):
    result = await session.execute(
        select(UserSession).where(UserSession.bot_id == bot_id, UserSession.tg_user_id == tg_user_id)
    )
    return result.scalar_one_or_none()


async def execute_action(bot_model, action_type, value, tg_user_id, session, *, tg, user_session=None):
    """Run what a button / code / start command asked for. ``tg`` is the child bot's client."""
    chat_id = tg_user_id  # private chats: chat id == user id

    if action_type == ActionType.text:
        await send_text(tg, chat_id, value)

    elif action_type == ActionType.link:
        await tg.send_message(
            chat_id=chat_id,
            text="Havolani ochish uchun tugmani bosing.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Havolani ochish", url=value)]]),
        )

    elif action_type == ActionType.menu:
        await open_menu(tg, bot_model.id, int(value), chat_id, session)

    elif action_type == ActionType.admin:
        if value.startswith("reply:"):
            _, admin_id, message = value.split(":", 2)
            await send_admin_message(tg, bot_model.id, tg_user_id, int(admin_id), message, session)
        else:
            await begin_admin_message(tg, bot_model.id, tg_user_id, int(value), session)

    elif action_type == ActionType.media:
        media = parse_media_value(value)
        if media is None:
            logger.warning("Bot %s has a media action with an invalid value", bot_model.id)
            await send_text(tg, chat_id, "Bu fayl hozir mavjud emas.")
        elif not await send_media(tg, chat_id, media["type"], media["file_id"], caption=media.get("caption")):
            await send_text(tg, chat_id, "Faylni yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")

    elif action_type == ActionType.form:
        if user_session is None:
            user_session = await get_user_session(session, bot_model.id, tg_user_id)
        if user_session is None:  # cannot happen through the normal flow: forms start from a menu
            await send_text(tg, chat_id, "Avval /start yuboring.")
            return
        await start_form(tg, bot_model, int(value), chat_id, user_session, session)

    else:
        logger.info("Action type %s is not supported by the runtime", action_type)


async def open_menu(tg, bot_id, menu_id, chat_id, session):
    result = await session.execute(select(Menu).where(Menu.id == menu_id, Menu.bot_id == bot_id))
    menu = result.scalar_one_or_none()
    if menu is None:
        await send_text(tg, chat_id, "Bu bo‘lim hozir mavjud emas.")
        return

    result = await session.execute(
        select(Button).where(Button.menu_id == menu.id).order_by(Button.position, Button.id)
    )
    buttons = result.scalars().all()

    user_session = await save_session(bot_id, chat_id, menu_id, session)
    await send_screen(tg, chat_id, menu, buttons, user_session)
    await session.commit()  # persists reply_keyboard_active as well


async def save_session(bot_id, tg_user_id, menu_id, session) -> UserSession:
    """Remember which menu the user is on (creating the session if needed)."""
    existing = await get_user_session(session, bot_id, tg_user_id)
    if existing:
        existing.current_menu_id = menu_id
        user_session = existing
    else:
        user_session = UserSession(bot_id=bot_id, tg_user_id=tg_user_id, current_menu_id=menu_id)
        session.add(user_session)
    await session.commit()
    return user_session


async def send_to_admins(tg, bot_id, tg_user_id, text, session):
    result = await session.execute(select(AdminLink).where(AdminLink.bot_id == bot_id))
    for admin in result.scalars().all():
        await tg.send_message(chat_id=admin.admin_tg_id, text=f"User {tg_user_id}:\n{text}")


async def begin_admin_message(tg, bot_id, tg_user_id, admin_id, session):
    user_session = await get_user_session(session, bot_id, tg_user_id)
    if user_session:
        user_session.pending_admin_id = admin_id
        await session.commit()
    await send_text(tg, tg_user_id, "✍️ Xabaringizni yuboring. U adminga yetkaziladi.")


async def send_admin_message(tg, bot_id, tg_user_id, admin_id, message, session):
    await tg.send_message(chat_id=admin_id, text=f"📩 Foydalanuvchi {tg_user_id}:\n\n{message}")
    user_session = await get_user_session(session, bot_id, tg_user_id)
    if user_session:
        user_session.pending_admin_id = None
        await session.commit()
    await send_text(tg, tg_user_id, "✅ Xabaringiz adminga yuborildi.")
