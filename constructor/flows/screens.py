"""Screen settings in the builder: media, keyboard type, columns, share-buttons.

Callbacks are anchored (``scr:...``) and registered before the legacy catch-all handlers.
"""
import json

from sqlalchemy import select
from telegram import InlineKeyboardButton, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from core.database import AsyncSessionLocal
from core.logger import get_logger
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.states import WAITING_FOR_ACTION_MEDIA, WAITING_FOR_MENU_MEDIA
from constructor.ui import show_screen
from engine.render import MEDIA_TYPES
from engine.telegram_client import get_client
from models.bots import Bot
from models.buttons import Button
from models.menus import Menu
from models.users import User

logger = get_logger("constructor.screens")

MAX_FILE_BYTES = 20 * 1024 * 1024  # Bot API getFile limit
MEDIA_LABELS = {
    "photo": "🖼 Rasm", "video": "🎬 Video", "document": "📄 Fayl",
    "audio": "🎵 Audio", "voice": "🎤 Ovozli xabar", "animation": "🎞 GIF",
}


# ---------------------------------------------------------------- pure helpers

def extract_media(message):
    """``(kind, file_id, file_size, filename)`` of the media in a Telegram message, or ``None``."""
    if message.animation:  # an animation also carries .document: check it first
        a = message.animation
        return "animation", a.file_id, a.file_size, a.file_name
    if message.photo:
        p = message.photo[-1]
        return "photo", p.file_id, p.file_size, None
    for kind in ("video", "audio", "voice", "document"):
        item = getattr(message, kind, None)
        if item:
            return kind, item.file_id, item.file_size, getattr(item, "file_name", None)
    return None


def media_from_sent(kind: str, sent) -> str | None:
    """file_id of the message a child bot just sent."""
    if kind == "photo":
        return sent.photo[-1].file_id if sent.photo else None
    item = getattr(sent, kind, None)
    return item.file_id if item else None


async def reupload(child, chat_id: int, kind: str, data: bytes, filename: str | None) -> str:
    """file_id values only work for the bot that saw the file, so send the bytes through the
    child bot (to the owner's private chat) and keep the id it gets back."""
    if kind not in MEDIA_TYPES:
        raise ValueError(kind)
    kwargs = {"chat_id": chat_id, kind: data}
    if kind in ("document", "audio", "video", "animation") and filename:
        kwargs["filename"] = filename
    sent = await getattr(child, f"send_{kind}")(**kwargs)
    file_id = media_from_sent(kind, sent)
    try:
        await child.delete_message(chat_id=chat_id, message_id=sent.message_id)
    except TelegramError:
        pass
    if not file_id:
        raise ValueError("no file_id in response")
    return file_id


# ---------------------------------------------------------------- data access

async def owned_menu(session, tg_id: int, menu_id: int):
    """``(menu, bot)`` if the menu belongs to a bot of this constructor user, else ``(None, None)``."""
    row = (await session.execute(
        select(Menu, Bot).join(Bot, Bot.id == Menu.bot_id).join(User, User.id == Bot.owner_id)
        .where(Menu.id == menu_id, User.tg_id == tg_id)
    )).first()
    return (row[0], row[1]) if row else (None, None)


def _menu_id(update: Update) -> int:
    return int(update.callback_query.data.rsplit(":", 1)[1])


# ---------------------------------------------------------------- screens

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_id: int | None = None, *, edit=True):
    menu_id = menu_id or _menu_id(update)
    async with AsyncSessionLocal() as session:
        menu, bot = await owned_menu(session, update.effective_user.id, menu_id)
    if menu is None:
        await update.callback_query.answer("Menu topilmadi.", show_alert=True)
        return
    media = MEDIA_LABELS.get(menu.media_type, "yo‘q") if menu.media_file_id else "yo‘q"
    reply = menu.keyboard_mode == "reply"
    text = (
        f"⚙️ <b>{menu.title}</b> — ko‘rinish\n\n"
        f"Media: {media}\n"
        f"Tugmalar: {'⌨️ Pastki klaviatura' if reply else '💬 Xabar ostida'}\n"
        f"Ustunlar: {menu.columns}"
    )
    keyboard = [
        [InlineKeyboardButton("🖼 Media qo‘yish", callback_data=f"scr:media:{menu.id}")],
        [InlineKeyboardButton(
            "⌨️ Pastki klaviaturaga o‘tkazish" if not reply else "💬 Xabar ostiga o‘tkazish",
            callback_data=f"scr:mode:{menu.id}",
        )],
        [InlineKeyboardButton(f"↔️ Ustunlar: {menu.columns} → {3 - menu.columns}", callback_data=f"scr:cols:{menu.id}")],
    ]
    if menu.media_file_id:
        keyboard.insert(1, [InlineKeyboardButton("🗑 Mediani olib tashlash", callback_data=f"scr:nomedia:{menu.id}")])
    if reply:
        keyboard.append([
            InlineKeyboardButton("📞 Kontakt tugmasi", callback_data=f"scr:share:contact:{menu.id}"),
            InlineKeyboardButton("📍 Lokatsiya tugmasi", callback_data=f"scr:share:location:{menu.id}"),
        ])
    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data=f"menu_{menu.id}")])
    await show_screen(update, text, keyboard, edit=edit)


async def toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, what, menu_id = update.callback_query.data.split(":")
    async with AsyncSessionLocal() as session:
        menu, _bot = await owned_menu(session, update.effective_user.id, int(menu_id))
        if menu is None:
            await update.callback_query.answer("Menu topilmadi.", show_alert=True)
            return
        if what == "mode":
            menu.keyboard_mode = "inline" if menu.keyboard_mode == "reply" else "reply"
            if menu.keyboard_mode == "inline":  # share buttons only exist on reply keyboards
                await _drop_share_buttons(session, menu.id)
        elif what == "cols":
            menu.columns = 2 if menu.columns == 1 else 1
        elif what == "nomedia":
            menu.media_type = None
            menu.media_file_id = None
        await session.commit()
    await show_settings(update, context, int(menu_id))


async def _drop_share_buttons(session, menu_id: int):
    rows = await session.execute(select(Button).where(Button.menu_id == menu_id, Button.kind != "normal"))
    for button in rows.scalars().all():
        await session.delete(button)


async def add_share_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, _, kind, menu_id = update.callback_query.data.split(":")
    label = "📞 Raqamimni yuborish" if kind == "contact" else "📍 Lokatsiyamni yuborish"
    async with AsyncSessionLocal() as session:
        menu, _bot = await owned_menu(session, update.effective_user.id, int(menu_id))
        if menu is None or menu.keyboard_mode != "reply":
            await update.callback_query.answer("Bu faqat pastki klaviaturada ishlaydi.", show_alert=True)
            return
        exists = (await session.execute(
            select(Button.id).where(Button.menu_id == menu.id, Button.kind == kind)
        )).first()
        if exists:
            await update.callback_query.answer("Bu tugma allaqachon bor.", show_alert=True)
            return
        count = len((await session.execute(select(Button.id).where(Button.menu_id == menu.id))).all())
        session.add(Button(menu_id=menu.id, text=label, kind=kind, position=count))
        await session.commit()
    await update.callback_query.answer("Tugma qo‘shildi. Javob xabarini tugmalar bo‘limida sozlang.", show_alert=True)
    await show_settings(update, context, int(menu_id))


# ---------------------------------------------------------------- media upload

async def ask_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_id = _menu_id(update)
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    async with AsyncSessionLocal() as session:
        menu, _bot = await owned_menu(session, update.effective_user.id, menu_id)
    if menu is None:
        await update.callback_query.answer("Menu topilmadi.", show_alert=True)
        return
    await save_builder_session(
        user.id, context, current_bot_id=menu.bot_id, current_menu_id=menu.id,
        pending_state=WAITING_FOR_MENU_MEDIA, draft={"flow": "menu_media"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🖼 Rasm, video, GIF, fayl yoki audio yuboring (20 MB gacha).\n"
        "Menu matni shu mediaga izoh bo‘lib qo‘shiladi.\n\n"
        "⚠️ Avval child botingizga o‘zingiz <code>/start</code> yuborgan bo‘lishingiz kerak — "
        "fayl bot orqali sizga yuborilib, so‘ng o‘chiriladi.",
        parse_mode="HTML",
    )


async def _transfer(update: Update, context: ContextTypes.DEFAULT_TYPE, bot):
    """Move the file of the incoming message to the child bot. Returns ``(kind, new_file_id)``
    or ``None`` after telling the user what went wrong."""
    message = update.message
    found = extract_media(message)
    if found is None:
        await message.reply_text("❌ Rasm, video, GIF, fayl yoki audio yuboring.")
        return None
    kind, file_id, size, filename = found
    if size and size > MAX_FILE_BYTES:
        await message.reply_text("❌ Fayl 20 MB dan katta. Kichikroq fayl yuboring.")
        return None
    try:
        tg_file = await context.bot.get_file(file_id)
        data = bytes(await tg_file.download_as_bytearray())
        child = await get_client(bot.plain_token)
        return kind, await reupload(child, update.effective_user.id, kind, data, filename)
    except TelegramError as exc:
        text = str(exc).lower()
        if "chat not found" in text or "forbidden" in text or "blocked" in text:
            await message.reply_text(
                "❌ Child bot sizga yozolmadi. Avval child botni oching va <code>/start</code> yuboring, "
                "so‘ng faylni qayta yuboring.", parse_mode="HTML",
            )
        else:
            logger.warning("media re-upload failed: %s", exc)
            await message.reply_text("❌ Faylni yuklab bo‘lmadi. Boshqa fayl bilan urinib ko‘ring.")
    except Exception:
        logger.exception("media re-upload failed")
        await message.reply_text("❌ Faylni yuklab bo‘lmadi. Keyinroq urinib ko‘ring.")
    return None


async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state not in (WAITING_FOR_MENU_MEDIA, WAITING_FOR_ACTION_MEDIA):
        return
    message = update.message
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    menu_id = context.user_data.get("current_menu_id")

    async with AsyncSessionLocal() as session:
        menu, bot = await owned_menu(session, update.effective_user.id, menu_id or 0)
    if menu is None:
        await message.reply_text("❌ Menu topilmadi.")
        return

    moved = await _transfer(update, context, bot)
    if moved is None:
        return
    kind, new_id = moved

    if state == WAITING_FOR_MENU_MEDIA:
        async with AsyncSessionLocal() as session:
            menu, _bot = await owned_menu(session, update.effective_user.id, menu_id)
            menu.media_type = kind
            menu.media_file_id = new_id
            await session.commit()
        await save_builder_session(user.id, context, pending_state="", draft={})
        await message.reply_text(f"✅ {MEDIA_LABELS[kind]} saqlandi.")
        await _settings_message(update, context, menu_id)
        return

    from constructor.flows.actions import save_button_action, return_to_buttons
    from models.button_actions import ActionType
    value = json.dumps({"type": kind, "file_id": new_id, "caption": message.caption_html or ""})
    async with AsyncSessionLocal() as session:
        await save_button_action(session, context.user_data.get("current_button_id"), ActionType.media, value)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await message.reply_text(f"✅ {MEDIA_LABELS[kind]} action saqlandi.")
    await return_to_buttons(update, context)


async def action_media_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(
        user.id, context, pending_state=WAITING_FOR_ACTION_MEDIA, draft={"flow": "action_media"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🖼 Tugma bosilganda yuboriladigan rasm/video/fayl/audioni yuboring (20 MB gacha). "
        "Izohni (caption) fayl bilan birga yozing.\n\n"
        "⚠️ Avval child botga o‘zingiz <code>/start</code> yuborgan bo‘lishingiz kerak.",
        parse_mode="HTML",
    )


async def _settings_message(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_id: int):
    """Same panel, but as a fresh message (we are answering a regular message, not a callback)."""
    async with AsyncSessionLocal() as session:
        menu, _bot = await owned_menu(session, update.effective_user.id, menu_id)
    keyboard = [[InlineKeyboardButton("⚙️ Ko‘rinish sozlamalari", callback_data=f"scr:open:{menu.id}")],
                [InlineKeyboardButton("⬅️ Menu", callback_data=f"menu_{menu.id}")]]
    await show_screen(update, f"<b>{menu.title}</b> menyusiga media biriktirildi.", keyboard, edit=False)
