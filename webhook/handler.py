from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.bots import Bot
from engine.router import route_update
from core.logger import logger
from core.config import settings
from core.security import secrets_match, webhook_secret

router = APIRouter()

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _check_secret(request: Request, bot: Bot) -> None:
    """Verify Telegram's secret header. Missing header is tolerated until enforcement is on."""
    received = request.headers.get(SECRET_HEADER)
    if received is None:
        if settings.WEBHOOK_SECRET_ENFORCE:
            raise HTTPException(status_code=403, detail="Forbidden")
        logger.warning("Webhook for bot_id=%s arrived without secret header", bot.id)
        return
    if not secrets_match(received, webhook_secret(bot.plain_token)):
        raise HTTPException(status_code=403, detail="Forbidden")


async def _process_child_webhook(bot_filter, request: Request):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(bot_filter, Bot.is_active == True)
        )
        bot = result.scalar_one_or_none()

        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        _check_secret(request, bot)
        update = await request.json()
        await route_update(bot, update, session)

    return {"ok": True}


@router.post("/h/{public_id}")
async def child_webhook(public_id: str, request: Request):
    """Child bot webhook. ``public_id`` is the bot's token hash, so the token never appears in a URL."""
    return await _process_child_webhook(Bot.token_hash == public_id, request)


@router.post("/webhooks/{token}")
async def telegram_webhook(token: str, request: Request):
    """Legacy child bot endpoint (token in URL). Kept until webhooks are re-registered."""
    return await _process_child_webhook(Bot.token_matches(token), request)


@router.post("/webhook/{token}")
async def legacy_webhook(token: str, request: Request):
    """Compatibility endpoint for webhooks configured before the URL rename."""
    if token == settings.TELEGRAM_TOKEN:
        from app.main import constructor_application
        from telegram import Update

        payload = await request.json()
        logger.info("Main bot legacy webhook received: update_id=%s", payload.get("update_id"))
        update = Update.de_json(payload, constructor_application.bot)
        await constructor_application.process_update(update)
        return {"ok": True}

    return await _process_child_webhook(Bot.token_matches(token), request)
