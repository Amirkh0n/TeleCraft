from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.bots import Bot
from engine.router import route_update
from core.logger import logger

router = APIRouter()


@router.post("/webhooks/{token}")
async def telegram_webhook(token: str, request: Request):
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
