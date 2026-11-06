import asyncio
import httpx
from telegram import Bot as TgBot
from sqlalchemy import select, update
from core.database import AsyncSessionLocal
from models.bots import Bot
from core.logger import get_logger

logger = get_logger("webhook_manager")


async def set_webhook(token: str, webhook_url: str) -> bool:
    """Set webhook for a bot"""
    try:
        tg_bot = TgBot(token)
        result = await tg_bot.set_webhook(
            url=webhook_url,
            max_connections=100,
            allowed_updates=['message', 'callback_query']
        )

        if result:
            logger.info(f"Webhook set successfully for bot with token: {token[:20]}...")

            # Save webhook URL to database
            async with AsyncSessionLocal() as session:
                # Get bot ID from token
                result = await session.execute(
                    select(Bot).where(Bot.token == token)
                )
                bot = result.scalar_one_or_none()

                if bot:
                    # Update webhook URL
                    await session.execute(
                        update(Bot)
                        .where(Bot.token == token)
                        .values(webhook_url=webhook_url, webhook_set=True)
                    )
                    await session.commit()
                    logger.info(f"Webhook URL saved to database for bot: {bot.name}")
                else:
                    logger.error(f"Bot not found for token: {token[:20]}...")

            return True
        else:
            logger.error(f"Failed to set webhook for bot with token: {token[:20]}...")
            return False

    except Exception as e:
        logger.error(f"Error setting webhook: {e}", exc_info=True)
        return False


async def delete_webhook(token: str) -> bool:
    """Delete webhook for a bot"""
    try:
        tg_bot = TgBot(token)
        result = await tg_bot.delete_webhook()

        if result:
            logger.info(f"Webhook deleted for bot with token: {token[:20]}...")

            # Update webhook URL in database
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Bot).where(Bot.token == token)
                )
                bot = result.scalar_one_or_none()

                if bot:
                    await session.execute(
                        update(Bot)
                        .where(Bot.token == token)
                        .values(webhook_url=None, webhook_set=False)
                    )
                    await session.commit()

            return True
        else:
            logger.error(f"Failed to delete webhook for bot with token: {token[:20]}...")
            return False

    except Exception as e:
        logger.error(f"Error deleting webhook: {e}", exc_info=True)
        return False


async def get_webhook_status(token: str) -> dict:
    """Get webhook status for a bot"""
    try:
        tg_bot = TgBot(token)
        webhook_info = await tg_bot.get_webhook_info()

        return {
            "has_webhook": bool(webhook_info.url),
            "url": webhook_info.url,
            "pending_update_count": webhook_info.pending_update_count,
            "last_error": webhook_info.last_error_message,
            "custom_emoji_payload": webhook_info.custom_emoji_payload,
            "max_connections": webhook_info.max_connections,
            "allowed_updates": webhook_info.allowed_updates
        }
    except Exception as e:
        logger.error(f"Error getting webhook status: {e}")
        return {
            "error": str(e),
            "has_webhook": False
        }


async def check_all_webhooks() -> list[dict]:
    """Check webhook status for all active bots"""
    results = []

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Bot).where(Bot.is_active == True, Bot.webhook_set == True)
            )
            bots = result.scalars().all()

            for bot in bots:
                status = await get_webhook_status(bot.token)
                results.append({
                    "bot_id": bot.id,
                    "bot_name": bot.name,
                    "token": bot.token[:20] + "...",
                    "webhook_url": bot.webhook_url,
                    "status": status
                })

        return results

    except Exception as e:
        logger.error(f"Error checking all webhooks: {e}", exc_info=True)
        return []


async def verify_webhook(url: str) -> bool:
    """Verify if webhook is accessible"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.head(url)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Error verifying webhook: {e}")
        return False
