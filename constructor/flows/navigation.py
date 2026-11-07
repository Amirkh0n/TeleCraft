from constructor.flows.bots import show_user_bots
from constructor.flows.menus import show_menus
from constructor.flows.buttons import show_buttons
from constructor.flows.bots import open_bot


async def handle_back(update, context):
    data = update.callback_query.data

    if data == "back_to_bots":
        await show_user_bots(update, context, back=True)

    elif data == "back_to_bot":
        await open_bot(update, context)

    elif data == "back_to_menus":
        await show_menus(update, context)

    elif data == "back_to_buttons":
        await show_buttons(update, context)
