from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.menus import Menu
from models.buttons import Button
from core.logger import get_logger
from core.analytics import track_event

logger = get_logger("flows")


async def delete_menu_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation dialog before deleting a menu"""
    try:
        await update.callback_query.answer()
        
        data = update.callback_query.data
        menu_id = int(data.split("_")[1])
        
        context.user_data["current_menu_id"] = menu_id
        
        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_menu_{menu_id}")],
            [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="cancel")]
        ]
        
        await update.callback_query.message.edit_text(
            "⚠️ Menuni o'chirishni tasdiqlaysizmi?\n\n"
            "Bu amal bekor qilib bo'lmaydi!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
        logger.info(f"User requesting menu deletion confirmation", menu_id=menu_id, user_id=update.effective_user.id)
        
    except Exception as e:
        logger.error(f"Error in delete_menu_confirm: {e}", exc_info=True)


async def handle_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu deletion confirmation"""
    try:
        await update.callback_query.answer()
        
        data = update.callback_query.data
        menu_id = int(data.split("_")[2])
        
        async with AsyncSessionLocal() as session:
            # Delete all buttons belonging to this menu
            result = await session.execute(
                select(Button).where(Button.menu_id == menu_id)
            )
            buttons = result.scalars().all()
            
            for button in buttons:
                session.delete(button)
            
            # Delete the menu
            result = await session.execute(
                select(Menu).where(Menu.id == menu_id)
            )
            menu = result.scalar_one_or_none()
            
            if menu:
                session.delete(menu)
                await session.commit()
                
                logger.info(f"Menu deleted successfully", menu_id=menu_id, user_id=update.effective_user.id)
                
                await update.callback_query.message.edit_text(
                    "✅ Menyu muvaffaqiyatli o'chirildi!",
                    parse_mode="HTML"
                )
            else:
                await update.callback_query.message.edit_text(
                    "❌ Menyu topilmadi.",
                    parse_mode="HTML"
                )
        
        context.user_data.clear()
        
    except Exception as e:
        logger.error(f"Error handling menu deletion: {e}", exc_info=True)
        await update.callback_query.message.edit_text(
            "❌ Menyu o'chirishda xatolik yuz berdi.",
            parse_mode="HTML"
        )


async def delete_button_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation dialog before deleting a button"""
    try:
        await update.callback_query.answer()
        
        data = update.callback_query.data
        button_id = int(data.split("_")[1])
        
        context.user_data["current_button_id"] = button_id
        
        keyboard = [
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"confirm_delete_button_{button_id}")],
            [InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="cancel")]
        ]
        
        await update.callback_query.message.edit_text(
            "⚠️ Tugmani o'chirishni tasdiqlaysizmi?\n\n"
            "Bu amal bekor qilib bo'lmaydi!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
        logger.info(f"User requesting button deletion confirmation", button_id=button_id, user_id=update.effective_user.id)
        
    except Exception as e:
        logger.error(f"Error in delete_button_confirm: {e}", exc_info=True)


async def handle_delete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button deletion confirmation"""
    try:
        await update.callback_query.answer()
        
        data = update.callback_query.data
        button_id = int(data.split("_")[2])
        
        async with AsyncSessionLocal() as session:
            # Delete the button action first
            result = await session.execute(
                select()
                .from()
                .where(ButtonAction.button_id == button_id)
            )
            
            # Delete button action
            result = await session.execute(
                select(ButtonAction).where(ButtonAction.button_id == button_id)
            )
            button_action = result.scalar_one_or_none()
            
            if button_action:
                session.delete(button_action)
            
            # Delete the button
            result = await session.execute(
                select(Button).where(Button.id == button_id)
            )
            button = result.scalar_one_or_none()
            
            if button:
                session.delete(button)
                await session.commit()
                
                logger.info(f"Button deleted successfully", button_id=button_id, user_id=update.effective_user.id)
                
                await update.callback_query.message.edit_text(
                    "✅ Tugma muvaffaqiyatli o'chirildi!",
                    parse_mode="HTML"
                )
            else:
                await update.callback_query.message.edit_text(
                    "❌ Tugma topilmadi.",
                    parse_mode="HTML"
                )
        
        context.user_data.clear()
        
    except Exception as e:
        logger.error(f"Error handling button deletion: {e}", exc_info=True)
        await update.callback_query.message.edit_text(
            "❌ Tugma o'chirishda xatolik yuz berdi.",
            parse_mode="HTML"
        )
