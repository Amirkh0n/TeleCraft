from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, Bot as TgBot
from telegram.ext import ContextTypes
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.users import User
from models.bots import Bot
from core.logger import get_logger
from core.permissions import check_user_permission
from core.validators import validate_bot_token
from core.config import settings
from core.webhook_manager import set_webhook
from constructor.states import WAITING_FOR_TOKEN

logger = get_logger("handlers")


def build_webhook_url(token: str) -> str:
    """Build webhook URL for a user bot"""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/webhook/{token}"


async def show_user_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, back=False):
    """Show list of user's bots with improved UX"""
    try:
        tg_user = update.effective_user
        user_id = tg_user.id

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                message = "📭 Sizda hali botlar yo'q.\n\n➕ Yangi bot qo'shing."
                keyboard = [[InlineKeyboardButton("➕ Yangi bot", callback_data="add_bot")]]
            else:
                result = await session.execute(
                    select(Bot).where(Bot.owner_id == user.id)
                )
                bots = result.scalars().all()

                if not bots:
                    message = "📭 Sizda hali botlar yo'q.\n\n➕ Yangi bot qo'shing."
                    keyboard = [[InlineKeyboardButton("➕ Yangi bot", callback_data="add_bot")]]
                else:
                    message = "📂 Sizning botlaringiz:"
                    keyboard = [
                        [InlineKeyboardButton(bot.name, callback_data=f"bot_{bot.id}")]
                        for bot in bots
                    ]
                    keyboard.append([InlineKeyboardButton("➕ Yangi bot", callback_data="add_bot")])

        markup = InlineKeyboardMarkup(keyboard)

        if back and update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                message,
                reply_markup=markup
            )
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                message,
                reply_markup=markup
            )
        elif update.message:
            await update.message.reply_text(
                message,
                reply_markup=markup
            )

        logger.info(f"User {user_id} viewed their bots")

    except Exception as e:
        logger.error(f"Error showing user bots: {e}", exc_info=True)
        if update.message:
            await update.message.reply_text("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        tg_user = update.effective_user
        user_id = tg_user.id

        await show_user_bots(update, context)
        logger.info(f"User {user_id} started the bot")

    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text("❌ Xatolik yuz berdi.")


async def add_bot_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding a new bot"""
    try:
        await update.callback_query.answer()
        context.user_data["state"] = WAITING_FOR_TOKEN

        await update.callback_query.message.reply_text(
            "🔑 BotFather'dan olgan tokenni yuboring:"
        )
        logger.info("User started adding a new bot", user_id=update.effective_user.id)

    except Exception as e:
        logger.error(f"Error in add_bot_click: {e}", exc_info=True)
        await update.callback_query.answer("❌ Xatolik yuz berdi", show_alert=True)


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle token input + avtomatik setWebhook"""
    try:
        if context.user_data.get("state") != WAITING_FOR_TOKEN:
            return

        token = update.message.text
        tg_user = update.effective_user
        user_id = tg_user.id

        try:
            validated_token = validate_bot_token(token)
        except Exception as e:
            await update.message.reply_text(f"❌ Xato: {str(e)}")
            return

        # 1. Tokenni Telegram API orqali tekshirish va bot nomini olish
        bot_name = None
        try:
            tg_check = TgBot(validated_token)
            me = await tg_check.get_me()
            bot_name = me.first_name or me.username or f"Bot_{user_id}"
        except Exception as e:
            logger.warning(f"Could not verify token via Telegram API: {e}")
            await update.message.reply_text(
                "❌ Token noto'g'ri yoki Telegram bilan aloqa yo'q.\n"
                "BotFather'dan to'g'ri tokenni yuboring."
            )
            return

        # 2. Webhook URL qurish va avtomatik setWebhook
        webhook_url = build_webhook_url(validated_token)
        webhook_ok = await set_webhook(validated_token, webhook_url)

        # 3. DB ga saqlash
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                user = User(tg_id=user_id, full_name=tg_user.full_name)
                session.add(user)
                await session.flush()

            # Token allaqachon mavjud bo'lsa yangilash
            result = await session.execute(
                select(Bot).where(Bot.token == validated_token)
            )
            bot = result.scalar_one_or_none()

            if bot:
                bot.name = bot_name
                bot.is_active = True
                bot.webhook_url = webhook_url if webhook_ok else bot.webhook_url
                bot.webhook_set = webhook_ok or bot.webhook_set
                logger.info(f"Bot re-added: {bot.name}", bot_id=bot.id)
            else:
                bot = Bot(
                    owner_id=user.id,
                    name=bot_name,
                    token=validated_token,
                    is_active=True,
                    webhook_url=webhook_url if webhook_ok else None,
                    webhook_set=webhook_ok,
                )
                session.add(bot)
                await session.flush()
                logger.info(f"New bot created: {bot.name}", bot_id=bot.id)

            await session.commit()
            bot_id = bot.id

        context.user_data["current_bot_id"] = bot_id
        context.user_data["state"] = None

        # 4. Natija xabari
        if webhook_ok:
            status_text = "🔔 Webhook avtomatik o'rnatildi — bot tayyor! 🚀"
        else:
            status_text = (
                "⚠️ Webhook o'rnatilmadi.\n"
                f"PUBLIC_BASE_URL sozlanmagan bo'lishi mumkin.\n"
                f"URL: {webhook_url}"
            )

        await update.message.reply_text(
            f"✅ <b>{bot_name}</b> qo'shildi!\n\n"
            f"{status_text}\n\n"
            "Botni boshqarish uchun bosing:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Boshqarish", callback_data=f"bot_{bot_id}")]
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
        await update.callback_query.message.reply_text("❌ Amal bekor qilindi.")
    except Exception as e:
        logger.error(f"Error in cancel action: {e}", exc_info=True)
