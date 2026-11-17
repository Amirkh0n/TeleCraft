"""Main bot home menu and the gallery of ready-made bots (Tayyor botlar)."""
import html

from sqlalchemy import select
from telegram import InlineKeyboardButton as Btn, Update, WebAppInfo
from telegram.ext import ContextTypes

from constructor.flows.cinema import set_kind
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core import plans
from core.config import settings
from core.database import AsyncSessionLocal
from models.bots import Bot
from webapp import editor_url

GALLERY_ORDER = ("cinema", "shop", "course", "booking", "quiz", "paid", "join")


def _modes():
    from webapp.api_modes import MODES  # imported late: that module imports constructor flows
    return MODES


def locked(plan: plans.Plan, kind: str) -> bool:
    return settings.PLANS_ENFORCE and kind not in plan.kinds


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    now = plans.utcnow()
    async with AsyncSessionLocal() as session:
        bots = list((await session.execute(select(Bot).where(Bot.owner_id == user.id).order_by(Bot.id.desc()))).scalars())
        plan = await plans.owner_plan(session, user.id, now)
        acc = await plans.get_account(session, user.id)
    code, status = plans.state_of(acc, now)
    tariff = plan.title if status != "free" or plan.code != plans.FREE else "Free"
    if status != "free" and not plans.is_platform_admin(tg.id):
        tariff += f" · {plans.as_utc(acc.expires_at).astimezone(plans_tz()).strftime('%d.%m.%Y')} gacha"
    limit = "∞" if plan.max_bots is None else str(plan.max_bots)
    text = (f"🏠 <b>TeleCraft</b>\nKod yozmasdan Telegram bot yarating.\n\n"
            f"🤖 Botlaringiz: <b>{len(bots)}</b> / {limit}\n💳 Tarif: <b>{tariff}</b>")
    rows = [[Btn(f"🤖 Botlarim ({len(bots)})" if bots else "🤖 Botlarim", callback_data="back_to_bots"), Btn("➕ Yangi bot", callback_data="add_bot")],
            [Btn("🧩 Tayyor botlar", callback_data="gal:home")]]
    url = editor_url()
    if url:
        rows[1].append(Btn("🎨 Muharrir", web_app=WebAppInfo(url=url)))
    last = next((b for b in bots if b.id == context.user_data.get("current_bot_id")), None)
    if last is not None:
        rows.append([Btn(f"▶️ Davom etish: {last.name}"[:60], callback_data=f"bot_{last.id}")])
    rows.append([Btn("💳 Tarif va to‘lov", callback_data="plx:home"), Btn("🎁 Do‘st taklif", callback_data="ref:home")])
    rows.append([Btn("❓ Yordam", callback_data="help")])
    if plans.is_platform_admin(tg.id) and url:
        rows.append([Btn("🛡 Admin panel", web_app=WebAppInfo(url=url))])
    await show_screen(update, text, rows, edit=bool(update.callback_query))


def plans_tz():
    from constructor.flows.plans import TZ
    return TZ


# ------------------------------------------------------------------ gallery

async def gallery_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    async with AsyncSessionLocal() as session:
        plan = await plans.owner_plan(session, user.id)
    modes = _modes()
    rows = []
    for kind in GALLERY_ORDER:
        icon, name, _, _ = modes[kind]
        lock = "🔒 " if locked(plan, kind) else ""
        rows.append([Btn(f"{lock}{icon} {name} · {plans.money(plans.KIND_PRICES[kind])}/oy"[:60], callback_data=f"gal:k:{kind}")])
    rows.append([Btn("💬 Oddiy bot (o‘zingiz quring)", callback_data="add_bot")])
    rows.append([Btn("🏠 Bosh menyu", callback_data="home")])
    await show_screen(update, "🧩 <b>Tayyor botlar</b>\n\nKerakli rejimni tanlang: bot shu zahoti kerakli funksiyalar bilan tayyor bo‘ladi. "
                              "Narx: bitta botni alohida ochish uchun oylik to‘lov; tariflarda esa ko‘p bot kiradi.\n🔒 — hozirgi tarifingizda yopiq.", rows)


async def gallery_kind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = update.callback_query.data.split(":")[2]
    modes = _modes()
    if kind not in modes or kind == "standard":
        return await gallery_home(update, context)
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    async with AsyncSessionLocal() as session:
        plan = await plans.owner_plan(session, user.id)
        count = await plans.bot_count(session, user.id)
    icon, name, about, steps = modes[kind]
    need = plans.PLANS[plans.KIND_MIN_PLAN[kind]]
    text = (f"{icon} <b>{name}</b>\n\n{about}\n\n<b>Boshlash:</b>\n" + "\n".join(f"• {s}" for s in steps)
            + f"\n\n💳 Alohida: <b>{plans.money(plans.KIND_PRICES[kind])}</b>/oy · tarif: <b>{need.title}</b> dan")
    rows = []
    if locked(plan, kind):
        text += f"\n\n🔒 Hozirgi tarifingiz (<b>{plan.title}</b>) bu rejimni ochmaydi: tarifni oshiring yoki bitta botni alohida oching."
        rows.append([Btn("💳 Tarifni tanlash", callback_data="plx:home")])
        if count:
            rows.append([Btn("🤖 Mavjud botni shu rejimda ochish (alohida to‘lov)", callback_data=f"gal:pay:{kind}")])
    else:
        rows.append([Btn("➕ Yangi bot sifatida yaratish", callback_data=f"gal:new:{kind}")])
        if count:
            rows.append([Btn("🔁 Mavjud botimda yoqish", callback_data=f"gal:use:{kind}")])
    rows.append([Btn("⬅️ Galereya", callback_data="gal:home")])
    await show_screen(update, text, rows)


async def _bot_picker(update: Update, kind: str, prefix: str, title: str):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    async with AsyncSessionLocal() as session:
        bots = list((await session.execute(select(Bot).where(Bot.owner_id == user.id).order_by(Bot.id.desc()))).scalars())
    rows = [[Btn(f"{b.name} · {plans.KIND_TITLES.get(b.kind, 'Oddiy bot')}"[:60], callback_data=f"{prefix}:{kind}:{b.id}")] for b in bots[:20]]
    rows.append([Btn("⬅️ Orqaga", callback_data=f"gal:k:{kind}")])
    await show_screen(update, title, rows)


async def gallery_use_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = update.callback_query.data.split(":")[2]
    await _bot_picker(update, kind, "gal:set", f"🔁 Qaysi botda <b>{plans.KIND_TITLES.get(kind, kind)}</b> yoqilsin?\n\n"
                      "Oldingi rejim ma’lumotlari o‘chmaydi, oddiy rejimga qaytsangiz yana ishlaydi.")


async def gallery_pay_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = update.callback_query.data.split(":")[2]
    await _bot_picker(update, kind, "gal:payfor", f"🤖 Qaysi botni <b>{plans.KIND_TITLES.get(kind, kind)}</b> rejimida ochamiz?\n\n"
                      "To‘lov tasdiqlangach bot shu rejimga o‘tadi.")


async def gallery_pay_for(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, _, kind, bot_id = update.callback_query.data.split(":")
    update.callback_query.data = f"plx:bk:{bot_id}:{kind}"
    from constructor.flows.plans import pick_bot_kind_months
    await pick_bot_kind_months(update, context)


async def gallery_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch an existing bot to the chosen mode, then open it."""
    from constructor.flows.bots import open_bot
    _, _, kind, raw = update.callback_query.data.split(":")
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    async with AsyncSessionLocal() as session:
        bot = (await session.execute(select(Bot).where(Bot.id == int(raw), Bot.owner_id == user.id))).scalar_one_or_none()
        if bot is None:
            return await gallery_home(update, context)
        try:
            await set_kind(session, bot, kind)
        except plans.PlanError as exc:
            await show_screen(update, str(exc), [[Btn("💳 Tariflar", callback_data="plx:home")],
                                                [Btn("🤖 Shu bot uchun alohida to‘lov", callback_data=f"plx:bk:{bot.id}:{kind}")]])
            return
        await session.commit()
        plans.invalidate(bot.id)
    await open_bot(update, context, bot_id=int(raw))


async def gallery_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from constructor.handlers import begin_create
    await begin_create(update, context, kind=update.callback_query.data.split(":")[2])


async def deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> bool:
    """``/start new_<mode>`` (from the Mini App gallery): begin creating a bot in that mode."""
    from constructor.handlers import begin_create
    if payload == "new":
        await begin_create(update, context)
        return True
    if not payload.startswith("new_") or payload[4:] not in GALLERY_ORDER:
        return False
    await begin_create(update, context, kind=payload[4:])
    return True


async def finish_create(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: int, kind: str) -> bool:
    """The new bot got its token: switch it to the chosen mode and open its panel."""
    from constructor.flows.bots import open_bot
    async with AsyncSessionLocal() as session:
        bot = await session.get(Bot, bot_id)
        try:
            await set_kind(session, bot, kind)
        except plans.PlanError as exc:
            await update.message.reply_text(plans.plain_text(str(exc)))
            return False
        bot.onboarding_completed = True
        await session.commit()
        plans.invalidate(bot.id)
    await update.message.reply_text(f"✅ {plans.KIND_TITLES.get(kind, kind)} rejimi yoqildi. Quyida botingiz paneli.")
    await open_bot(update, context, bot_id=bot_id)
    return True
