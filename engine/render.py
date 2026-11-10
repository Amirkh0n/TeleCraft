"""Turning a screen (menu) into Telegram messages: text, media, inline or reply keyboard."""
import json

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

from core.logger import get_logger

logger = get_logger("render")

CAPTION_LIMIT = 1024
MEDIA_TYPES = ("photo", "video", "document", "audio", "voice", "animation")
_SEND_METHOD = {kind: f"send_{kind}" for kind in MEDIA_TYPES}


def _is_parse_error(exc: Exception) -> bool:
    return "parse entities" in str(exc).lower()


async def send_text(tg, chat_id, text, *, reply_markup=None):
    """Send text as HTML. If the text contains something Telegram cannot parse as HTML
    (a stray ``<`` typed by the bot's owner), send it as plain text instead of failing."""
    try:
        return await tg.send_message(
            chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )
    except BadRequest as exc:
        if not _is_parse_error(exc):
            raise
        return await tg.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def send_media(tg, chat_id, media_type, file_id, *, caption=None, reply_markup=None) -> bool:
    """Send a stored file. Returns False if Telegram rejected the file (e.g. an invalid file_id)."""
    method = getattr(tg, _SEND_METHOD[media_type])
    base = {"chat_id": chat_id, media_type: file_id, "reply_markup": reply_markup}
    try:
        if caption:
            await method(caption=caption, parse_mode=ParseMode.HTML, **base)
        else:
            await method(**base)
        return True
    except BadRequest as exc:
        if caption and _is_parse_error(exc):
            # Caption is not valid HTML: send the file, then the text as a normal message.
            await method(**base)
            await send_text(tg, chat_id, caption)
            return True
        logger.warning("Telegram rejected %s file: %s", media_type, exc)
        return False


def parse_media_value(value: str | None) -> dict | None:
    """Button action value for ActionType.media: JSON {"type", "file_id", "caption"}."""
    try:
        data = json.loads(value or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") not in MEDIA_TYPES or not data.get("file_id"):
        return None
    return data


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def build_markup(menu, buttons):
    """Keyboard for a screen, or None if it has no buttons."""
    columns = max(1, min(int(menu.columns or 1), 2))
    if menu.keyboard_mode == "reply":
        keys = [
            KeyboardButton(
                button.text,
                request_contact=button.kind == "contact",
                request_location=button.kind == "location",
            )
            for button in buttons
        ]
        return ReplyKeyboardMarkup(_chunk(keys, columns), resize_keyboard=True) if keys else None

    # Contact/location buttons only exist on reply keyboards; inline ones have no meaning here.
    keys = [
        InlineKeyboardButton(button.text, callback_data=str(button.id))
        for button in buttons
        if button.kind == "normal"
    ]
    return InlineKeyboardMarkup(_chunk(keys, columns)) if keys else None


async def send_screen(tg, chat_id, menu, buttons, user_session) -> None:
    """Show a menu to the user and keep ``user_session.reply_keyboard_active`` accurate."""
    markup = build_markup(menu, buttons)
    reply_was_active = bool(user_session.reply_keyboard_active)

    if reply_was_active and markup is None:
        markup = ReplyKeyboardRemove()
    elif reply_was_active and isinstance(markup, InlineKeyboardMarkup):
        # A message can carry only one kind of markup: clear the old keyboard first.
        try:
            note = await tg.send_message(chat_id=chat_id, text="⌨️", reply_markup=ReplyKeyboardRemove())
            await tg.delete_message(chat_id=chat_id, message_id=note.message_id)
        except Exception as exc:  # cosmetic; never block the screen itself
            logger.info("Could not clear reply keyboard: %s", exc)

    text = menu.message_text
    media_ok = False
    if menu.media_type in MEDIA_TYPES and menu.media_file_id:
        if text and len(text) > CAPTION_LIMIT:
            media_ok = await send_media(tg, chat_id, menu.media_type, menu.media_file_id)
            if media_ok:
                await send_text(tg, chat_id, text, reply_markup=markup)
        else:
            media_ok = await send_media(
                tg, chat_id, menu.media_type, menu.media_file_id, caption=text, reply_markup=markup
            )
    if not media_ok:
        await send_text(tg, chat_id, text or menu.title, reply_markup=markup)

    user_session.reply_keyboard_active = isinstance(markup, ReplyKeyboardMarkup)
