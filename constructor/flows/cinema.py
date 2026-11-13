"""Builder panels for cinema mode and bot admins.

Movies are managed inside the child bot (``/admin``); here the owner only switches the mode on
and decides who the admins are.
"""
import html
import re

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from constructor import states
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from constructor.flows.audience import normalize_channel_ref
from engine import cinema as cinema_engine
from engine import subscription
from engine.telegram_client import get_client
from models.admin_links import AdminLink
from models.bots import Bot
from models.movies import KIND_CINEMA, KIND_STANDARD, Movie
from models.users import User

MAX_ADMINS = 20
TG_ID_RE = re.compile(r"^\d{5,15}$")


# ---------------------------------------------------------------- pure / db helpers

def parse_tg_id(text: str) -> int:
    text = (text or "").strip()
    if not TG_ID_RE.match(text):
        raise ValueError("Telegram ID faqat raqamlardan iborat bo‘ladi (masalan 123456789).")
    return int(text)


async def set_kind(session, bot, kind: str) -> None:
    from engine import booking as booking_engine
    from engine import quiz as quiz_engine
    from engine import course as course_engine
    from engine import shop as shop_engine
    from models.booking import KIND_BOOKING
    from models.course import KIND_COURSE
    from models.shop import KIND_SHOP
    from models.quiz import KIND_QUIZ
    bot.kind = kind
    welcomes = {KIND_CINEMA: cinema_engine.WELCOME, KIND_BOOKING: booking_engine.WELCOME, KIND_QUIZ: quiz_engine.WELCOME,
                KIND_COURSE: course_engine.WELCOME, KIND_SHOP: shop_engine.WELCOME}
    if kind in welcomes:
        if kind == KIND_BOOKING:
            await booking_engine.ensure_setup(session, bot)
        elif kind == KIND_QUIZ:
            await quiz_engine.ensure_setup(session, bot)
        elif kind == KIND_COURSE:
            await course_engine.ensure_setup(session, bot)
        elif kind == KIND_SHOP:
            await shop_engine.ensure_setup(session, bot)
        menu = await cinema_engine.ensure_start_menu(session, bot, welcomes[kind])
        if menu.message_text in welcomes.values():  # still a default text of another mode: swap it
            menu.message_text = welcomes[kind]
    await session.commit()


async def save_channel(session, bot, chat_id: int, title: str) -> None:
    bot.movie_channel_id, bot.movie_channel_title = chat_id, title[:255]
    await session.commit()


async def clear_channel(session, bot) -> None:
    bot.movie_channel_id = bot.movie_channel_title = None
    await session.commit()


async def list_admins(session, bot) -> list[int]:
    return list((await session.execute(
        select(AdminLink.admin_tg_id).where(AdminLink.bot_id == bot.id).order_by(AdminLink.id)
    )).scalars().all())


async def add_admin(session, bot, tg_id: int, owner_tg_id: int) -> str | None:
    """Returns a user-facing problem, or ``None`` when the admin was added."""
    if tg_id == owner_tg_id:
        return "Siz bot egasisiz — sizni admin qilib qo‘shish shart emas, sizda barcha huquqlar bor."
    current = await list_admins(session, bot)
    if tg_id in current:
        return "Bu foydalanuvchi allaqachon admin."
    if len(current) >= MAX_ADMINS:
        return f"Adminlar soni {MAX_ADMINS} tadan oshmasligi kerak."
    session.add(AdminLink(bot_id=bot.id, admin_tg_id=tg_id))
    await session.commit()
    return None


async def remove_admin(session, bot, tg_id: int) -> bool:
    links = (await session.execute(
        select(AdminLink).where(AdminLink.bot_id == bot.id, AdminLink.admin_tg_id == tg_id)
    )).scalars().all()
    for link in links:
        await session.delete(link)
    await session.commit()
    return bool(links)


async def _current_bot(session, update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    if not bot_id:
        return None
    return (await session.execute(
        select(Bot).join(User, User.id == Bot.owner_id).where(Bot.id == bot_id, User.tg_id == update.effective_user.id)
    )).scalar_one_or_none()


async def _no_bot(update: Update):
    await update.callback_query.answer("Avval botni tanlang.", show_alert=True)


def _back(bot_id: int):
    return [InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot_id}")]


# ---------------------------------------------------------------- cinema mode

async def cinema_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        count = (await session.execute(select(func.count(Movie.id)).where(Movie.bot_id == bot.id))).scalar() or 0
    if bot.kind == KIND_CINEMA:
        username = f"@{bot.username}" if bot.username else "child bot"
        text = (
            "🎬 <b>Kino bot rejimi: yoqilgan</b>\n\n"
            f"Kinolar: <b>{count}</b>\n"
            f"Kino kanal: <b>{html.escape(bot.movie_channel_title) if bot.movie_channel_id else 'ulanmagan'}</b>\n\n"
            "Kino qo‘shish, tahrirlash va o‘chirish <b>child botning o‘zida</b> bajariladi:\n"
            f"1. {username} ga kiring\n2. <code>/admin</code> yuboring\n3. «➕ Kino qo‘shish» → video yuboring → kod va nom kiriting.\n\n"
            "Kino videosi Telegram <code>file_id</code> sifatida saqlanadi va shu orqali yuboriladi. "
            "Admin qo‘shish uchun «👮 Adminlar» bo‘limidan foydalaning."
        )
        keyboard = [
            [InlineKeyboardButton("📢 Kino kanalni almashtirish" if bot.movie_channel_id else "📢 Kino kanal ulash",
                                  callback_data="cin:ch")],
            *([[InlineKeyboardButton("🗑 Kanalni uzish", callback_data="cin:chdel")]] if bot.movie_channel_id else []),
            [InlineKeyboardButton("👮 Adminlar", callback_data="adm:home")],
            [InlineKeyboardButton("🔙 Oddiy rejimga qaytish", callback_data="cin:off")],
        ]
        if bot.username:
            keyboard.insert(0, [InlineKeyboardButton("🤖 Botni ochish", url=f"https://t.me/{bot.username}")])
    else:
        text = (
            "🎬 <b>Kino bot</b>\n\nBot kino katalogiga aylanadi: foydalanuvchi kino <b>kodini</b> yoki "
            "<b>nomini</b> yozadi va videoni oladi. Kinolarni adminlar botning o‘zida boshqaradi.\n\n"
            "⚠️ Rejim yoqilganda menyu/tugmalar o‘rniga kino qidiruvi ishlaydi (menyularingiz o‘chmaydi)."
            + ("\n\n⚠️ Hozir <b>bron bot</b> rejimi yoqilgan; kino botga o‘tsangiz, u o‘chadi (bronlar saqlanadi)." if bot.kind == "booking" else "")
        )
        keyboard = [[InlineKeyboardButton("✅ Kino botga aylantirish", callback_data="cin:on")]]
    keyboard.append(_back(bot.id))
    await show_screen(update, text, keyboard)


async def cinema_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = KIND_CINEMA if update.callback_query.data == "cin:on" else KIND_STANDARD
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await set_kind(session, bot, kind)
    await cinema_home(update, context)
    if kind == KIND_CINEMA and not bot.movie_channel_id:
        await _ask_channel(update, context, via_message=True)  # offered right away when the mode is enabled


async def _ask_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_message: bool = False):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_MOVIE_CHANNEL, draft={"flow": "movie_channel"})
    target = update.callback_query.message
    await target.reply_text(
        "📢 Yangi kinolar e’lon qilinadigan <b>kanalni</b> yuboring: <code>@kanal_nomi</code> yoki <code>t.me/kanal_nomi</code>.\n"
        "Avval child botni shu kanalga <b>administrator</b> qiling (xabar yuborish huquqi bilan). "
        "Yopiq kanal bo‘lsa, raqamli ID (<code>-100...</code>) yuboring.\n"
        "Hozircha kerak bo‘lmasa: /cancel",
        parse_mode="HTML",
    )


async def channel_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        if await _current_bot(session, update, context) is None:
            return await _no_bot(update)
    await update.callback_query.answer()
    await _ask_channel(update, context)


async def channel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await clear_channel(session, bot)
    await cinema_home(update, context)


async def handle_channel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = normalize_channel_ref(update.message.text)
    if ref is None:
        await update.message.reply_text("❌ Manzil noto‘g‘ri. Masalan: @kanal_nomi")
        return
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            await update.message.reply_text("❌ Avval botni tanlang.")
            return
        token = bot.plain_token
        chat_id, title, _username, problem = await subscription.describe_channel(await get_client(token), ref)
        if problem:
            await update.message.reply_text(f"❌ {problem}")
            return
        await save_channel(session, bot, chat_id, title)
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await update.message.reply_text(f"✅ Kino kanal ulandi: {html.escape(title)}. Endi yangi kinolar shu yerga e’lon qilinadi.", parse_mode="HTML")


# ---------------------------------------------------------------- admins

async def admins_home(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = True):
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        admins = await list_admins(session, bot)
    lines = ["👮 <b>Adminlar</b>", "", f"👑 Egasi: <code>{update.effective_user.id}</code> (siz)"]
    lines += [f"• <code>{tg_id}</code>" for tg_id in admins]
    if not admins:
        lines.append("\nQo‘shimcha adminlar yo‘q.")
    lines += ["", "Adminlar child botda <code>/admin</code> orqali kinolarni boshqara oladi va "
                  "forma/xabarlar haqida bildirishnoma oladi."]
    keyboard = [[InlineKeyboardButton(f"❌ {tg_id}", callback_data=f"adm:del:{tg_id}")] for tg_id in admins]
    keyboard.append([InlineKeyboardButton("➕ Admin qo‘shish", callback_data="adm:add")])
    keyboard.append(_back(bot.id))
    await show_screen(update, "\n".join(lines), keyboard, edit=edit)


async def admin_add_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_BOT_ADMIN, draft={"flow": "bot_admin"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "👮 Yangi adminning <b>Telegram ID</b> raqamini yuboring (masalan <code>123456789</code>).\n"
        "ID ni @userinfobot orqali bilish mumkin. Bekor qilish: /cancel",
        parse_mode="HTML",
    )


async def admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = int(update.callback_query.data.rsplit(":", 1)[1])
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            return await _no_bot(update)
        await remove_admin(session, bot, tg_id)
    await admins_home(update, context)


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    try:
        tg_id = parse_tg_id(text)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    async with AsyncSessionLocal() as session:
        bot = await _current_bot(session, update, context)
        if bot is None:
            await update.message.reply_text("❌ Avval botni tanlang.")
            return
        problem = await add_admin(session, bot, tg_id, update.effective_user.id)
    if problem:
        await update.message.reply_text(f"❌ {problem}")
        return
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await update.message.reply_text("✅ Admin qo‘shildi.")
    await admins_home(update, context, edit=False)
