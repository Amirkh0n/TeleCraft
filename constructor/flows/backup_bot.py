"""Main bot: the owner's own backup of a bot (download as JSON, restore from a JSON file)."""
import io
from datetime import datetime, timezone

from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, Update
from telegram.ext import ContextTypes

from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core import bot_backup
from core.database import AsyncSessionLocal
from models.bots import Bot

WAITING_FOR_RESTORE = "waiting_for_bot_restore"


async def _owned(session, update: Update, raw) -> Bot | None:
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    if not str(raw).isdigit():
        return None
    return (await session.execute(select(Bot).where(Bot.id == int(raw), Bot.owner_id == user.id))).scalar_one_or_none()


async def _fallback(update, context):
    from constructor.flows.bots import show_user_bots
    await show_user_bots(update, context)


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, query.data.split(":")[2])
    if bot is None:
        return await _fallback(update, context)
    rows = [[Btn("📥 Zaxira nusxani yuklab olish", callback_data=f"bkp:out:{bot.id}")],
            [Btn("📤 Fayldan tiklash", callback_data=f"bkp:in:{bot.id}")],
            [Btn("⬅️ Sozlamalar", callback_data=f"grp:settings:{bot.id}")]]
    await show_screen(update, "💾 <b>Zaxira nusxa</b>\n\nBotning menyu, tugma va formalari bitta fayl bo‘ladi. Faylni saqlab qo‘ying: "
                              "xato qilsangiz yoki botni ko‘chirmoqchi bo‘lsangiz, shu fayldan tiklaysiz.\n\n"
                              "Foydalanuvchilar, tokenlar va forma javoblari faylga kirmaydi.", rows, edit=True)


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, query.data.split(":")[2])
        if bot is None:
            await query.answer()
            return await _fallback(update, context)
        data = await bot_backup.export_bot(session, bot)
    await query.answer("Fayl tayyorlandi")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name = f"telecraft_{data['bot_username'] or data['bot_id']}_{stamp}.json"
    await query.message.reply_document(document=io.BytesIO(bot_backup.dumps(data)), filename=name,
                                       caption=f"💾 «{bot.name}» zaxira nusxasi · {len(data['menus'])} menyu, {sum(len(m['buttons']) for m in data['menus'])} tugma")


async def ask_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, query.data.split(":")[2])
    if bot is None:
        return await _fallback(update, context)
    await save_builder_session(user.id, context, pending_state=WAITING_FOR_RESTORE, draft={"flow": "restore", "bot_id": bot.id})
    await query.message.reply_text("📤 Zaxira faylini (.json) shu chatga yuboring.\n⚠️ Hozirgi menyu va tugmalar fayldagilar bilan almashtiriladi. Bekor qilish: /cancel")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A document arrived while waiting for a backup file."""
    message = update.message
    doc = message.document
    if doc is None or doc.file_size and doc.file_size > bot_backup.MAX_BYTES:
        await message.reply_text("❌ .json zaxira faylini yuboring (2 MB gacha).")
        return
    bot_id = (context.user_data.get("draft") or {}).get("bot_id")
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, bot_id)
    if bot is None:
        await message.reply_text("❌ Bot topilmadi.")
        return
    try:
        raw = bytes(await (await context.bot.get_file(doc.file_id)).download_as_bytearray())
        data = bot_backup.parse(raw)
    except bot_backup.BackupError as exc:
        await message.reply_text(f"❌ {exc}")
        return
    except Exception:
        await message.reply_text("❌ Faylni o‘qib bo‘lmadi. Qayta yuboring.")
        return
    context.user_data["restore_data"] = data
    info = bot_backup.summary(data, bot.id)
    warn = "" if info["same_bot"] else "\nℹ️ Fayl boshqa botdan: media, fayl va admin tugmalari tiklanmaydi."
    await show_screen(update, f"📦 <b>Zaxira fayli</b>\n\nMenyu: {info['menus']} · Tugma: {info['buttons']} · Forma: {info['forms']}{warn}\n\n"
                              "⚠️ Hozirgi menyu va tugmalar <b>o‘chiriladi</b>.",
                      [[Btn("✅ Tiklash", callback_data=f"bkp:go:{bot.id}")], [Btn("❌ Bekor qilish", callback_data=f"bot_{bot.id}")]], edit=False)


async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data.pop("restore_data", None)
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, query.data.split(":")[2])
        if bot is None:
            return await _fallback(update, context)
        if data is None:
            await query.message.reply_text("⌛ Fayl eskirgan. Qaytadan yuboring: Sozlamalar → Zaxira nusxa.")
            return
        bot_id = bot.id
        result = await bot_backup.restore(session, bot, data)
    await save_builder_session(user.id, context, current_bot_id=bot_id, pending_state="", draft={})
    from core import plans
    plans.invalidate(bot_id)
    extra = f"\nℹ️ {result['dropped']} ta tugma (media/fayl/admin) tiklanmadi." if result["dropped"] else ""
    await query.message.reply_text(f"✅ Tiklandi: {result['menus']} menyu, {result['buttons']} tugma, {result['forms_new']} yangi forma.{extra}")
    from constructor.flows.bots import open_bot
    await open_bot(update, context, bot_id=bot_id)
