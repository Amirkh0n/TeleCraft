from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func

from core.database import AsyncSessionLocal
from core.validators import validate_menu_title, validate_text_length
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.states import WAITING_FOR_MENU_NAME, WAITING_FOR_MENU_MESSAGE
from constructor.ui import show_screen
from models.menus import Menu


async def show_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    if not bot_id:
        await update.callback_query.message.reply_text("Avval botni tanlang.")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Menu).where(Menu.bot_id == bot_id).order_by(Menu.is_start.desc(), Menu.position, Menu.id)
        )
        menus = result.scalars().all()

    keyboard = [
        [InlineKeyboardButton(
            f"{'🏠 ' if menu.is_start else '📂 '}{menu.title}",
            callback_data=f"menu_{menu.id}",
        )]
        for menu in menus
    ]
    keyboard.extend([
        [InlineKeyboardButton("➕ Menu qo‘shish", callback_data="add_menu")],
        [InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot_id}")],
    ])
    await show_screen(update, "📂 Menyular\n\nMenyuni tanlab uning tugmalarini boshqaring.", keyboard)


async def add_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, pending_state=WAITING_FOR_MENU_NAME, draft={"flow": "new_menu"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "📂 Yangi menu nomini yuboring.\nMasalan: Xizmatlar yoki Biz haqimizda."
    )


async def edit_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_id = context.user_data.get("current_menu_id")
    if not menu_id:
        await update.callback_query.answer("Avval menu tanlang.", show_alert=True)
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(
        user.id,
        context,
        current_menu_id=menu_id,
        pending_state=WAITING_FOR_MENU_MESSAGE,
        draft={"flow": "edit_menu_message"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 Menu ochilganda ko‘rinadigan yangi xabarni yuboring.")


async def handle_menu_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_MENU_NAME:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        title = validate_menu_title(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Menu nomi bo‘sh bo‘lmasin. Qayta yuboring.")
        return

    bot_id = context.user_data.get("current_bot_id")
    if not bot_id:
        await update.message.reply_text("❌ Bot tanlanmagan. /start yuborib botingizni oching.")
        return
    async with AsyncSessionLocal() as session:
        position = (await session.execute(
            select(func.coalesce(func.max(Menu.position), -1)).where(Menu.bot_id == bot_id)
        )).scalar_one() + 1
        menu = Menu(bot_id=bot_id, title=title, message_text=None, is_start=False, position=position)
        session.add(menu)
        await session.commit()
        await session.refresh(menu)

    await save_builder_session(
        user.id,
        context,
        current_bot_id=bot_id,
        current_menu_id=menu.id,
        pending_state=WAITING_FOR_MENU_MESSAGE,
        draft={"flow": "new_menu"},
    )
    await update.message.reply_text(
        f"✅ <b>{title}</b> menu yaratildi.\n\nEndi u ochilganda ko‘rinadigan xabarni yuboring.",
        parse_mode="HTML",
    )


async def handle_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_MENU_MESSAGE:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        message_text = validate_text_length(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Xabar bo‘sh bo‘lmasin. Qayta yuboring.")
        return
    menu_id = context.user_data.get("current_menu_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Menu).where(Menu.id == menu_id))
        menu = result.scalar_one_or_none()
        if menu is None:
            await update.message.reply_text("❌ Menu topilmadi.")
            return
        menu.message_text = message_text
        await session.commit()
        bot_id = menu.bot_id

    await save_builder_session(
        user.id,
        context,
        current_bot_id=bot_id,
        current_menu_id=menu_id,
        pending_state="",
        draft={},
    )
    await show_screen(
        update,
        f"✅ <b>{menu.title}</b> tayyor. Endi unga tugma qo‘shishingiz mumkin.",
        [[InlineKeyboardButton("➕ Tugma qo‘shish", callback_data="add_button")],
         [InlineKeyboardButton("📂 Menyular", callback_data="menus")]],
        edit=False,
    )
