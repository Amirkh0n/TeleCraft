"""Helpers for preserving a constructor user's place in the builder."""

from sqlalchemy import select
from telegram.ext import ContextTypes

from core.database import AsyncSessionLocal
from models.constructor_sessions import ConstructorSession
from models.users import User


async def ensure_constructor_user(tg_id: int, full_name: str | None) -> User:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(tg_id=tg_id, full_name=full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        elif full_name and user.full_name != full_name:
            user.full_name = full_name
            await session.commit()
        return user


async def load_builder_session(user_id: int) -> ConstructorSession:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConstructorSession).where(ConstructorSession.user_id == user_id)
        )
        builder_session = result.scalar_one_or_none()
        if builder_session is None:
            builder_session = ConstructorSession(user_id=user_id, draft={})
            session.add(builder_session)
            await session.commit()
            await session.refresh(builder_session)
        return builder_session


async def save_builder_session(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    current_bot_id: int | None = None,
    current_menu_id: int | None = None,
    current_button_id: int | None = None,
    pending_state: str | None = None,
    draft: dict | None = None,
    keep_selection: bool = True,
) -> None:
    """Synchronize navigation state in PTB memory and the database."""
    if not keep_selection:
        context.user_data.pop("current_bot_id", None)
        context.user_data.pop("current_menu_id", None)
        context.user_data.pop("current_button_id", None)

    values = {
        "current_bot_id": current_bot_id,
        "current_menu_id": current_menu_id,
        "current_button_id": current_button_id,
    }
    if pending_state is not None:
        values["state"] = pending_state
    if draft is not None:
        values["draft"] = draft
    for key, value in values.items():
        if value is None or (key == "state" and value == "") or (key == "draft" and value == {}):
            if key in {"state", "draft"}:
                context.user_data.pop(key, None)
            elif key == "draft":
                context.user_data.pop(key, None)
            continue
        context.user_data[key] = value

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConstructorSession).where(ConstructorSession.user_id == user_id)
        )
        builder_session = result.scalar_one_or_none()
        if builder_session is None:
            builder_session = ConstructorSession(user_id=user_id, draft={})
            session.add(builder_session)

        for field, value in (
            ("current_bot_id", current_bot_id),
            ("current_menu_id", current_menu_id),
            ("current_button_id", current_button_id),
            ("pending_state", pending_state),
        ):
            if value is not None or not keep_selection:
                setattr(builder_session, field, value)
        if draft is not None:
            builder_session.draft = draft
        await session.commit()


async def restore_builder_session(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> ConstructorSession:
    builder_session = await load_builder_session(user_id)
    for key in ("current_bot_id", "current_menu_id", "current_button_id"):
        value = getattr(builder_session, key)
        if value is not None:
            context.user_data[key] = value
    if builder_session.pending_state:
        context.user_data["state"] = builder_session.pending_state
    if builder_session.draft:
        context.user_data["draft"] = builder_session.draft
    return builder_session


async def clear_pending_state(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("state", None)
    context.user_data.pop("draft", None)
    await save_builder_session(user_id, context, pending_state="", draft={})
