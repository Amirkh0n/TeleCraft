from engine.resolver import (
    handle_start,
    handle_button,
    handle_text,
)
from engine.actions import execute_action


async def route_update(bot, update, session):
    message = update.get("message")
    callback = update.get("callback_query")

    action_type = None
    value = None
    tg_user_id = None

    # /start
    if message and message.get("text") == "/start":
        tg_user_id = message["from"]["id"]
        action_type, value = await handle_start(bot, message, session)

    # button
    elif callback:
        tg_user_id = callback["from"]["id"]
        action_type, value = await handle_button(bot, callback, session)

    # text (code)
    elif message and message.get("text"):
        tg_user_id = message["from"]["id"]
        action_type, value = await handle_text(bot, message, session)

    if action_type:
        await execute_action(
            bot,
            action_type,
            value,
            tg_user_id,
            session,
            callback_id=callback.get("id") if callback else None,
        )
    elif message and message.get("text"):
        from telegram import Bot as TgBot

        async with TgBot(bot.plain_token) as telegram_bot:
            await telegram_bot.send_message(
                chat_id=message["from"]["id"],
                text="Kerakli bo‘limni menyudagi tugmalardan tanlang.",
            )
