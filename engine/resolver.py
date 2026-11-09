"""Decide WHAT an incoming update means (an action), without sending anything."""
from sqlalchemy import select

from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.codes import Code
from models.menus import Menu


async def handle_start(bot, message, session):
    result = await session.execute(select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True))  # noqa: E712
    menu = result.scalar_one_or_none()
    if menu is None or not (menu.message_text or menu.media_file_id):
        return ActionType.text, "👋 Bot hozir sozlanmoqda. Tez orada qayta urinib ko‘ring."

    return ActionType.menu, str(menu.id)


async def _action_for_button(session, bot_id, button_id):
    """The action of a button, but only if the button belongs to this bot."""
    result = await session.execute(
        select(ButtonAction)
        .join(Button, Button.id == ButtonAction.button_id)
        .join(Menu, Menu.id == Button.menu_id)
        .where(ButtonAction.button_id == button_id, Menu.bot_id == bot_id)
    )
    action = result.scalar_one_or_none()
    return (action.action_type, action.value) if action else (None, None)


async def handle_button(bot, callback, session):
    try:
        button_id = int(callback.get("data", ""))
    except (TypeError, ValueError):
        return None, None
    return await _action_for_button(session, bot.id, button_id)


async def _reply_button_action(session, bot_id, menu_id, text):
    """Action of the reply-keyboard button labelled ``text`` on a menu (None if no such button)."""
    result = await session.execute(
        select(Button.id)
        .join(Menu, Menu.id == Button.menu_id)
        .where(
            Menu.id == menu_id, Menu.bot_id == bot_id, Menu.keyboard_mode == "reply",
            Button.text == text, Button.kind == "normal",
        )
        .order_by(Button.position, Button.id)
    )
    button_id = result.scalars().first()
    if button_id is None:
        return None, None
    return await _action_for_button(session, bot_id, button_id)


async def handle_text(bot, message, session, user_session=None):
    text = message["text"]

    if user_session and user_session.pending_admin_id:
        return ActionType.admin, f"reply:{user_session.pending_admin_id}:{text}"

    # Reply-keyboard button of the menu the user is on.
    if user_session:
        found = await _reply_button_action(session, bot.id, user_session.current_menu_id, text)
        if found[0]:
            return found

    result = await session.execute(select(Code).where(Code.bot_id == bot.id, Code.code == text))
    code = result.scalars().first()
    if code:
        return code.action_type, code.value

    return None, None


async def find_share_button(bot, user_session, kind, session):
    """The "share contact"/"share location" button on the user's current reply menu, if any,
    as ``(action_type, value)`` of the button's own action (``(None, None)`` if it has none)."""
    if not user_session:
        return None, None
    result = await session.execute(
        select(Button.id)
        .join(Menu, Menu.id == Button.menu_id)
        .where(Menu.id == user_session.current_menu_id, Menu.bot_id == bot.id, Button.kind == kind)
        .order_by(Button.position, Button.id)
    )
    button_id = result.scalars().first()
    if button_id is None:
        return None, None
    return await _action_for_button(session, bot.id, button_id)


async def has_share_button(bot, user_session, kind, session) -> bool:
    if not user_session:
        return False
    result = await session.execute(
        select(Button.id)
        .join(Menu, Menu.id == Button.menu_id)
        .where(Menu.id == user_session.current_menu_id, Menu.bot_id == bot.id, Button.kind == kind)
    )
    return result.scalars().first() is not None
