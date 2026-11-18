"""Bot control panel: the long list of buttons is grouped into a few sections (content, clients, settings, modes)."""
from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, Update
from telegram.ext import ContextTypes

from constructor.session import ensure_constructor_user
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from models.bots import Bot

# kind -> (button title, the mode's own panel)
MODES = {
    "cinema": ("🎬 Kino bot", "cin:home"), "booking": ("📅 Bron bot", "bkc:home"), "quiz": ("🧠 Test bot", "qzc:home"),
    "course": ("🎓 Kurs bot", "crsc:home"), "shop": ("🛒 Do‘kon bot", "shpc:home"), "join": ("📨 Ariza bot", "jnpc:home"),
    "paid": ("💎 Pullik kanal", "pdc:home"),
}


def top_rows(bot, editor_row) -> list[list[Btn]]:
    """The first screen of a bot: a handful of sections instead of seventeen buttons."""
    rows = [[Btn("📝 Bosh xabar", callback_data="edit_start_message")], *editor_row,
            [Btn("📂 Kontent", callback_data=f"grp:content:{bot.id}")]]
    if bot.kind in MODES:
        title, home = MODES[bot.kind]
        rows.append([Btn(f"{title} sozlamalari", callback_data=home)])
    else:
        rows.append([Btn("✨ Tayyor rejim tanlash", callback_data=f"grp:modes:{bot.id}")])
    rows.append([Btn("👥 Mijozlar", callback_data=f"grp:clients:{bot.id}"), Btn("⚙️ Sozlamalar", callback_data=f"grp:settings:{bot.id}")])
    rows.append([Btn("🧪 Sinab ko‘rish", callback_data="test_bot"), Btn("📊 Holat", callback_data="bot_status")])
    rows.append([Btn("⬅️ Botlarim", callback_data="back_to_bots")])
    return rows


def group_rows(name: str, bot) -> tuple[str, list[list[Btn]]] | None:
    if name == "content":
        return "📂 Kontent\n\nBot nimani ko‘rsatishini shu yerda sozlang.", [
            [Btn("📂 Menyular", callback_data="menus"), Btn("🔘 Tugmalar", callback_data="start_buttons")],
            [Btn("📋 Formalar", callback_data="frm:list")]]
    if name == "clients":
        return "👥 Mijozlar\n\nBot foydalanuvchilari bilan ishlash.", [
            [Btn("👥 Auditoriya", callback_data="aud:home"), Btn("📣 Broadcast", callback_data="bc:home")],
            [Btn("🔒 Majburiy obuna", callback_data="sub:home")]]
    if name == "settings":
        rows = [[Btn("👮 Adminlar", callback_data="adm:home"), Btn("💳 Tarif", callback_data="plx:home")],
                [Btn("🔀 Bot rejimini almashtirish", callback_data=f"grp:modes:{bot.id}")]]
        return "⚙️ Sozlamalar", rows
    if name == "modes":
        rows, row = [], []
        for kind, (title, home) in MODES.items():
            row.append(Btn(("✅ " if kind == bot.kind else "") + title, callback_data=home))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return "🔀 Tayyor rejimlar\n\nBotni kerakli rejimga o‘tkazing. Joriy rejim ✅ bilan belgilangan.", rows
    return None


async def show_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, name, raw = query.data.split(":", 2)
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    async with AsyncSessionLocal() as session:
        bot = (await session.execute(select(Bot).where(Bot.id == int(raw), Bot.owner_id == user.id))).scalar_one_or_none() if raw.isdigit() else None
    built = group_rows(name, bot) if bot else None
    if built is None:
        from constructor.flows.bots import show_user_bots
        await show_user_bots(update, context)
        return
    text, rows = built
    rows.append([Btn("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")])
    await show_screen(update, text, rows, edit=True)
