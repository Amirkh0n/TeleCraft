from sqlalchemy import select
from models.menus import Menu
from models.button_actions import ButtonAction
from models.codes import Code
from models.user_sessions import UserSession
from models.button_actions import ActionType


async def handle_start(bot, message, session):
    result = await session.execute(
        select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True)
    )
    menu = result.scalar_one_or_none()
    if menu is None or not menu.message_text:
        return ActionType.text, "👋 Bot hozir sozlanmoqda. Tez orada qayta urinib ko‘ring."

    return ActionType.menu, str(menu.id)


async def handle_button(bot, callback, session):
    button_id = int(callback["data"])

    result = await session.execute(
        select(ButtonAction).where(ButtonAction.button_id == button_id)
    )
    action = result.scalar_one_or_none()
    if action is None:
        return None, None

    return action.action_type, action.value


async def handle_text(bot, message, session):
    text = message["text"]
    tg_user_id = message["from"]["id"]

    session_result = await session.execute(
        select(UserSession).where(
            UserSession.bot_id == bot.id,
            UserSession.tg_user_id == tg_user_id,
        )
    )
    user_session = session_result.scalar_one_or_none()
    if user_session and user_session.pending_admin_id:
        return ActionType.admin, f"reply:{user_session.pending_admin_id}:{text}"

    result = await session.execute(
        select(Code).where(Code.bot_id == bot.id, Code.code == text)
    )
    code = result.scalar_one_or_none()

    if code:
        return code.action_type, code.value

    return None, None
