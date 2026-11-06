from constructor import states
from constructor.handlers import handle_token
from constructor.flows.menus import handle_menu_name
from constructor.flows.buttons import handle_button_text
from constructor.flows.actions import handle_action_text, handle_action_link, handle_admin_id


async def messages(update, context):
    state = context.user_data.get('state')

    if state == states.WAITING_FOR_TOKEN:
        await handle_token(update, context)
    elif state == states.WAITING_FOR_MENU_NAME:
        await handle_menu_name(update, context)
    elif state == states.WAITING_FOR_BUTTON_TEXT:
        await handle_button_text(update, context)
    elif state == states.WAITING_FOR_ACTION_TEXT:
        await handle_action_text(update, context)
    elif state == states.WAITING_FOR_ACTION_LINK:
        await handle_action_link(update, context)
    elif state == states.WAITING_FOR_ADMIN_ID:
        await handle_admin_id(update, context)