from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from constructor.handlers import (
    start,
    add_bot_click,
    cancel_action,
    edit_start_message,
    resume_draft,
    show_help,
    show_bot_status,
    test_bot,
)
from constructor.flows.bots import open_bot
from constructor.flows.menus import show_menus, add_menu_click, edit_menu_message
from constructor.flows.buttons import show_buttons, add_button_click
from constructor.flows.deletion import delete_menu_confirm, handle_delete_menu, delete_button_confirm, handle_delete_button
from constructor.messages import messages
from constructor.flows.navigation import handle_back
from constructor.flows.actions import choose_action, action_text_click, action_menu_click, select_menu_for_action, action_link_click, action_admin_click


def build_constructor_application(token: str):
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_action))
    app.add_handler(CallbackQueryHandler(add_bot_click, pattern="add_bot"))
    app.add_handler(CallbackQueryHandler(resume_draft, pattern="resume_draft"))
    app.add_handler(CallbackQueryHandler(show_help, pattern="help"))
    app.add_handler(CallbackQueryHandler(edit_start_message, pattern="edit_start_message"))
    app.add_handler(CallbackQueryHandler(show_bot_status, pattern="bot_status"))
    app.add_handler(CallbackQueryHandler(test_bot, pattern="test_bot"))
    app.add_handler(CallbackQueryHandler(show_menus, pattern="menus"))
    app.add_handler(CallbackQueryHandler(add_menu_click, pattern="add_menu"))
    app.add_handler(CallbackQueryHandler(edit_menu_message, pattern="edit_menu_message"))
    app.add_handler(CallbackQueryHandler(delete_menu_confirm, pattern="delete_menu_"))
    app.add_handler(CallbackQueryHandler(handle_delete_menu, pattern="confirm_delete_menu"))
    app.add_handler(CallbackQueryHandler(show_buttons, pattern=r"^menu_\d+$"))
    app.add_handler(CallbackQueryHandler(show_buttons, pattern=r"^start_buttons$"))
    app.add_handler(CallbackQueryHandler(add_button_click, pattern="add_button"))
    app.add_handler(CallbackQueryHandler(delete_button_confirm, pattern="delete_button_"))
    app.add_handler(CallbackQueryHandler(handle_delete_button, pattern="confirm_delete_button"))
    app.add_handler(CallbackQueryHandler(choose_action, pattern=r"^button_\d+$"))
    app.add_handler(CallbackQueryHandler(action_text_click, pattern="action_text"))
    app.add_handler(CallbackQueryHandler(action_menu_click, pattern="action_menu"))
    app.add_handler(CallbackQueryHandler(select_menu_for_action, pattern=r"^select_menu_"))
    app.add_handler(CallbackQueryHandler(action_link_click, pattern="action_link"))
    app.add_handler(CallbackQueryHandler(action_admin_click, pattern="action_admin"))
    app.add_handler(CallbackQueryHandler(handle_back, pattern=r"^back_to_"))
    app.add_handler(CallbackQueryHandler(cancel_action, pattern="cancel"))
    app.add_handler(CallbackQueryHandler(open_bot))
    app.add_handler(MessageHandler(filters.TEXT, messages))
    return app

def run_constructor_bot(token: str):
    app = build_constructor_application(token)
    print("Bot starting...")

    app.run_polling()
