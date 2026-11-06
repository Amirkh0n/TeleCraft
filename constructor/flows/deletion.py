from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.menus import Menu
from models.buttons import Button
from models.button_actions import ButtonAction
from core.logger import get_logger

logger = get_logger("flows.deletion")


async def delete_menu_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation dialog before deleting a menu"""
    try:
        await update.callback_query.answer()

        data = update.callback_query.data
        menu_id = int(data.replace("delete_menu_", ""))

        context.user_data["current_menu_id"] = menu_id

        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_menu_{menu_id}")],
            [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="back_to_menus")],
        ]

        await update.callback_query.message.edit_text(
            "⚠️ Menyu o'chirishni tasdiqlaysizmi?\n\n"
            "Diqqat: bu amal bekor qilib bo'lmaydi! Menudagi barcha tugmalar ham o'chiriladi.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        logger.info("Menu delete confirmation requested", menu_id=menu_id)

    except Exception as e:
        logger.error(f"Error in delete_menu_confirm: {e}", exc_info=True)


async def handle_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete menu after confirmation"""
    try:
        await update.callback_query.answer()

        data = update.callback_query.data
        menu_id = int(data.replace("confirm_delete_menu_", ""))

        async with AsyncSessionLocal() as session:
            # Menudagi tugmalarni o'chirish (action'lar bilan)
            result = await session.execute(
                select(Button).where(Button.menu_id == menu_id)
            )
            buttons = result.scalars().all()

            for button in buttons:
                action_result = await session.execute(
                    select(ButtonAction).where(ButtonAction.button_id == button.id)
                )
                action = action_result.scalar_one_or_none()
                if action:
                    session.delete(action)
                session.delete(button)

            # Menuni o'chirish
            result = await session.execute(
                select(Menu).where(Menu.id == menu_id)
            )
            menu = result.scalar_one_or_none()

            if menu:
                session.delete(menu)
                await session.commit()
                logger.info("Menu deleted", menu_id=menu_id)
                await update.callback_query.message.edit_text("✅ Menyu muvaffaqiyatli o'chirildi!")
            else:
                await update.callback_query.message.edit_text("❌ Menyu topilmadi.")

        context.user_data.pop("current_menu_id", None)

    except Exception as e:
        logger.error(f"Error handling menu deletion: {e}", exc_info=True)
        await update.callback_query.message.edit_text("❌ Menyu o'chirishda xatolik yuz berdi.")


async def delete_button_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation dialog before deleting a button"""
    try:
        await update.callback_query.answer()

        data = update.callback_query.data
        button_id = int(data.replace("delete_button_", ""))

        context.user_data["current_button_id"] = button_id

        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_button_{button_id}")],
            [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="back_to_buttons")],
        ]

        await update.callback_query.message.edit_text(
            "⚠️ Tugma o'chirishni tasdiqlaysizmi?\n\n"
            "Diqqat: bu amal bekor qilib bo'lmaydi!",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        logger.info("Button delete confirmation requested", button_id=button_id)

    except Exception as e:
        logger.error(f"Error in delete_button_confirm: {e}", exc_info=True)


async def handle_delete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete button after confirmation"""
    try:
        await update.callback_query.answer()

        data = update.callback_query.data
        button_id = int(data.replace("confirm_delete_button_", ""))

        async with AsyncSessionLocal() as session:
            # Action'ni o'chirish
            result = await session.execute(
                select(ButtonAction).where(ButtonAction.button_id == button_id)
            )
            action = result.scalar_one_or_none()
            if action:
                session.delete(action)

            # Tugmani o'chirish
            result = await session.execute(
                select(Button).where(Button.id == button_id)
            )
            button = result.scalar_one_or_none()

            if button:
                session.delete(button)
                await session.commit()
                logger.info("Button deleted", button_id=button_id)
                await update.callback_query.message.edit_text("✅ Tugma muvaffaqiyatli o'chirildi!")
            else:
                await update.callback_query.message.edit_text("❌ Tugma topilmadi.")

        context.user_data.pop("current_button_id", None)

    except Exception as e:
        logger.error(f"Error handling button deletion: {e}", exc_info=True)
        await update.callback_query.message.edit_text("❌ Tugma o'chirishda xatolik yuz berdi.")
