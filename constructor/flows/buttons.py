from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func

from core.database import AsyncSessionLocal
from core.validators import validate_button_text
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.states import WAITING_FOR_BUTTON_TEXT
from constructor.ui import show_screen
from models.buttons import Button
from models.menus import Menu


async def show_buttons_for_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    menu_id: int,
    *,
    edit: bool = True,
):
    async with AsyncSessionLocal() as session:
        menu_result = await session.execute(select(Menu).where(Menu.id == menu_id))
        menu = menu_result.scalar_one_or_none()
        if menu is None:
            await update.message.reply_text("❌ Menu topilmadi.")
            return
        result = await session.execute(
            select(Button).where(Button.menu_id == menu_id).order_by(Button.position, Button.id)
        )
        buttons = result.scalars().all()

    keyboard = [
        [InlineKeyboardButton(f"🔘 {button.text}", callback_data=f"button_{button.id}")]
        for button in buttons
    ]
    keyboard.extend([
        [InlineKeyboardButton("➕ Tugma qo‘shish", callback_data="add_button")],
        [InlineKeyboardButton("📝 Menu xabarini tahrirlash", callback_data="edit_menu_message")],
        [InlineKeyboardButton("⬅️ Menyular", callback_data="menus")],
    ])
    if not menu.is_start:
        keyboard.insert(-1, [InlineKeyboardButton("🗑 Menu o‘chirish", callback_data=f"delete_menu_{menu.id}")])
    await show_screen(
        update,
        f"🔘 {menu.title}\n\nTugmani tanlab uning action’ini sozlang.",
        keyboard,
        edit=edit,
    )


async def show_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data.startswith("menu_"):
        menu_id = int(data.split("_", 1)[1])
    else:
        menu_id = context.user_data.get("current_menu_id")
    if not menu_id:
        await update.callback_query.message.reply_text("Avval menu tanlang.")
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    await save_builder_session(user.id, context, current_menu_id=menu_id)
    await show_buttons_for_menu(update, context, menu_id)


async def add_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        pending_state=WAITING_FOR_BUTTON_TEXT,
        draft={"flow": "new_button"},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🔘 Tugma ustida yoziladigan matnni yuboring.\nMasalan: Narxlar"
    )


async def handle_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_FOR_BUTTON_TEXT:
        return
    tg_user = update.effective_user
    user = await ensure_constructor_user(tg_user.id, tg_user.full_name)
    try:
        text = validate_button_text(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Tugma matni bo‘sh bo‘lmasin. Qayta yuboring.")
        return
    menu_id = context.user_data.get("current_menu_id")
    async with AsyncSessionLocal() as session:
        max_position = (await session.execute(
            select(func.coalesce(func.max(Button.position), -1)).where(Button.menu_id == menu_id)
        )).scalar_one()
        button = Button(menu_id=menu_id, text=text, position=max_position + 1)
        session.add(button)
        await session.commit()
        await session.refresh(button)

    await save_builder_session(
        user.id,
        context,
        current_menu_id=menu_id,
        current_button_id=button.id,
        pending_state="",
        draft={},
    )
    from constructor.flows.actions import show_action_choices
    await show_action_choices(update, context, button.id, edit=False)
