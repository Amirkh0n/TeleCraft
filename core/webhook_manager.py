import asyncio
import httpx
from telegram import Bot as TgBot
from sqlalchemy import select, update
from core.database import AsyncSessionLocal
from models.bots import Bot
from core.config import settings
from core.logger import get_logger
from core.security import token_hash, webhook_secret

logger = get_logger("webhook_manager")


def build_webhook_url(token: str) -> str:
    """Public webhook URL for a child bot. Uses the token hash, never the token itself."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/h/{token_hash(token)}"


# poll_answer is needed by quiz bots (non-anonymous polls report who voted for what)
ALLOWED_UPDATES = ('message', 'callback_query', 'my_chat_member', 'poll_answer')


async def set_webhook(token: str, webhook_url: str) -> bool:
    """Set webhook for a bot"""
    try:
        async with TgBot(token) as tg_bot:
            result = await tg_bot.set_webhook(
                url=webhook_url,
                max_connections=100,
                allowed_updates=list(ALLOWED_UPDATES),
                secret_token=webhook_secret(token),
            )

        if result:
            logger.info("Webhook set successfully for bot with token hash %s", token_hash(token)[:8])

            # Save webhook URL to database
            async with AsyncSessionLocal() as session:
                # Get bot ID from token
                result = await session.execute(
                    select(Bot).where(Bot.token_matches(token))
                )
                bot = result.scalar_one_or_none()

                if bot:
                    # Update webhook URL
                    await session.execute(
                        update(Bot)
                        .where(Bot.token_matches(token))
                        .values(webhook_url=webhook_url, webhook_set=True)
                    )
                    await session.commit()
                    logger.info(f"Webhook URL saved to database for bot: {bot.name}")
                else:
                    logger.error("Bot not found for token hash %s", token_hash(token)[:8])

            return True
        else:
            logger.error("Failed to set webhook for token hash %s", token_hash(token)[:8])
            return False

    except Exception as e:
        logger.error("Error setting webhook: %s", type(e).__name__)
        return False


async def delete_webhook(token: str) -> bool:
    """Delete webhook for a bot"""
    try:
        async with TgBot(token) as tg_bot:
            result = await tg_bot.delete_webhook()

        if result:
            logger.info("Webhook deleted for token hash %s", token_hash(token)[:8])

            # Update webhook URL in database
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Bot).where(Bot.token_matches(token))
                )
                bot = result.scalar_one_or_none()

                if bot:
                    await session.execute(
                        update(Bot)
                        .where(Bot.token_matches(token))
                        .values(webhook_url=None, webhook_set=False)
                    )
                    await session.commit()

            return True
        else:
            logger.error("Failed to delete webhook for token hash %s", token_hash(token)[:8])
            return False

    except Exception as e:
        logger.error(f"Error deleting webhook: {e}", exc_info=True)
        return False


async def get_webhook_status(token: str) -> dict:
    """Get webhook status for a bot"""
    try:
        async with TgBot(token) as tg_bot:
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
                status = await get_webhook_status(bot.plain_token)
                results.append({
                    "bot_id": bot.id,
                    "bot_name": bot.name,
                    "token_hash": (bot.token_hash or "")[:8],
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


async def refresh_webhooks() -> int:
    """Re-register webhooks of all active child bots (new URL format + secret header)."""
    if "your-app" in settings.PUBLIC_BASE_URL:
        logger.warning("PUBLIC_BASE_URL is not configured; skipping webhook refresh")
        return 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Bot).where(Bot.is_active == True))
        tokens = [bot.plain_token for bot in result.scalars().all()]

    refreshed = 0
    for token in tokens:
        if await set_webhook(token, build_webhook_url(token)):
            refreshed += 1
        await asyncio.sleep(0.2)
    logger.info("Webhooks refreshed: %s/%s", refreshed, len(tokens))
    return refreshed
