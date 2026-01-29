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
    menu = result.scalar_one()

    return ActionType.menu, str(menu.id)


async def handle_button(bot, callback, session):
    button_id = int(callback["data"])

    result = await session.execute(
        select(ButtonAction).where(ButtonAction.button_id == button_id)
    )
    action = result.scalar_one()

    return action.action_type, action.value


async def handle_text(bot, message, session):
    text = message["text"]

    result = await session.execute(
        select(Code).where(Code.bot_id == bot.id, Code.code == text)
    )
    code = result.scalar_one_or_none()

    if code:
        return code.action_type, code.value

    return None, None
