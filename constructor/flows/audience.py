"""Builder panels: audience statistics, broadcasts, required channels."""
import html
import re

from sqlalchemy import select
from telegram import InlineKeyboardButton, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from constructor import states
from constructor.flows.screens import MEDIA_LABELS, _transfer
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from core.logger import get_logger
from core.validators import validate_url
from engine import audience as audience_engine
from engine import broadcast as broadcast_engine
from engine import subscription
from engine.telegram_client import get_client
from models.audience import BROADCAST_DRAFT, BROADCAST_SENDING, Broadcast, RequiredChannel
from models.bots import Bot
from models.users import User

logger = get_logger("constructor.audience")

MAX_CHANNELS = 5
BUTTON_LABEL_MAX = 64


# ---------------------------------------------------------------- pure helpers

def parse_button(text: str) -> tuple[str, str]:
    """``"Ochish | https://example.com"`` -> ``("Ochish", "https://example.com")``."""
    label, sep, url = (text or "").partition("|")
    label, url = label.strip(), url.strip()
    if not sep or not label or len(label) > BUTTON_LABEL_MAX:
        raise ValueError(f"Format: Tugma matni | https://havola (matn {BUTTON_LABEL_MAX} belgigacha).")
    try:
        return label, validate_url(url, "URL")
    except Exception:
        raise ValueError("Havola https:// bilan boshlanishi kerak.") from None


def normalize_channel_ref(text: str):
    """``@name``, ``t.me/name`` or ``-100123`` -> value for getChat, or ``None``."""
    text = (text or "").strip()
    match = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z][\w]{3,31})/?", text)
    if match:
        return "@" + match.group(1)
    if re.fullmatch(r"@[A-Za-z][\w]{3,31}", text):
        return text
    if re.fullmatch(r"-100\d{5,}", text):
        return int(text)
    return None


def stats_text(name: str, s: dict) -> str:
    lines = [
        f"👥 <b>{html.escape(name)}</b> — auditoriya", "",
        f"Jami: <b>{s['total']}</b>  (faol {s['active']}, bloklagan {s['blocked']})",
        f"Yangi: 24 soat — {s['new_24h']}, 7 kun — {s['new_7d']}, 30 kun — {s['new_30d']}",
        f"Faol: 24 soat — {s['active_24h']}, 7 kun — {s['active_7d']}",
        f"Forma javoblari: {s['submissions']}",
        f"Broadcast orqali yuborilgan xabarlar: {s['broadcast_messages']}",
    ]
    if s["sources"]:
        lines += ["", "Manbalar (<code>t.me/bot?start=nom</code>):"]
        lines += [f"• {html.escape(src)}: {n}" for src, n in s["sources"]]
    return "\n".join(lines)


# ---------------------------------------------------------------- access helpers

async def _current_bot(session, update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    if not bot_id:
        return None
    return (await session.execute(
        select(Bot).join(User, User.id == Bot.owner_id).where(Bot.id == bot_id, User.tg_id == update.effective_user.id)
    )).scalar_one_or_none()


async def owned_broadcast(session, tg_id: int, broadcast_id: int):
    row = (await session.execute(
        select(Broadcast, Bot).join(Bot, Bot.id == Broadcast.bot_id).join(User, User.id == Bot.owner_id)
        .where(Broadcast.id == broadcast_id, User.tg_id == tg_id)
    )).first()
    return (row[0], row[1]) if row else (None, None)


def _id(update: Update) -> int:
    return int(update.callback_query.data.rsplit(":", 1)[1])


async def _no_bot(update: Update):
    await update.callback_query.answer("Avval botni tanlang.", show_alert=True)


# ---------------------------------------------------------------- statistics

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        data = await audience_engine.stats(session, bot.id)
    keyboard = [[InlineKeyboardButton("📣 Broadcast", callback_data="bc:home")],
                [InlineKeyboardButton("🔄 Yangilash", callback_data="aud:home")],
                [InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")]]
    await show_screen(update, stats_text(bot.name, data), keyboard)


# ---------------------------------------------------------------- required channels

async def show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=True):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        channels = await subscription.channels_of(session, bot.id)
    lines = ["🔒 <b>Majburiy obuna</b>", "",
             "Foydalanuvchi shu kanallarga a‘zo bo‘lmaguncha botdan foydalana olmaydi. "
             "Bot har bir kanalda <b>administrator</b> bo‘lishi shart."]
    if channels:
        lines += ["", *[f"• {html.escape(c.title)}" for c in channels]]
    keyboard = [[InlineKeyboardButton(f"🗑 {c.title}", callback_data=f"sub:del:{c.id}")] for c in channels]
    if len(channels) < MAX_CHANNELS:
        keyboard.append([InlineKeyboardButton("➕ Kanal qo‘shish", callback_data="sub:add")])
    keyboard.append([InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")])
    await show_screen(update, "\n".join(lines), keyboard, edit=edit)


async def add_channel_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_CHANNEL, draft={"flow": "channel"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "📢 Kanal manzilini yuboring: <code>@kanal_nomi</code> yoki <code>t.me/kanal_nomi</code>.\n"
        "Avval child botni shu kanalga <b>administrator</b> qiling.\n"
        "Yopiq kanal bo‘lsa, raqamli ID (<code>-100...</code>) yuboring.",
        parse_mode="HTML",
    )


async def delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_id = _id(update)
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        channel = (await session.execute(
            select(RequiredChannel).where(RequiredChannel.id == channel_id, RequiredChannel.bot_id == bot.id)
        )).scalar_one_or_none()
        if channel:
            await session.delete(channel)
            await session.commit()
    await show_channels(update, context)


async def _save_channel(update, context, bot, chat_id, title, username, invite_link):
    async with AsyncSessionLocal() as session:
        exists = (await session.execute(
            select(RequiredChannel.id).where(RequiredChannel.bot_id == bot.id, RequiredChannel.chat_id == chat_id)
        )).first()
        if exists:
            await update.message.reply_text("Bu kanal allaqachon qo‘shilgan.")
        else:
            position = len(await subscription.channels_of(session, bot.id))
            session.add(RequiredChannel(
                bot_id=bot.id, chat_id=chat_id, title=title[:255], username=username,
                invite_link=invite_link, position=position,
            ))
            await session.commit()
            await update.message.reply_text("✅ Kanal qo‘shildi. Endi botdan foydalanish uchun unga obuna bo‘lish shart.")
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await show_channels(update, context, edit=False)


# ---------------------------------------------------------------- broadcasts

async def broadcast_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        recent = (await session.execute(
            select(Broadcast).where(Broadcast.bot_id == bot.id, Broadcast.status != BROADCAST_DRAFT)
            .order_by(Broadcast.id.desc()).limit(5)
        )).scalars().all()
        size = await broadcast_engine.audience_size(session, bot.id)
    keyboard = [[InlineKeyboardButton("✍️ Yangi broadcast", callback_data="bc:new")]]
    for b in recent:
        label = (b.text or MEDIA_LABELS.get(b.media_type, "Media")).replace("\n", " ")[:25]
        keyboard.append([InlineKeyboardButton(f"#{b.id} {label} · {b.sent}/{b.total}", callback_data=f"bc:status:{b.id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")])
    await show_screen(
        update,
        f"📣 <b>Broadcast</b>\n\nBotni bloklamagan foydalanuvchilar: <b>{size}</b>.\n"
        "Xabar matn, rasm, video yoki fayl bo‘lishi mumkin; pastiga havola tugmasi qo‘shsa bo‘ladi.",
        keyboard,
    )


async def new_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_BC_CONTENT, draft={"flow": "broadcast"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "✍️ Yuboriladigan xabarni yuboring: matn yoki rasm/video/fayl (izoh bilan).\n"
        "Formatlash (qalin, kursiv, havola) saqlanadi.\n\n"
        "ℹ️ Media uchun avval child botga o‘zingiz <code>/start</code> yuborgan bo‘lishingiz kerak.",
        parse_mode="HTML",
    )


async def _create_and_show(update, context, bot, **content):
    async with AsyncSessionLocal() as session:
        draft = await broadcast_engine.create_draft(session, bot.id, update.effective_user.id, **content)
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await show_broadcast(update, context, draft.id, edit=False)


async def show_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, broadcast_id: int | None = None, *, edit=True):
    broadcast_id = broadcast_id or _id(update)
    async with AsyncSessionLocal() as session:
        b, bot = await owned_broadcast(session, update.effective_user.id, broadcast_id)
        if b is None:
            await update.callback_query.answer("Broadcast topilmadi.", show_alert=True)
            return
        size = await broadcast_engine.audience_size(session, bot.id)
    snippet = html.escape((b.text or "")[:200]) or "(matnsiz)"
    media = f"\nMedia: {MEDIA_LABELS.get(b.media_type, b.media_type)}" if b.media_file_id else ""
    button = f"\nTugma: {html.escape(b.button_text)} → {html.escape(b.button_url)}" if b.button_text else ""
    if b.status == BROADCAST_DRAFT:
        text = f"📣 <b>Broadcast #{b.id}</b> (qoralama)\n\n{snippet}{media}{button}\n\nQabul qiluvchilar: <b>{size}</b>"
        keyboard = [
            [InlineKeyboardButton("👁 O‘zimga yuborib ko‘rish", callback_data=f"bc:preview:{b.id}")],
            [InlineKeyboardButton("🔗 Tugma qo‘shish", callback_data=f"bc:btn:{b.id}")],
            [InlineKeyboardButton("🚀 Yuborish", callback_data=f"bc:ask:{b.id}")],
            [InlineKeyboardButton("🗑 Bekor qilish", callback_data=f"bc:cancel:{b.id}")],
            [InlineKeyboardButton("⬅️ Broadcast", callback_data="bc:home")],
        ]
    else:
        text = f"📣 <b>Broadcast #{b.id}</b>\n\n{broadcast_engine.summary(b)}"
        keyboard = []
        if b.status == BROADCAST_SENDING:
            keyboard.append([InlineKeyboardButton("🔄 Yangilash", callback_data=f"bc:status:{b.id}")])
            keyboard.append([InlineKeyboardButton("🛑 To‘xtatish", callback_data=f"bc:cancel:{b.id}")])
        keyboard.append([InlineKeyboardButton("⬅️ Broadcast", callback_data="bc:home")])
    await show_screen(update, text, keyboard, edit=edit)


async def broadcast_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, action, raw = update.callback_query.data.split(":")
    broadcast_id = int(raw)
    async with AsyncSessionLocal() as session:
        b, bot = await owned_broadcast(session, update.effective_user.id, broadcast_id)
        if b is None:
            await update.callback_query.answer("Broadcast topilmadi.", show_alert=True)
            return

        if action == "preview":
            token = bot.plain_token
            await update.callback_query.answer()
            try:
                ok = await broadcast_engine.deliver(await get_client(token), update.effective_user.id, b)
            except TelegramError:
                ok = False
            if not ok:
                await update.callback_query.message.reply_text(
                    "❌ Ko‘rib bo‘lmadi. Child botga avval <code>/start</code> yuboring.", parse_mode="HTML"
                )
            return

        if action == "btn":
            user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
            await save_builder_session(
                user.id, context, pending_state=states.WAITING_FOR_BC_BUTTON, draft={"flow": "bc_button", "id": b.id},
            )
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                "🔗 Tugmani shu ko‘rinishda yuboring:\n<code>Batafsil | https://example.com</code>", parse_mode="HTML"
            )
            return

        if action == "ask":
            size = await broadcast_engine.audience_size(session, bot.id)
            keyboard = [[InlineKeyboardButton(f"✅ Ha, {size} kishiga yuborish", callback_data=f"bc:go:{b.id}")],
                        [InlineKeyboardButton("⬅️ Ortga", callback_data=f"bc:open:{b.id}")]]
            await show_screen(update, "⚠️ Xabar darhol yuboriladi va qaytarib bo‘lmaydi. Davom etasizmi?", keyboard)
            return

        if action == "go":
            result = await broadcast_engine.start(session, b.id)
            if result == "busy":
                await update.callback_query.answer("Boshqa broadcast hali yuborilmoqda.", show_alert=True)
                return
            if result == "invalid":
                await update.callback_query.answer("Bu broadcastni yuborib bo‘lmaydi.", show_alert=True)
                return
            await session.refresh(b)

        if action == "cancel":
            await broadcast_engine.cancel(session, b.id)
    await show_broadcast(update, context, broadcast_id)


# ---------------------------------------------------------------- message handlers

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)

    if state == states.WAITING_FOR_BC_CONTENT:
        async with AsyncSessionLocal() as session:
            bot = await _current_bot(session, update, context)
        if bot is None:
            await update.message.reply_text("❌ Avval botni tanlang.")
            return
        if not text or len(update.message.text_html) > 4000:
            await update.message.reply_text("❌ Matn 1–4000 belgi bo‘lsin. Qayta yuboring.")
            return
        await _create_and_show(update, context, bot, text=update.message.text_html)

    elif state == states.WAITING_FOR_BC_BUTTON:
        try:
            label, url = parse_button(text)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc}")
            return
        broadcast_id = int((context.user_data.get("draft") or {}).get("id", 0))
        async with AsyncSessionLocal() as session:
            b, _bot = await owned_broadcast(session, update.effective_user.id, broadcast_id)
            if b is None or b.status != BROADCAST_DRAFT:
                await update.message.reply_text("❌ Broadcast topilmadi.")
                return
            b.button_text, b.button_url = label, url
            await session.commit()
        await save_builder_session(user.id, context, pending_state="", draft={})
        await show_broadcast(update, context, broadcast_id, edit=False)

    elif state == states.WAITING_FOR_CHANNEL:
        await _handle_channel(update, context, text)

    elif state == states.WAITING_FOR_CHANNEL_LINK:
        draft = dict(context.user_data.get("draft") or {})
        if not re.fullmatch(r"https://t\.me/(\+|joinchat/)[\w-]+", text):
            await update.message.reply_text("❌ Taklif havolasi <code>https://t.me/+...</code> ko‘rinishida bo‘lsin.", parse_mode="HTML")
            return
        async with AsyncSessionLocal() as session:
            bot = await _current_bot(session, update, context)
        if bot is None:
            await update.message.reply_text("❌ Avval botni tanlang.")
            return
        await _save_channel(update, context, bot, draft["chat_id"], draft["title"], None, text)


async def _handle_channel(update, context, text):
    ref = normalize_channel_ref(text)
    if ref is None:
        await update.message.reply_text("❌ Manzil noto‘g‘ri. Masalan: @kanal_nomi")
        return
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            await update.message.reply_text("❌ Avval botni tanlang.")
            return
        token = bot.plain_token
    chat_id, title, username, problem = await subscription.describe_channel(await get_client(token), ref)
    if problem:
        await update.message.reply_text(f"❌ {problem}")
        return
    if username is None:
        user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
        await save_builder_session(
            user.id, context, pending_state=states.WAITING_FOR_CHANNEL_LINK,
            draft={"flow": "channel_link", "chat_id": chat_id, "title": title},
        )
        await update.message.reply_text(
            "🔗 Bu yopiq kanal. Foydalanuvchilar qo‘shilishi uchun taklif havolasini yuboring "
            "(<code>https://t.me/+...</code>).", parse_mode="HTML",
        )
        return
    await _save_channel(update, context, bot, chat_id, title, username, None)


async def handle_broadcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A photo/video/file sent while composing a broadcast."""
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
    if bot is None:
        await update.message.reply_text("❌ Avval botni tanlang.")
        return
    moved = await _transfer(update, context, bot)
    if moved is None:
        return
    kind, file_id = moved
    await _create_and_show(update, context, bot, text=update.message.caption_html, media_type=kind, media_file_id=file_id)
