from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.bots import Bot
from engine.router import route_update
from core.logger import logger
from core.config import settings

router = APIRouter()


async def _process_child_webhook(token: str, request: Request):
    update = await request.json()

    # Avval bazadan qidirib ko'ramiz
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Bot).where(Bot.token == token, Bot.is_active == True)
        )
        bot = result.scalar_one_or_none()

        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        # 🔥 Engine chaqiriladi
        await route_update(bot, update, session)

    return {"ok": True}


@router.post("/webhooks/{token}")
async def telegram_webhook(token: str, request: Request):
    """Child bot webhook endpoint."""
    return await _process_child_webhook(token, request)


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

    return await _process_child_webhook(token, request)
