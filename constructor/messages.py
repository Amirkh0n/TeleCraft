from constructor import states
from constructor.flows import audience as audience_flows
from constructor.flows import cinema as cinema_flows
from constructor.flows import forms as form_flows
from constructor.handlers import handle_token
from constructor.handlers import handle_start_message
from constructor.flows.menus import handle_menu_name
from constructor.flows.menus import handle_menu_message
from constructor.flows.buttons import handle_button_text
from constructor.flows.actions import handle_action_text, handle_action_link, handle_admin_id


async def messages(update, context):
    state = context.user_data.get('state')

    if state == states.WAITING_FOR_TOKEN:
        await handle_token(update, context)
    elif state == states.WAITING_FOR_START_MESSAGE:
        await handle_start_message(update, context)
    elif state == states.WAITING_FOR_MENU_NAME:
        await handle_menu_name(update, context)
    elif state == states.WAITING_FOR_MENU_MESSAGE:
        await handle_menu_message(update, context)
    elif state == states.WAITING_FOR_BUTTON_TEXT:
        await handle_button_text(update, context)
    elif state == states.WAITING_FOR_ACTION_TEXT:
        await handle_action_text(update, context)
    elif state == states.WAITING_FOR_ACTION_LINK:
        await handle_action_link(update, context)
    elif state == states.WAITING_FOR_ADMIN_ID:
        await handle_admin_id(update, context)
    elif state == states.WAITING_FOR_MOVIE_CHANNEL:
        await cinema_flows.handle_channel_text(update, context)
    elif state == states.WAITING_FOR_BOT_ADMIN:
        await cinema_flows.handle_admin_text(update, context)
    elif state in states.AUDIENCE_STATES:
        await audience_flows.handle_text(update, context)
    elif state in states.FORM_STATES:
        await form_flows.handle_text(update, context)
