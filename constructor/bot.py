from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from constructor.handlers import start, add_bot_click
from constructor.flows.bots import open_bot
from constructor.flows.menus import show_menus, add_menu_click
from constructor.messages import messages
from constructor.flows.buttons import show_buttons, add_button_click
from constructor.flows.navigation import handle_back
from constructor.flows.actions import choose_action, action_text_click, action_menu_click, select_menu_for_action, action_link_click, action_admin_click

def run_constructor_bot(token: str):
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_bot_click, pattern="add_bot"))
    app.add_handler(CallbackQueryHandler(show_menus, pattern="menus"))
    app.add_handler(CallbackQueryHandler(add_menu_click, pattern="add_menu"))
    app.add_handler(CallbackQueryHandler(show_buttons, pattern=r"^menu_\d+$"))
    app.add_handler(CallbackQueryHandler(add_button_click, pattern="add_button"))
    app.add_handler(CallbackQueryHandler(choose_action, pattern=r"^button_\d+$"))
    app.add_handler(CallbackQueryHandler(action_text_click, pattern="action_text"))
    app.add_handler(CallbackQueryHandler(action_menu_click, pattern="action_menu"))
    app.add_handler(CallbackQueryHandler(select_menu_for_action, pattern=r"^select_menu_"))
    app.add_handler(CallbackQueryHandler(action_link_click, pattern="action_link"))
    app.add_handler(CallbackQueryHandler(action_admin_click, pattern="action_admin"))

    app.add_handler(CallbackQueryHandler(handle_back, pattern=r"^back_to_"))

    app.add_handler(CallbackQueryHandler(open_bot))
    app.add_handler(MessageHandler(filters.TEXT, messages))

    print("Bot starting...")

    app.run_polling()
