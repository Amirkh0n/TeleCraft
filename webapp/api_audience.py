"""Mini App API: broadcasts and required channels."""
import re

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import TelegramError

from engine import broadcast as broadcast_engine
from engine import subscription
from engine.telegram_client import get_client
from models.audience import BROADCAST_DRAFT, RequiredChannel, Broadcast
from models.bots import Bot
from models.users import User
from webapp.api import _check_text, _upload_to_child, not_found, owned_bot
from webapp.auth import current_user, get_session

router = APIRouter(prefix="/api/v1", tags=["miniapp"])

MAX_CHANNELS = 5
SHOWN = 15


class BroadcastIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    button_text: str | None = Field(default=None, max_length=64)
    button_url: str | None = Field(default=None, max_length=512)


class ChannelIn(BaseModel):
    ref: str = Field(min_length=2, max_length=120)
    invite_link: str | None = Field(default=None, max_length=200)


def broadcast_out(b: Broadcast, audience: int | None = None) -> dict:
    out = {
        "id": b.id, "status": b.status, "text": b.text, "media_type": b.media_type if b.media_file_id else None,
        "button_text": b.button_text, "button_url": b.button_url, "total": b.total, "sent": b.sent,
        "failed": b.failed, "blocked": b.blocked,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
    }
    if audience is not None:
        out["audience"] = audience
    return out


async def owned_broadcast(session: AsyncSession, user: User, broadcast_id: int):
    row = (await session.execute(
        select(Broadcast, Bot).join(Bot, Bot.id == Broadcast.bot_id)
        .where(Broadcast.id == broadcast_id, Bot.owner_id == user.id)
    )).first()
    if row is None:
        raise not_found("Xabar")
    return row[0], row[1]


def _apply(b: Broadcast, body: BroadcastIn) -> None:
    fields = body.model_fields_set
    if "text" in fields:
        b.text = _check_text(body.text, "Xabar matni")
    if fields & {"button_text", "button_url"}:
        label = (body.button_text or "").strip()
        url = (body.button_url or "").strip()
        if label or url:
            if not label or not url:
                raise HTTPException(status_code=422, detail="Tugma uchun yozuv ham, havola ham kerak.")
            if not re.fullmatch(r"https?://[^\s/$.?#][^\s]{0,500}", url):
                raise HTTPException(status_code=422, detail="Havola https:// bilan boshlanishi kerak.")
        b.button_text, b.button_url = label or None, url or None


# ---------------------------------------------------------------- broadcasts

@router.get("/bots/{bot_id}/broadcasts")
async def list_broadcasts(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    rows = (await session.execute(
        select(Broadcast).where(Broadcast.bot_id == bot.id).order_by(Broadcast.id.desc()).limit(SHOWN)
    )).scalars().all()
    return {"audience": await broadcast_engine.audience_size(session, bot.id), "items": [broadcast_out(b) for b in rows]}


@router.post("/bots/{bot_id}/broadcasts", status_code=201)
async def create_broadcast(bot_id: int, body: BroadcastIn, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    b = Broadcast(bot_id=bot.id, created_by=user.tg_id, status=BROADCAST_DRAFT)
    _apply(b, body)
    session.add(b)
    await session.commit()
    return broadcast_out(b, await broadcast_engine.audience_size(session, bot.id))


@router.get("/broadcasts/{broadcast_id}")
async def get_broadcast(broadcast_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    await session.refresh(b)
    return broadcast_out(b, await broadcast_engine.audience_size(session, bot.id))


@router.patch("/broadcasts/{broadcast_id}")
async def edit_broadcast(broadcast_id: int, body: BroadcastIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    if b.status != BROADCAST_DRAFT:
        raise HTTPException(status_code=409, detail="Yuborilgan xabarni o‘zgartirib bo‘lmaydi.")
    _apply(b, body)
    await session.commit()
    return broadcast_out(b, await broadcast_engine.audience_size(session, bot.id))


@router.post("/broadcasts/{broadcast_id}/media")
async def broadcast_media(broadcast_id: int, file: UploadFile = File(...), user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    if b.status != BROADCAST_DRAFT:
        raise HTTPException(status_code=409, detail="Yuborilgan xabarni o‘zgartirib bo‘lmaydi.")
    b.media_type, b.media_file_id = await _upload_to_child(bot, user, file)
    await session.commit()
    return broadcast_out(b, await broadcast_engine.audience_size(session, bot.id))


@router.delete("/broadcasts/{broadcast_id}/media")
async def remove_broadcast_media(broadcast_id: int, user: User = Depends(current_user),
                                 session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    if b.status != BROADCAST_DRAFT:
        raise HTTPException(status_code=409, detail="Yuborilgan xabarni o‘zgartirib bo‘lmaydi.")
    b.media_type = b.media_file_id = None
    await session.commit()
    return broadcast_out(b, await broadcast_engine.audience_size(session, bot.id))


@router.post("/broadcasts/{broadcast_id}/preview", status_code=204)
async def preview_broadcast(broadcast_id: int, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    hint = "Avval child botni oching va /start yuboring, keyin qayta urining."
    try:
        ok = await broadcast_engine.deliver(await get_client(bot.plain_token), user.tg_id, b)
    except TelegramError:
        raise HTTPException(status_code=409, detail=hint) from None
    if not ok:
        raise HTTPException(status_code=422, detail="Xabar bo‘sh yoki Telegram uni qabul qilmadi.")
    return Response(status_code=204)


@router.post("/broadcasts/{broadcast_id}/send")
async def send_broadcast(broadcast_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, bot = await owned_broadcast(session, user, broadcast_id)
    if not await broadcast_engine.audience_size(session, bot.id):
        raise HTTPException(status_code=409, detail="Hozircha xabar yuboriladigan foydalanuvchi yo‘q.")
    result = await broadcast_engine.start(session, b.id)
    if result == "busy":
        raise HTTPException(status_code=409, detail="Boshqa xabar hali yuborilmoqda. Tugashini kuting.")
    if result == "invalid":
        raise HTTPException(status_code=409, detail="Bu xabarni yuborib bo‘lmaydi (bo‘sh yoki allaqachon yuborilgan).")
    await session.refresh(b)
    return broadcast_out(b)


@router.post("/broadcasts/{broadcast_id}/cancel")
async def cancel_broadcast(broadcast_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, _bot = await owned_broadcast(session, user, broadcast_id)
    await broadcast_engine.cancel(session, b.id)
    await session.refresh(b)
    return broadcast_out(b)


# ---------------------------------------------------------------- required channels

def _channel_out(c: RequiredChannel) -> dict:
    return {"id": c.id, "title": c.title, "username": c.username, "private": not c.username}


@router.get("/bots/{bot_id}/channels")
async def list_channels(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    return [_channel_out(c) for c in await subscription.channels_of(session, bot.id)]


@router.post("/bots/{bot_id}/channels", status_code=201)
async def add_channel(bot_id: int, body: ChannelIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    from constructor.flows.audience import normalize_channel_ref
    bot = await owned_bot(session, user, bot_id)
    ref = normalize_channel_ref(body.ref)
    if ref is None:
        raise HTTPException(status_code=422, detail="Manzil noto‘g‘ri. Masalan: @kanal_nomi")
    existing = await subscription.channels_of(session, bot.id)
    if len(existing) >= MAX_CHANNELS:
        raise HTTPException(status_code=409, detail=f"{MAX_CHANNELS} tadan ko‘p kanal qo‘shib bo‘lmaydi.")
    chat_id, title, username, problem = await subscription.describe_channel(await get_client(bot.plain_token), ref)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if any(c.chat_id == chat_id for c in existing):
        raise HTTPException(status_code=409, detail="Bu kanal allaqachon qo‘shilgan.")
    invite = (body.invite_link or "").strip() or None
    if not username:
        if not invite or not re.fullmatch(r"https://t\.me/(\+|joinchat/)[\w-]+", invite):
            raise HTTPException(status_code=422, detail="Yopiq kanal uchun taklif havolasi kerak (https://t.me/+…).")
    else:
        invite = None
    channel = RequiredChannel(bot_id=bot.id, chat_id=chat_id, title=(title or str(chat_id))[:255], username=username,
                              invite_link=invite, position=len(existing))
    session.add(channel)
    await session.commit()
    return _channel_out(channel)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(RequiredChannel).join(Bot, Bot.id == RequiredChannel.bot_id)
        .where(RequiredChannel.id == channel_id, Bot.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Kanal")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)
