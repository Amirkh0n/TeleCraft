from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
from sqlalchemy import select
from constructor.handlers import start, add_bot_click, cancel_action
from constructor.flows.bots import open_bot, back_to_bots
from constructor.flows.menus import show_menus, add_menu_click
from constructor.flows.buttons import show_buttons, add_button_click
from constructor.flows.deletion import delete_menu_confirm, handle_delete_menu, delete_button_confirm, handle_delete_button
from constructor.messages import messages
from constructor.flows.navigation import handle_back
from constructor.flows.actions import choose_action, action_text_click, action_menu_click, select_menu_for_action, action_link_click, action_admin_click
from constructor import states
from core.database import AsyncSessionLocal
from models.bots import Bot
from core.logger import logger
from core.config import settings


def build_constructor_application(token: str):
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_bot_click, pattern="add_bot"))
    app.add_handler(CallbackQueryHandler(show_menus, pattern="menus"))
    app.add_handler(CallbackQueryHandler(add_menu_click, pattern="add_menu"))
    app.add_handler(CallbackQueryHandler(delete_menu_confirm, pattern="delete_menu_"))
    app.add_handler(CallbackQueryHandler(handle_delete_menu, pattern="confirm_delete_menu"))
    app.add_handler(CallbackQueryHandler(show_buttons, pattern=r"^menu_\d+$"))
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


async def ensure_constructor_bot_in_db(token: str):
    """Constructor botni bazaga saqlaydi agar bo'lmasa"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(Bot.token == token)
        )
        bot = result.scalar_one_or_none()

        if not bot:
            logger.info("Constructor bot bazaga qo'silyapti...")
            from core.webhook_manager import setup_webhook
            webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhook"

            constructor_bot = Bot(
                owner_id=1,  # Admin ID
                name="Constructor Bot",
                token=token,
                is_active=True,
                webhook_url=webhook_url,
                webhook_set=True
            )
            session.add(constructor_bot)
            await session.commit()

            # Webhookni o'rnatish
            await setup_webhook(constructor_bot)
            logger.info("Constructor bot bazaga saqlandi va webhook o'rnatildi")


def run_constructor_bot(token: str):
    app = build_constructor_application(token)
    print("Bot starting...")

    app.run_polling()
