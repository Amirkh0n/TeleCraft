from constructor import states
from constructor.handlers import handle_token
from constructor.flows.menus import handle_menu_name


async def messages(update, context):
    state = context.user_data['state']

    if state == states.WAITING_FOR_TOKEN:
        await handle_token(update, context)
    elif state == states.WAITING_FOR_MENU_NAME:
        await handle_menu_name(update, context)