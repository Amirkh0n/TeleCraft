"""Main bot: the invite-a-friend screen and the notices to the inviter."""
from urllib.parse import quote

from telegram import InlineKeyboardButton as Btn, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from constructor.session import ensure_constructor_user
from constructor.ui import show_screen
from core import referrals
from core.database import AsyncSessionLocal
from core.logger import get_logger

logger = get_logger("constructor.referral")


def bar(done: int, need: int) -> str:
    return "🟩" * min(done, need) + "⬜" * max(0, need - done)


async def show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    if update.callback_query:
        await update.callback_query.answer()
    username = context.bot.username or ""
    async with AsyncSessionLocal() as session:
        data = await referrals.info(session, user, username)
    text = (f"🎁 <b>Do‘st taklif qiling — {data['reward']} bepul</b>\n\n"
            f"Havolangiz orqali {data['need']} ta do‘stingiz kirib, har biri o‘z botini yaratsa, sizga {data['reward']} tarifi beriladi.\n\n"
            f"{bar(data['done'], data['need'])}\n"
            f"Bot yaratganlar: <b>{data['done']}</b> / {data['need']}"
            + (f" · hali bot yaratmaganlar: {data['joined']}" if data["joined"] else ""))
    if data["rewarded"]:
        text += "\n\n✅ Mukofot olingan."
    rows = []
    if data["link"]:
        text += f"\n\n🔗 <code>{data['link']}</code>"
        share = f"https://t.me/share/url?url={quote(data['link'])}&text={quote('Kod yozmasdan Telegram bot yarating:')}"
        rows.append([Btn("📤 Do‘stlarga yuborish", url=share)])
    rows.append([Btn("🏠 Bosh menyu", callback_data="home")])
    await show_screen(update, text, rows, edit=bool(update.callback_query))


async def friend_built_bot(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """A friend of someone just created a first bot: count it and tell the inviter."""
    try:
        async with AsyncSessionLocal() as session:
            res = await referrals.activate(session, user_id)
        if res is None:
            return
        if res["rewarded"]:
            text = f"🎉 {res['done']} ta do‘stingiz bot yaratdi! Sizga {referrals.REWARD_DAYS} kunlik Start tarifi berildi."
        else:
            text = f"👥 Do‘stingiz bot yaratdi: {res['done']} / {referrals.NEED}"
        await context.bot.send_message(chat_id=res["tg_id"], text=text)
    except TelegramError:
        logger.info("Could not notify the inviter")
    except Exception:
        logger.exception("Referral activation failed")
