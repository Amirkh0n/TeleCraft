"""Telegram Mini App authentication.

The Mini App sends ``Authorization: tma <initData>``. ``initData`` is signed by Telegram with a
key derived from the constructor bot's token, so the server can trust the user id inside it
without sessions or passwords.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from models.users import User

MAX_AGE_SECONDS = 24 * 3600
CLOCK_SKEW_SECONDS = 300


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SECONDS, now: float | None = None) -> dict:
    """Return the Telegram user (``{"id": ..., "first_name": ...}``) or raise ``AuthError``."""
    if not init_data or len(init_data) > 8192:
        raise AuthError("missing init data")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise AuthError("no hash")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthError("bad signature")
    try:
        issued = int(pairs["auth_date"])
        user = json.loads(pairs["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("malformed init data") from None
    current = time.time() if now is None else now
    if current - issued > max_age or issued - current > CLOCK_SKEW_SECONDS:
        raise AuthError("expired")
    user["id"] = user_id
    return user


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    scheme, _, payload = (authorization or "").partition(" ")
    if scheme.lower() != "tma" or not payload:
        raise HTTPException(status_code=401, detail="Telegram orqali oching.")
    try:
        tg_user = validate_init_data(payload, settings.TELEGRAM_TOKEN)
    except AuthError:
        raise HTTPException(status_code=401, detail="Sessiya eskirgan. Muharrirni qayta oching.") from None

    full_name = " ".join(p for p in (tg_user.get("first_name"), tg_user.get("last_name")) if p) or None
    user = (await session.execute(select(User).where(User.tg_id == tg_user["id"]))).scalar_one_or_none()
    if user is None:
        user = User(tg_id=tg_user["id"], full_name=full_name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user
