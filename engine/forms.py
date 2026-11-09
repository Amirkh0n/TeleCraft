"""Forms: a bot asks the user a series of questions and stores the answers.

State lives on ``UserSession`` (form_id / form_step / form_data), so it survives restarts
and works the same for every user of every bot. While a form is active, every message from
that user is an answer; ``/start``, ``/cancel`` or the cancel button leave the form.
"""
import html
import re

from sqlalchemy import select
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import Forbidden, TelegramError

from core.config import settings
from core.logger import get_logger
from engine.render import send_text
from models.admin_links import AdminLink
from models.forms import (
    FIELD_CHOICE, FIELD_EMAIL, FIELD_LOCATION, FIELD_NUMBER, FIELD_PHONE, FIELD_PHOTO,
    Form, FormField, FormSubmission,
)
from models.users import User

logger = get_logger("forms")

CANCEL_LABEL = "❌ Bekor qilish"
SKIP_LABEL = "⏭ O‘tkazib yuborish"
SHARE_PHONE_LABEL = "📞 Raqamni yuborish"
SHARE_LOCATION_LABEL = "📍 Lokatsiyani yuborish"
MAX_TEXT_LENGTH = 1000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


# ---------------------------------------------------------------- answer parsing (pure)

def parse_answer(field, message: dict):
    """Validate one answer. Returns ``(True, value)`` or ``(False, error_message)``."""
    text = (message.get("text") or "").strip()
    kind = field.type

    if kind == FIELD_PHOTO:
        photos = message.get("photo")
        if not photos:
            return False, "📷 Iltimos, rasm yuboring."
        best = max(photos, key=lambda p: p.get("file_size") or (p.get("width", 0) * p.get("height", 0)))
        return True, best["file_id"]

    if kind == FIELD_LOCATION:
        location = message.get("location")
        if not location:
            return False, "📍 Iltimos, lokatsiyani tugma orqali yuboring."
        return True, f"{location['latitude']},{location['longitude']}"

    if kind == FIELD_PHONE:
        contact = message.get("contact")
        raw = contact.get("phone_number") if contact else text
        digits = re.sub(r"\D", "", raw or "")
        if not (7 <= len(digits) <= 15) or not re.fullmatch(r"\+?[\d\s\-()]+", raw or ""):
            return False, "📞 Telefon raqami noto‘g‘ri. Masalan: +998901234567"
        return True, "+" + digits

    if not text:
        return False, "✍️ Iltimos, javobni matn ko‘rinishida yuboring."

    if kind == FIELD_NUMBER:
        if not _NUMBER_RE.fullmatch(text.replace(" ", "")):
            return False, "🔢 Iltimos, faqat raqam yuboring."
        return True, text.replace(" ", "").replace(",", ".")

    if kind == FIELD_EMAIL:
        if not _EMAIL_RE.fullmatch(text):
            return False, "📧 Email manzili noto‘g‘ri. Masalan: ism@example.com"
        return True, text.lower()

    if kind == FIELD_CHOICE:
        options = field.options or []
        if text not in options:
            return False, "👇 Iltimos, tugmalardan birini tanlang."
        return True, text

    if len(text) > MAX_TEXT_LENGTH:
        return False, f"✂️ Javob juda uzun (eng ko‘pi bilan {MAX_TEXT_LENGTH} belgi)."
    return True, text


def keyboard_for(field) -> ReplyKeyboardMarkup:
    """Reply keyboard shown under a question."""
    rows: list[list[KeyboardButton]] = []
    if field.type == FIELD_CHOICE:
        rows.extend([KeyboardButton(option)] for option in (field.options or []))
    elif field.type == FIELD_PHONE:
        rows.append([KeyboardButton(SHARE_PHONE_LABEL, request_contact=True)])
    elif field.type == FIELD_LOCATION:
        rows.append([KeyboardButton(SHARE_LOCATION_LABEL, request_location=True)])
    if not field.required:
        rows.append([KeyboardButton(SKIP_LABEL)])
    rows.append([KeyboardButton(CANCEL_LABEL)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ---------------------------------------------------------------- state helpers

def is_active(user_session) -> bool:
    return bool(user_session and user_session.form_id is not None)


def clear_state(user_session) -> None:
    user_session.form_id = None
    user_session.form_step = None
    user_session.form_data = None


async def _load_fields(session, form_id: int) -> list:
    result = await session.execute(
        select(FormField).where(FormField.form_id == form_id).order_by(FormField.position, FormField.id)
    )
    return list(result.scalars().all())


async def _ask(tg, chat_id, field, number: int, total: int) -> None:
    header = f"<b>{number}/{total}</b>  "
    await send_text(tg, chat_id, header + field.prompt, reply_markup=keyboard_for(field))


# ---------------------------------------------------------------- public API

async def start_form(tg, bot, form_id: int, chat_id: int, user_session, session) -> None:
    result = await session.execute(select(Form).where(Form.id == form_id, Form.bot_id == bot.id))
    form = result.scalar_one_or_none()
    fields = await _load_fields(session, form.id) if form else []
    if form is None or not fields:
        await send_text(tg, chat_id, "Bu forma hozir mavjud emas.")
        return

    user_session.form_id = form.id
    user_session.form_step = 0
    user_session.form_data = []
    user_session.reply_keyboard_active = True
    await session.commit()

    if form.intro_text:
        await send_text(tg, chat_id, form.intro_text)
    await _ask(tg, chat_id, fields[0], 1, len(fields))


async def abort_form(tg, bot, chat_id: int, user_session, session, *, notify: bool = True) -> None:
    """Leave the form without saving, optionally telling the user, and restore the menu."""
    clear_state(user_session)
    await session.commit()
    if notify:
        await send_text(tg, chat_id, "Forma bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        user_session.reply_keyboard_active = False
        await session.commit()


async def handle_message(tg, bot, message: dict, user_session, session) -> None:
    """Process one message from a user who is in the middle of a form."""
    from engine.actions import open_menu  # local import: actions imports this module

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if text == CANCEL_LABEL or text.split("@")[0] == "/cancel":
        await abort_form(tg, bot, chat_id, user_session, session)
        await open_menu(tg, bot.id, user_session.current_menu_id, chat_id, session)
        return

    form = (await session.execute(select(Form).where(Form.id == user_session.form_id))).scalar_one_or_none()
    fields = await _load_fields(session, user_session.form_id) if form else []
    step = user_session.form_step or 0
    if form is None or step >= len(fields):  # form was deleted/shortened while the user was in it
        await abort_form(tg, bot, chat_id, user_session, session)
        await open_menu(tg, bot.id, user_session.current_menu_id, chat_id, session)
        return

    field = fields[step]
    if text == SKIP_LABEL and not field.required:
        value = None
    else:
        ok, value = parse_answer(field, message)
        if not ok:
            await send_text(tg, chat_id, value, reply_markup=keyboard_for(field))
            return

    answers = list(user_session.form_data or [])
    answers.append({"label": field.label, "type": field.type, "value": value})
    user_session.form_data = answers
    user_session.form_step = step + 1

    if user_session.form_step < len(fields):
        await session.commit()
        await _ask(tg, chat_id, fields[user_session.form_step], user_session.form_step + 1, len(fields))
        return

    await _finish(tg, bot, form, message, chat_id, answers, user_session, session)


async def _finish(tg, bot, form, message, chat_id, answers, user_session, session) -> None:
    from engine.actions import open_menu

    sender = message.get("from") or {}
    full_name = " ".join(part for part in (sender.get("first_name"), sender.get("last_name")) if part) or None
    session.add(
        FormSubmission(
            form_id=form.id,
            bot_id=bot.id,
            tg_user_id=sender.get("id", chat_id),
            username=sender.get("username"),
            full_name=full_name,
            answers=answers,
        )
    )
    clear_state(user_session)
    user_session.reply_keyboard_active = False
    await session.commit()  # the answers are safe from here on, whatever Telegram does next

    await send_text(
        tg, chat_id, form.final_message or "✅ Rahmat! Javobingiz qabul qilindi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    if form.notify_admins:
        await _notify_admins(tg, bot, form, sender, full_name, answers, session)
    await open_menu(tg, bot.id, user_session.current_menu_id, chat_id, session)


# ---------------------------------------------------------------- notifications

def format_submission(form_title: str, sender: dict, full_name: str | None, answers: list) -> str:
    who = html.escape(full_name or "Noma’lum")
    if sender.get("username"):
        who += f" (@{html.escape(sender['username'])})"
    lines = [f"📋 <b>{html.escape(form_title)}</b> — yangi javob", f"👤 {who}  <code>{sender.get('id', '')}</code>", ""]
    for answer in answers:
        value = answer["value"]
        if value is None:
            shown = "—"
        elif answer["type"] == FIELD_PHOTO:
            shown = "📷 (rasm pastda)"
        elif answer["type"] == FIELD_LOCATION:
            shown = f"https://maps.google.com/?q={value}"
        else:
            shown = html.escape(str(value))
        lines.append(f"<b>{html.escape(answer['label'])}:</b> {shown}")
    return "\n".join(lines)


async def _recipients(bot, session) -> list[int]:
    rows = await session.execute(select(AdminLink.admin_tg_id).where(AdminLink.bot_id == bot.id))
    ids = [row[0] for row in rows.all()]
    owner = (await session.execute(select(User.tg_id).where(User.id == bot.owner_id))).scalar_one_or_none()
    if owner is not None:
        ids.append(owner)
    return list(dict.fromkeys(ids))  # unique, order kept


async def _deliver(clients, chat_id: int, text: str, answers: list) -> bool:
    """Send the summary (and photos/locations) through the first client that can reach the chat."""
    for client in clients:
        try:
            await send_text(client, chat_id, text)
        except Forbidden:
            continue  # this person never started that bot; try the next one
        except TelegramError as exc:
            logger.warning("Could not deliver form answer to %s: %s", chat_id, exc)
            continue

        # The summary arrived. Attachments are a bonus: a file_id only works through the child
        # bot that received the photo, so a failure here must not make the delivery look failed.
        for answer in answers:
            if answer["value"] is None:
                continue
            try:
                if answer["type"] == FIELD_PHOTO:
                    await client.send_photo(chat_id=chat_id, photo=answer["value"], caption=answer["label"])
                elif answer["type"] == FIELD_LOCATION:
                    lat, lon = answer["value"].split(",")
                    await client.send_location(chat_id=chat_id, latitude=float(lat), longitude=float(lon))
            except TelegramError as exc:
                logger.info("Attachment for %s not delivered: %s", chat_id, exc)
        return True
    return False


async def notify(tg, bot, text: str, session, answers=()) -> None:
    """Send ``text`` to the bot's admins and its owner. Tries the child bot first, then the
    constructor bot (owners and admins always started that one). Never raises."""
    clients = [tg]
    try:
        from engine.telegram_client import get_client
        clients.append(await get_client(settings.TELEGRAM_TOKEN))
    except Exception as exc:
        logger.info("Constructor bot client unavailable for notifications: %s", exc)

    for chat_id in await _recipients(bot, session):
        if not await _deliver(clients, chat_id, text, list(answers)):
            logger.warning("Notification for bot_id=%s could not reach %s", bot.id, chat_id)


async def _notify_admins(tg, bot, form, sender, full_name, answers, session) -> None:
    await notify(tg, bot, format_submission(form.title, sender, full_name, answers), session, answers)
