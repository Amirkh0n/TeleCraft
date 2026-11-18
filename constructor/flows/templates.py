"""Apply a ready-made template to a bot: start message, menus and buttons in one tap."""
from sqlalchemy import delete, select, update as sql_update
from telegram import InlineKeyboardButton as Btn, Update
from telegram.ext import ContextTypes

from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core.database import AsyncSessionLocal
from core.templates import BACK, BY_KEY, TEMPLATES, Sub
from models.bots import Bot
from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.menus import Menu
from models.user_sessions import UserSession


async def has_content(session, bot_id: int) -> bool:
    menus = (await session.execute(select(Menu.id).where(Menu.bot_id == bot_id))).scalars().all()
    if len(menus) > 1:
        return True
    return bool(menus) and (await session.execute(select(Button.id).where(Button.menu_id.in_(menus)).limit(1))).first() is not None


async def wipe(session, bot_id: int, start: Menu) -> None:
    """Remove every button and every menu except ``start``. Users' open screens move to the start menu first."""
    others = (await session.execute(select(Menu.id).where(Menu.bot_id == bot_id, Menu.id != start.id))).scalars().all()
    all_ids = [start.id, *others]
    await session.execute(sql_update(UserSession).where(UserSession.bot_id == bot_id).values(current_menu_id=start.id).execution_options(synchronize_session=False))
    button_ids = (await session.execute(select(Button.id).where(Button.menu_id.in_(all_ids)))).scalars().all()
    if button_ids:
        await session.execute(delete(ButtonAction).where(ButtonAction.button_id.in_(button_ids)).execution_options(synchronize_session=False))
        await session.execute(delete(Button).where(Button.id.in_(button_ids)).execution_options(synchronize_session=False))
    if others:
        await session.execute(delete(Menu).where(Menu.id.in_(others)).execution_options(synchronize_session=False))


async def apply(session, bot: Bot, key: str) -> None:
    """Replace the bot's menus with the template. Users' open screens move to the start menu first."""
    tpl = BY_KEY[key]
    start = (await session.execute(select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True))).scalars().first()  # noqa: E712
    if start is None:
        start = Menu(bot_id=bot.id, title="Bosh menyu", is_start=True, position=0)
        session.add(start)
        await session.flush()
    await wipe(session, bot.id, start)

    start.message_text, start.title, start.columns, start.keyboard_mode = tpl.start, "Bosh menyu", 2, "inline"
    start.media_type = start.media_file_id = None

    async def add(menu_id, position, text, action_type, value):
        button = Button(menu_id=menu_id, text=text, position=position)
        session.add(button)
        await session.flush()
        session.add(ButtonAction(button_id=button.id, action_type=action_type, value=value))

    for pos, (text, answer) in enumerate(tpl.buttons):
        if isinstance(answer, Sub):
            sub = Menu(bot_id=bot.id, title=answer.title[:255], message_text=answer.text, position=pos + 1, columns=1)
            session.add(sub)
            await session.flush()
            for i, (label, reply) in enumerate(answer.items):
                await add(sub.id, i, label, ActionType.text, reply)
            await add(sub.id, len(answer.items), BACK, ActionType.menu, str(start.id))
            await add(start.id, pos, text, ActionType.menu, str(sub.id))
        else:
            await add(start.id, pos, text, ActionType.text, answer)
    bot.onboarding_completed = True
    await session.commit()


async def _owned(session, update: Update, bot_id) -> Bot | None:
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    if not str(bot_id).isdigit():
        return None
    return (await session.execute(select(Bot).where(Bot.id == int(bot_id), Bot.owner_id == user.id))).scalar_one_or_none()


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tpl:list[:<bot_id>] — the template gallery. Without an id the bot being set up is used."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    bot_id = parts[2] if len(parts) > 2 else context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, bot_id)
    if bot is None:
        from constructor.flows.bots import show_user_bots
        return await show_user_bots(update, context)
    rows = [[Btn(f"{t.icon} {t.title}", callback_data=f"tpl:v:{t.key}:{bot.id}")] for t in TEMPLATES]
    rows.append([Btn("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot.id}")])
    await show_screen(update, "✨ <b>Tayyor shablonlar</b>\n\nBiznes turingizni tanlang: bot menyu va tugmalar bilan shu zahoti tayyor bo‘ladi. "
                              "Keyin matn va narxlarni o‘zingiznikiga almashtirasiz.", rows, edit=True)


async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tpl:v:<key>:<bot_id> — what the template contains, then apply."""
    query = update.callback_query
    await query.answer()
    _, _, key, bot_id = query.data.split(":")
    tpl = BY_KEY.get(key)
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, bot_id)
        busy = bot is not None and await has_content(session, bot.id)
    if tpl is None or bot is None:
        return await show_list(update, context)
    lines = "\n".join(f"• {text}" + (" ▸" if isinstance(ans, Sub) else "") for text, ans in tpl.buttons)
    warn = "\n\n⚠️ Botdagi hozirgi menyu va tugmalar <b>o‘chiriladi</b>." if busy else ""
    rows = [[Btn("✅ Qo‘llash", callback_data=f"tpl:go:{key}:{bot.id}")], [Btn("⬅️ Shablonlar", callback_data=f"tpl:list:{bot.id}")]]
    await show_screen(update, f"{tpl.icon} <b>{tpl.title}</b>\n{tpl.about}\n\nTugmalar:\n{lines}{warn}", rows, edit=True)


async def go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, key, bot_id = query.data.split(":")
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    async with AsyncSessionLocal() as session:
        bot = await _owned(session, update, bot_id)
        if bot is None or key not in BY_KEY:
            return await show_list(update, context)
        bot_id = bot.id
        await apply(session, bot, key)
    await save_builder_session(user.id, context, current_bot_id=bot_id, pending_state="", draft={})
    from constructor.flows.bots import open_bot
    await query.message.reply_text("✅ Shablon qo‘llandi. Botni sinab ko‘ring, keyin matn va narxlarni o‘zgartiring.")
    await open_bot(update, context, bot_id=bot_id)
