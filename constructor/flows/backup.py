"""``/backup``: an admin of the main bot asks for a database backup right now."""
from telegram import Update
from telegram.ext import ContextTypes

from core import backup
from core.config import settings
from core.database import engine
from core.logger import get_logger

logger = get_logger("constructor.backup")


async def backup_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in settings.admin_ids_list:
        return  # silently ignored: the command is not advertised to anyone else
    await update.message.reply_text("⏳ Zaxira nusxa tayyorlanmoqda...")
    try:
        sent = await backup.send_backup(context.bot, [user.id], engine)
    except Exception as exc:
        logger.exception("manual backup failed")
        await update.message.reply_text(f"❌ Zaxira nusxa yaratilmadi: {exc}")
        return
    if not sent:
        await update.message.reply_text("❌ Faylni yuborib bo'lmadi.")
