from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.users import User
from models.bots import Bot
from core.logger import get_logger
from core.permissions import check_user_permission, get_user_role
from core.validators import validate_bot_token, validate_user_id, validate_menu_id, validate_menu_title, validate_text_length, validate_button_text, validate_action_type, validate_action_value, validate_admin_id
from core.analytics import track_event
from enum import Enum

logger = get_logger("handlers")


class UserStates(Enum):
    WAITING_FOR_TOKEN = "waiting_for_token"
    WAITING_FOR_MENU_NAME = "waiting_for_menu_name"
    WAITING_FOR_BUTTON_TEXT = "waiting_for_button_text"
    WAITING_FOR_ACTION_TEXT = "waiting_for_action_text"
    WAITING_FOR_ACTION_LINK = "waiting_for_action_link"
    WAITING_FOR_ADMIN_ID = "waiting_for_admin_id"


async def show_user_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, back=False):
    """Show list of user's bots with improved UX"""
    try:
        tg_user = update.effective_user
        user_id = tg_user.id
        
        if not await check_user_permission(user_id):
            await update.message.reply_text(
                "Access denied: You don't have permission to access bots.",
                parse_mode="HTML"
            )
            return
            
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                await update.message.reply_text(
                    "❌ Foydalanuvchi topilmadi.",
                    parse_mode="HTML"
                )
                return

            result = await session.execute(
                select(Bot).where(Bot.owner_id == user.id)
            )
            bots = result.scalars().all()
        
        if not bots:
            await update.message.reply_text(
                "📭 Sizda hali botlar yo'q.\n\n"
                "Yangi bot qo'shish uchun ➕ tugmasini bosing.",
                parse_mode="HTML"
            )
            return
            
        keyboard = []
        for bot in bots:
            keyboard.append(
                [InlineKeyboardButton(bot.name, callback_data=f"bot_{bot.id}")]
            )
        
        keyboard.append(
            [InlineKeyboardButton("➕ Yangi bot", callback_data="add_bot")]
        )
        
        keyboard.append(
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel")]
        )
        
        if back:
            await update.callback_query.edit_message_text(
                "📂 Sizning botlaringiz:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await update.message.reply_text(
            "📂 Sizning botlaringiz:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logger.info(f"User {user_id} viewed their bots", user_id=user_id, bot_count=len(bots))
        
    except Exception as e:
        logger.error(f"Error showing user bots: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Xatolik yuz berdi. Qayta urinib ko'ring.",
            parse_mode="HTML"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        tg_user = update.effective_user
        user_id = tg_user.id
        
        if not await check_user_permission(user_id):
            await update.message.reply_text(
                "❌ Sizga kirish huquqi yo'q.",
                parse_mode="HTML"
            )
            return
        
        await show_user_bots(update, context)
        
        logger.info(f"User {user_id} started the bot", user_id=user_id)
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Xatolik yuz berdi.",
            parse_mode="HTML"
        )


async def add_bot_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add bot button click"""
    try:
        await update.callback_query.answer()
        context.user_data["state"] = UserStates.WAITING_FOR_TOKEN
        
        await update.callback_query.message.reply_text(
            "🔑 BotFather'dan olgan tokenni yuboring:",
            parse_mode="HTML"
        )
        
        logger.info("User started adding a new bot", user_id=update.effective_user.id)
        
    except Exception as e:
        logger.error(f"Error in add_bot_click: {e}", exc_info=True)
        await update.callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle token input"""
    try:
        if context.user_data.get("state") != UserStates.WAITING_FOR_TOKEN:
            return
        
        token = update.message.text
        tg_user = update.effective_user
        user_id = tg_user.id
        
        # Validate token
        try:
            validated_token = validate_bot_token(token)
        except Exception as e:
            await update.message.reply_text(f"❌ Xato: {str(e)}")
            return
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(tg_id=user_id, full_name=tg_user.full_name)
                session.add(user)
                await session.flush()
            
            bot = Bot(
                owner_id=user.id,
                name=f"Bot {len(user.bots) + 1}",
                token=validated_token,
                is_active=True,
            )
            session.add(bot)
            await session.commit()
            
            logger.info(f"New bot created: {bot.name}", bot_id=bot.id, user_id=user_id)
        
        await update.message.reply_text(
            "✅ Bot muvaffaqiyatli qo'shildi!\n\n"
            "Botni boshqarish uchun bosing:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Boshqarish", callback_data=f"bot_{bot.id}")]
            ]),
            parse_mode="HTML"
        )
        
        context.user_data.clear()
        
    except Exception as e:
        logger.error(f"Error handling token: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Bot qo'shishda xatolik yuz berdi. Qayta urinib ko'ring."
        )


async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel action"""
    try:
        await update.callback_query.answer()
        context.user_data.clear()
        await update.callback_query.message.reply_text(
            "❌ Amal bekor qilindi."
        )
    except Exception as e:
        logger.error(f"Error in cancel action: {e}", exc_info=True)
