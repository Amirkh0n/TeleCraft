from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from constructor.states import WAITING_FOR_ACTION_TEXT, WAITING_FOR_ACTION_LINK, WAITING_FOR_ADMIN_ID
from core.database import AsyncSessionLocal
from core.validators import validate_admin_id, validate_text_length, validate_url
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from models.button_actions import ButtonAction, ActionType
from models.admin_links import AdminLink
from models.menus import Menu


async def show_action_choices(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    button_id: int,
    *,
    edit: bool = True,
):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, current_button_id=button_id)
    keyboard = [
        [InlineKeyboardButton("📝 Matn yuborish", callback_data="action_text")],
        [InlineKeyboardButton("🔗 Havola ochish", callback_data="action_link")],
        [InlineKeyboardButton("📂 Menu ochish", callback_data="action_menu")],
        [InlineKeyboardButton("👨‍💼 Adminga yuborish", callback_data="action_admin")],
        [InlineKeyboardButton("🗑 Tugmani o‘chirish", callback_data=f"delete_button_{button_id}")],
        [InlineKeyboardButton("⬅️ Tugmalar", callback_data="back_to_buttons")],
    ]
    await show_screen(update, "Bu tugma bosilganda nima bo‘lsin?", keyboard, edit=edit)


async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    button_id = int(update.callback_query.data.split("_", 1)[1])
    await show_action_choices(update, context, button_id)


async def action_text_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, pending_state=WAITING_FOR_ACTION_TEXT, draft={"flow": "action_text"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 Tugma bosilganda yuboriladigan matnni kiriting.")


async def save_button_action(session, button_id, action_type, value):
    result = await session.execute(select(ButtonAction).where(ButtonAction.button_id == button_id))
    existing = result.scalar_one_or_none()
    if existing:
        existing.action_type = action_type
        existing.value = value
    else:
        session.add(ButtonAction(button_id=button_id, action_type=action_type, value=value))
    await session.commit()


async def return_to_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from constructor.flows.buttons import show_buttons_for_menu
    await show_buttons_for_menu(update, context, context.user_data.get("current_menu_id"), edit=False)


async def handle_action_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ACTION_TEXT:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        text = validate_text_length(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Matn bo‘sh bo‘lmasin. Qayta yuboring.")
        return
    async with AsyncSessionLocal() as session:
        await save_button_action(session, context.user_data.get("current_button_id"), ActionType.text, text)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await update.message.reply_text("✅ Matn action saqlandi.")
    await return_to_buttons(update, context)


async def action_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Menu).where(Menu.bot_id == bot_id).order_by(Menu.position, Menu.id))
        menus = result.scalars().all()
    keyboard = [[InlineKeyboardButton(menu.title, callback_data=f"select_menu_{menu.id}")] for menu in menus]
    keyboard.append([InlineKeyboardButton("⬅️ Actionlar", callback_data=f"button_{context.user_data.get('current_button_id')}")])
    await show_screen(update, "Qaysi menu ochilsin?", keyboard)


async def select_menu_for_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_id = int(update.callback_query.data.split("_", 2)[2])
    button_id = context.user_data.get("current_button_id")
    async with AsyncSessionLocal() as session:
        await save_button_action(session, button_id, ActionType.menu, str(menu_id))
    await show_action_choices(update, context, button_id)


async def action_link_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, pending_state=WAITING_FOR_ACTION_LINK, draft={"flow": "action_link"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🔗 URL manzilini yuboring. Masalan: https://example.com")


async def handle_action_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ACTION_LINK:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        url = validate_url(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Havola https:// bilan boshlanishi kerak. Qayta yuboring.")
        return
    async with AsyncSessionLocal() as session:
        await save_button_action(session, context.user_data.get("current_button_id"), ActionType.link, url)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await update.message.reply_text("✅ Havola action saqlandi.")
    await return_to_buttons(update, context)


async def action_admin_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, pending_state=WAITING_FOR_ADMIN_ID, draft={"flow": "action_admin"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("👨‍💼 Adminning Telegram ID raqamini yuboring.")


async def handle_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_ADMIN_ID:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        admin_id = validate_admin_id(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Telegram ID raqam bo‘lishi kerak. Qayta yuboring.")
        return
    button_id = context.user_data.get("current_button_id")
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AdminLink).where(AdminLink.bot_id == bot_id, AdminLink.admin_tg_id == admin_id)
        )
        if result.scalar_one_or_none() is None:
            session.add(AdminLink(bot_id=bot_id, admin_tg_id=admin_id))
        await save_button_action(session, button_id, ActionType.admin, str(admin_id))
    await save_builder_session(user.id, context, pending_state="", draft={})
    await update.message.reply_text("✅ Admin action saqlandi.")
    await return_to_buttons(update, context)
