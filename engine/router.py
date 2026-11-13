"""Entry point for every update a child bot receives."""
import asyncio
import html
import weakref
from collections import OrderedDict

from telegram.error import Forbidden

from core.logger import get_logger
from engine import booking, cinema, course, forms, quiz, shop
from engine.audience import set_blocked, touch_user
from engine.actions import execute_action, get_user_session
from engine.resolver import (
    handle_start,
    handle_button,
    handle_text,
    find_share_button,
    has_share_button,
)
from engine import subscription
from engine.telegram_client import get_client

logger = get_logger("router")

HINT_TEXT = "Kerakli bo‘limni menyudagi tugmalardan tanlang."

# --- Telegram retries an update until it gets HTTP 200, so the same update can arrive twice.
_SEEN_LIMIT = 5000
_seen: "OrderedDict[tuple, None]" = OrderedDict()


def _already_seen(bot_id: int, update_id) -> bool:
    if update_id is None:
        return False
    key = (bot_id, update_id)
    if key in _seen:
        return True
    _seen[key] = None
    if len(_seen) > _SEEN_LIMIT:
        _seen.popitem(last=False)
    return False


# --- One update at a time per (bot, user): otherwise two quick messages could be processed
# in parallel and form answers would be stored out of order.
_locks: "weakref.WeakValueDictionary[tuple, asyncio.Lock]" = weakref.WeakValueDictionary()


def _user_lock(bot_id: int, user_id) -> asyncio.Lock:
    key = (bot_id, user_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _sender_id(update: dict):
    source = (update.get("callback_query") or update.get("message") or update.get("my_chat_member")
              or update.get("poll_answer") or {})
    return (source.get("from") or source.get("user") or {}).get("id")


def _command(text: str) -> str:
    """'/start@MyBot payload' -> '/start'"""
    return text.split()[0].split("@")[0] if text else ""


async def route_update(bot, update, session, *, client=None):
    """Handle one update. Never raises: a failing update must not make Telegram retry it forever."""
    if _already_seen(bot.id, update.get("update_id")):
        logger.info("Duplicate update %s for bot_id=%s ignored", update.get("update_id"), bot.id)
        return

    try:
        tg = client or await get_client(bot.plain_token)
        if update.get("callback_query"):
            await _ack(tg, update["callback_query"])
        async with _user_lock(bot.id, _sender_id(update)):
            if update.get("my_chat_member"):
                await _on_membership(bot, update["my_chat_member"], session)
            elif getattr(bot, "kind", "standard") == "cinema":
                await cinema.handle(bot, update, session, tg)
            elif getattr(bot, "kind", "standard") == "booking":
                await booking.handle(bot, update, session, tg)
            elif getattr(bot, "kind", "standard") == "quiz":
                await quiz.handle(bot, update, session, tg)
            elif getattr(bot, "kind", "standard") == "course":
                await course.handle(bot, update, session, tg)
            elif getattr(bot, "kind", "standard") == "shop":
                await shop.handle(bot, update, session, tg)
            elif update.get("callback_query"):
                await _on_callback(bot, update["callback_query"], session, tg)
            elif update.get("message"):
                await _on_message(bot, update["message"], session, tg)
    except Forbidden:
        logger.info("bot_id=%s: the user blocked the bot or never started it", bot.id)
        await session.rollback()
        sender = _sender_id(update)
        if sender is not None:
            try:
                await set_blocked(session, bot.id, sender)
            except Exception:
                logger.exception("could not mark user as blocked")
                await session.rollback()
    except Exception:
        logger.exception("bot_id=%s: failed to process update %s", bot.id, update.get("update_id"))
        await session.rollback()


async def _ack(tg, callback):
    """Stops the loading spinner on the tapped button (for every bot kind)."""
    try:
        await tg.answer_callback_query(callback["id"])
    except Exception as exc:  # e.g. the query is too old: the action can still run
        logger.info("answer_callback_query failed: %s", exc)


async def _on_callback(bot, callback, session, tg):
    user_id = callback["from"]["id"]
    await touch_user(session, bot.id, callback["from"])
    if callback.get("data") == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, user_id, session, use_cache=False):
            action_type, value = await handle_start(bot, callback, session)
            user_session = await get_user_session(session, bot.id, user_id)
            await execute_action(bot, action_type, value, user_id, session, tg=tg, user_session=user_session)
        return
    if not await subscription.gate(tg, bot, user_id, session):
        return
    user_session = await get_user_session(session, bot.id, user_id)
    if forms.is_active(user_session):
        # Tapping an old inline button while filling a form means "leave the form".
        await forms.abort_form(tg, bot, user_id, user_session, session, notify=False)

    action_type, value = await handle_button(bot, callback, session)
    if action_type:
        await execute_action(bot, action_type, value, user_id, session, tg=tg, user_session=user_session)


async def _on_message(bot, message, session, tg):
    if (message.get("chat") or {}).get("type") != "private":
        return  # groups/channels are not supported yet
    sender = message.get("from") or {}
    if sender.get("is_bot") or "id" not in sender:
        return

    user_id = sender["id"]
    text = message.get("text")
    payload = text.split(maxsplit=1)[1] if text and _command(text) == "/start" and len(text.split()) > 1 else None
    await touch_user(session, bot.id, sender, source=payload)
    if not await subscription.gate(tg, bot, user_id, session):
        return
    user_session = await get_user_session(session, bot.id, user_id)

    if text and _command(text) == "/start":
        if forms.is_active(user_session):
            forms.clear_state(user_session)
            await session.commit()
        action_type, value = await handle_start(bot, message, session)
        await execute_action(bot, action_type, value, user_id, session, tg=tg, user_session=user_session)
        return

    if forms.is_active(user_session):
        await forms.handle_message(tg, bot, message, user_session, session)
        return

    if text:
        action_type, value = await handle_text(bot, message, session, user_session)
        if action_type:
            await execute_action(bot, action_type, value, user_id, session, tg=tg, user_session=user_session)
        else:
            await tg.send_message(chat_id=user_id, text=HINT_TEXT)
    elif message.get("contact"):
        await _on_shared(bot, "contact", message, user_session, session, tg)
    elif message.get("location"):
        await _on_shared(bot, "location", message, user_session, session, tg)
    # Other message types (photos, stickers...) outside a form are ignored.


async def _on_membership(bot, event, session):
    """The user blocked or unblocked the bot (needs ``my_chat_member`` in allowed_updates)."""
    if (event.get("chat") or {}).get("type") != "private":
        return
    status = (event.get("new_chat_member") or {}).get("status")
    user_id = (event.get("from") or {}).get("id")
    if user_id is not None and status in ("kicked", "member"):
        await set_blocked(session, bot.id, user_id, blocked=status == "kicked")


async def _on_shared(bot, kind, message, user_session, session, tg):
    """A user shared a contact/location through a button outside any form: tell the admins,
    then run the button's own action (e.g. a thank-you message)."""
    if not await has_share_button(bot, user_session, kind, session):
        return  # not something this bot asked for

    sender = message["from"]
    who = html.escape(" ".join(p for p in (sender.get("first_name"), sender.get("last_name")) if p) or "Noma’lum")
    if sender.get("username"):
        who += f" (@{html.escape(sender['username'])})"
    if kind == "contact":
        body = f"📞 <b>Kontakt:</b> {html.escape(message['contact'].get('phone_number', ''))}"
    else:
        location = message["location"]
        body = f"📍 <b>Lokatsiya:</b> https://maps.google.com/?q={location['latitude']},{location['longitude']}"
    await forms.notify(tg, bot, f"{body}\n👤 {who}  <code>{sender['id']}</code>", session)

    action_type, value = await find_share_button(bot, user_session, kind, session)
    if action_type:
        await execute_action(bot, action_type, value, sender["id"], session, tg=tg, user_session=user_session)
    else:
        await tg.send_message(chat_id=sender["id"], text="✅ Rahmat!")
