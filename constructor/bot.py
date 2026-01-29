from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from constructor.handlers import start, handle_token, add_bot_click
from constructor.flows.bots import back_to_bots, open_bot
from constructor.flows.menus import show_menus, back_to_bot, add_menu_click, handle_menu_name
from constructor.messages import messages

def run_constructor_bot(token: str):
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_bot_click, pattern="add_bot"))
    app.add_handler(CallbackQueryHandler(show_menus, pattern="menus"))
    app.add_handler(CallbackQueryHandler(add_menu_click, pattern="add_menu"))
    app.add_handler(CallbackQueryHandler(back_to_bots, pattern="back_to_bots"))
    app.add_handler(CallbackQueryHandler(back_to_bot, pattern="back_to_bot"))

    app.add_handler(CallbackQueryHandler(open_bot))
    app.add_handler(MessageHandler(filters.TEXT, messages))

    print("Bot starting...")

    app.run_polling()
