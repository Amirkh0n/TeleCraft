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
from constructor.flows import screens, forms as form_flows, audience as aud, cinema as cin, booking as bkc, quiz as qzc
from constructor.flows.navigation import handle_back
from constructor.flows.actions import choose_action, action_text_click, action_menu_click, select_menu_for_action, action_link_click, action_admin_click


def build_constructor_application(token: str):
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_action))
    # Anchored new-style callbacks go first: the legacy patterns below are unanchored substrings.
    app.add_handler(CallbackQueryHandler(screens.show_settings, pattern=r"^scr:open:\d+$"))
    app.add_handler(CallbackQueryHandler(screens.ask_media, pattern=r"^scr:media:\d+$"))
    app.add_handler(CallbackQueryHandler(screens.toggle, pattern=r"^scr:(mode|cols|nomedia):\d+$"))
    app.add_handler(CallbackQueryHandler(screens.add_share_button, pattern=r"^scr:share:(contact|location):\d+$"))
    app.add_handler(CallbackQueryHandler(screens.action_media_click, pattern=r"^act:media$"))
    app.add_handler(CallbackQueryHandler(form_flows.show_forms, pattern=r"^frm:list$"))
    app.add_handler(CallbackQueryHandler(form_flows.new_form, pattern=r"^frm:new$"))
    app.add_handler(CallbackQueryHandler(form_flows.open_form, pattern=r"^frm:open:\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.add_question, pattern=r"^frm:addq:\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.pick_type, pattern=r"^frm:ft:\w+$"))
    app.add_handler(CallbackQueryHandler(form_flows.set_required, pattern=r"^frm:req:[01]$"))
    app.add_handler(CallbackQueryHandler(form_flows.delete_last_question, pattern=r"^frm:delq:\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.toggle_notify, pattern=r"^frm:notify:\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.edit_text_click, pattern=r"^frm:(intro|final):\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.delete_form, pattern=r"^frm:(del|delok):\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.show_submissions, pattern=r"^frm:(subs|csv):\d+$"))
    app.add_handler(CallbackQueryHandler(form_flows.pick_form_for_button, pattern=r"^act:form$"))
    app.add_handler(CallbackQueryHandler(form_flows.use_form, pattern=r"^frm:use:\d+$"))
    app.add_handler(CallbackQueryHandler(cin.cinema_home, pattern=r"^cin:home$"))
    app.add_handler(CallbackQueryHandler(cin.cinema_toggle, pattern=r"^cin:(on|off)$"))
    app.add_handler(CallbackQueryHandler(bkc.booking_home, pattern=r"^bkc:home$"))
    app.add_handler(CallbackQueryHandler(bkc.booking_toggle, pattern=r"^bkc:(on|off)$"))
    app.add_handler(CallbackQueryHandler(qzc.quiz_home, pattern=r"^qzc:home$"))
    app.add_handler(CallbackQueryHandler(qzc.quiz_toggle, pattern=r"^qzc:(on|off)$"))
    app.add_handler(CallbackQueryHandler(cin.channel_click, pattern=r"^cin:ch$"))
    app.add_handler(CallbackQueryHandler(cin.channel_delete, pattern=r"^cin:chdel$"))
    app.add_handler(CallbackQueryHandler(cin.admins_home, pattern=r"^adm:home$"))
    app.add_handler(CallbackQueryHandler(cin.admin_add_click, pattern=r"^adm:add$"))
    app.add_handler(CallbackQueryHandler(cin.admin_delete, pattern=r"^adm:del:\d+$"))
    app.add_handler(CallbackQueryHandler(aud.show_stats, pattern=r"^aud:home$"))
    app.add_handler(CallbackQueryHandler(aud.show_channels, pattern=r"^sub:home$"))
    app.add_handler(CallbackQueryHandler(aud.add_channel_click, pattern=r"^sub:add$"))
    app.add_handler(CallbackQueryHandler(aud.delete_channel, pattern=r"^sub:del:\d+$"))
    app.add_handler(CallbackQueryHandler(aud.broadcast_home, pattern=r"^bc:home$"))
    app.add_handler(CallbackQueryHandler(aud.new_broadcast, pattern=r"^bc:new$"))
    app.add_handler(CallbackQueryHandler(aud.show_broadcast, pattern=r"^bc:(open|status):\d+$"))
    app.add_handler(CallbackQueryHandler(aud.broadcast_action, pattern=r"^bc:(preview|btn|ask|go|cancel):\d+$"))
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
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.AUDIO | filters.VOICE | filters.Document.ALL,
        screens.handle_media_message,
    ))
    app.add_handler(MessageHandler(filters.TEXT, messages))
    return app

def run_constructor_bot(token: str):
    app = build_constructor_application(token)
    print("Bot starting...")

    app.run_polling()
