"""Main bot: the owner's plan, buying a plan or a single bot with a card + receipt photo, and the admins'
✅/❌ decision. Money rules live in ``core.plans``."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from constructor import states
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from core import plans, promo
from core.config import settings
from core.database import AsyncSessionLocal
from core.logger import get_logger
from core.plans import PLANS, PlanError
from engine.booking_time import as_utc, utcnow
from models.bots import Bot
from models.plans import PlanPayment

from sqlalchemy import select

logger = get_logger("constructor.plans")
TZ = ZoneInfo("Asia/Tashkent")
HOME = "plx:home"


def day(dt: datetime) -> str:
    return as_utc(dt).astimezone(TZ).strftime("%d.%m.%Y")


plain = plans.plain_text


def _plans_button():
    return [Btn("💳 Tariflar", callback_data=HOME)]


async def deny(update: Update, message: str) -> None:
    """Show a plan-limit message with a way to the tariffs."""
    await show_screen(update, message, [_plans_button()], edit=bool(update.callback_query))


def guard(handler):
    """Wrap a handler that may raise PlanError: the person sees why, and a button to the tariffs."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await handler(update, context)
        except PlanError as exc:
            await deny(update, str(exc))
    return wrapper


# ------------------------------------------------------------------ owner screens

async def plan_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    now = utcnow()
    async with AsyncSessionLocal() as session:
        acc = await plans.get_account(session, user.id)
        plan = await plans.owner_plan(session, user.id, now)
        count = await plans.bot_count(session, user.id)
    code, status = plans.state_of(acc, now)
    if plans.is_platform_admin(tg.id) or not settings.PLANS_ENFORCE:
        head = f"Joriy tarif: <b>{plan.title}</b> (cheklovsiz)"
    elif status == "active":
        left = (as_utc(acc.expires_at) - now).days
        head = f"Joriy tarif: <b>{plan.title}</b> · {day(acc.expires_at)} gacha ({left} kun qoldi)"
    elif status == "grace":
        head = (f"Joriy tarif: <b>{PLANS[code].title}</b> muddati {day(acc.expires_at)} da tugadi.\n"
                f"⏳ {plans.GRACE_DAYS} kunlik imtiyoz davom etmoqda: uzaytirmasangiz Free tarifga tushasiz.")
    else:
        head = "Joriy tarif: <b>Free</b>"
    limit_bots = "cheksiz" if plan.max_bots is None else str(plan.max_bots)
    users = "cheksiz" if plan.user_cap is None else str(plan.user_cap)
    lines = [f"💳 <b>Tarif va to‘lov</b>\n\n{head}", f"Botlar: <b>{count}</b> / {limit_bots} · foydalanuvchi (har bot): {users}\n",
             "<b>Tariflar (oyiga):</b>"]
    for code in plans.PAID_PLANS:
        p = PLANS[code]
        bots = "cheksiz bot" if p.max_bots is None else f"{p.max_bots} bot"
        cap = "cheksiz foydalanuvchi" if p.user_cap is None else f"{p.user_cap} foydalanuvchi"
        lines.append(f"• <b>{p.title}</b> — {plans.money(p.price)}: {bots}, {cap}")
    lines.append(f"• <b>Free</b> — 0: 1 bot, 20 foydalanuvchi\n\nUzoq muddat arzonroq: 3 oyga −10%, 12 oyga −25%.")
    keyboard = [[Btn(f"{PLANS[c].title} · {plans.money(PLANS[c].price)}", callback_data=f"plx:p:{c}")] for c in plans.PAID_PLANS]
    if acc is None or not acc.trial_used:
        keyboard.append([Btn(f"🎁 {plans.TRIAL_DAYS} kun bepul Pro", callback_data="plx:trial")])
    keyboard.append([Btn("🤖 Bitta botni ochish (alohida to‘lov)", callback_data="plx:b")])
    keyboard.append([Btn("🎁 10 do‘st taklif qiling — 1 oy Start bepul", callback_data="ref:home")])
    keyboard.append([Btn("🏠 Bosh menyu", callback_data="home")])
    await show_screen(update, "\n".join(lines), keyboard, edit=bool(update.callback_query))


def _months_keyboard(prefix: str, monthly: int, back: str):
    rows = []
    for m in plans.MONTH_CHOICES:
        off = plans.DISCOUNT[m]
        label = f"{m} oy · {plans.money(plans.price_for(monthly, m))}" + (f" (−{off}%)" if off else "")
        rows.append([Btn(label, callback_data=f"{prefix}:{m}")])
    rows.append([Btn("⬅️ Orqaga", callback_data=back)])
    return rows


async def pick_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.callback_query.data.split(":")[2]
    if code not in plans.PAID_PLANS:
        return await plan_home(update, context)
    p = PLANS[code]
    text = (f"💳 <b>{p.title}</b> tarifi\n\nMuddatni tanlang:")
    await show_screen(update, text, _months_keyboard(f"plx:pm:{code}", p.price, HOME))


async def pick_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    async with AsyncSessionLocal() as session:
        bots = list((await session.execute(select(Bot).where(Bot.owner_id == user.id).order_by(Bot.id.desc()))).scalars())
    if not bots:
        return await show_screen(update, "Avval bot yarating.", [[Btn("⬅️ Orqaga", callback_data=HOME)]])
    rows = [[Btn(f"{b.name} · {plans.KIND_TITLES.get(b.kind, 'Oddiy bot')} · {plans.money(plans.KIND_PRICES.get(b.kind, 15000))}",
                 callback_data=f"plx:bb:{b.id}")] for b in bots[:20]]
    rows.append([Btn("⬅️ Orqaga", callback_data=HOME)])
    await show_screen(update, "🤖 <b>Bitta botni ochish</b>\n\nCheksiz foydalanuvchi va TeleCraft yozuvisiz, faqat shu bot va uning "
                              "hozirgi rejimi uchun. Botni tanlang:", rows)


async def pick_bot_months(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    bot_id = int(update.callback_query.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        bot = (await session.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id))).scalar_one_or_none()
    if bot is None:
        return await pick_bot(update, context)
    kind = bot.kind or "standard"
    text = f"🤖 <b>{html.escape(bot.name)}</b> · {plans.KIND_TITLES.get(kind, kind)}\n\nMuddatni tanlang:"
    await show_screen(update, text, _months_keyboard(f"plx:bm:{bot.id}", plans.KIND_PRICES[kind], "plx:b"))


async def pick_bot_kind_months(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``plx:bk:<bot id>:<mode>``: pay for one bot in a chosen mode (it is switched to it once approved)."""
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    _, _, raw_bot, kind = update.callback_query.data.split(":")
    async with AsyncSessionLocal() as session:
        bot = (await session.execute(select(Bot).where(Bot.id == int(raw_bot), Bot.owner_id == user.id))).scalar_one_or_none()
    if bot is None or kind not in plans.KIND_PRICES:
        return await pick_bot(update, context)
    text = (f"🤖 <b>{html.escape(bot.name)}</b> → {plans.KIND_TITLES[kind]}\n\n"
            "To‘lov tasdiqlangach bot shu rejimga o‘tadi. Muddatni tanlang:")
    await show_screen(update, text, _months_keyboard(f"plx:bn:{bot.id}:{kind}", plans.KIND_PRICES[kind], HOME))


async def start_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    try:
        async with AsyncSessionLocal() as session:
            acc = await plans.start_trial(session, user)
    except PlanError as exc:
        return await deny(update, str(exc))
    await show_screen(update, f"🎁 <b>Pro</b> tarifi {plans.TRIAL_DAYS} kunga yoqildi: {day(acc.expires_at)} gacha.\n"
                              "Barcha rejimlar va cheksiz foydalanuvchi ochiq.", [[Btn("⬅️ Botlarim", callback_data="back_to_bots")]])


# ------------------------------------------------------------------ paying

async def make_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``plx:pm:<plan>:<months>`` or ``plx:bm:<bot id>:<months>``: show the card and wait for the receipt."""
    parts = update.callback_query.data.split(":")
    kind, target, months = parts[1], parts[2], parts[-1]
    mode = parts[3] if kind == "bn" else None
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    try:
        async with AsyncSessionLocal() as session:
            if kind == "pm":
                pay = await plans.create_payment(session, user, plan=target, months=int(months))
            else:
                pay = await plans.create_payment(session, user, bot_id=int(target), months=int(months), kind=mode)
    except (PlanError, ValueError, KeyError) as exc:
        return await deny(update, str(exc) if isinstance(exc, PlanError) else "So‘rov noto‘g‘ri.")
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_PLAN_RECEIPT,
                               draft={"flow": "plan_receipt", "id": pay.id})
    await _show_payment(update, pay)


async def _show_payment(update: Update, pay: PlanPayment, *, edit: bool = True):
    if settings.PLAN_CARD_NUMBER:
        card = (f"💳 Karta: <code>{html.escape(settings.PLAN_CARD_NUMBER)}</code>\n"
                + (f"👤 Egasi: {html.escape(settings.PLAN_CARD_HOLDER)}\n" if settings.PLAN_CARD_HOLDER else ""))
    else:
        card = "⚠️ To‘lov rekvizitlari hali sozlanmagan. Admin bilan bog‘laning.\n"
    amount = f"<b>{plans.money(pay.amount)}</b>"
    if pay.discount:
        amount = f"<s>{plans.money(pay.amount + pay.discount)}</s> → {amount} (promo <code>{html.escape(pay.promo_code or '')}</code>)"
    text = (f"💳 <b>To‘lov #{pay.id}</b>\n{plans.describe(pay)}\n\n"
            f"Summa: {amount}\n{card}\n"
            "To‘lovni amalga oshiring va <b>chek rasmini (skrinshot)</b> shu chatga yuboring. "
            "Admin tekshirgach, tarif yoqiladi.")
    await show_screen(update, text, [[Btn("🎟 Promo-kod", callback_data=f"plx:pr:{pay.id}")],
                                     [Btn("❌ Bekor qilish", callback_data=f"plx:x:{pay.id}")]], edit=edit)


async def ask_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    pay_id = int(query.data.split(":")[2])
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_PROMO, draft={"flow": "plan_receipt", "id": pay_id})
    await query.message.reply_text("🎟 Promo-kodni yuboring (bekor qilish: /cancel).")


async def promo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The owner typed a promo code while paying."""
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    pay_id = (context.user_data.get("draft") or {}).get("id") or 0
    try:
        async with AsyncSessionLocal() as session:
            pay = await promo.apply_to_payment(session, pay_id, user.id, update.message.text or "")
            amount = pay.amount
    except PlanError as exc:
        await update.message.reply_text(f"❌ {exc}\nBoshqa kod yuboring yoki chek rasmini yuboring.")
        await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_PLAN_RECEIPT, draft={"flow": "plan_receipt", "id": pay_id})
        return
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_PLAN_RECEIPT, draft={"flow": "plan_receipt", "id": pay_id})
    async with AsyncSessionLocal() as session:
        pay = await session.get(PlanPayment, pay_id)
        await _show_payment(update, pay, edit=False)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    pay_id = int(update.callback_query.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        await plans.cancel_payment(session, pay_id, tg.id)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await plan_home(update, context)


async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A photo or document while the owner is paying: send it to the platform admins."""
    message = update.message
    tg = update.effective_user
    user = await ensure_constructor_user(tg.id, tg.full_name)
    if message.photo:
        rtype, file_id = "photo", message.photo[-1].file_id
    elif message.document:
        rtype, file_id = "document", message.document.file_id
    else:
        await message.reply_text("📎 Chekni rasm (skrinshot) ko‘rinishida yuboring.")
        return
    pay_id = (context.user_data.get("draft") or {}).get("id")
    async with AsyncSessionLocal() as session:
        pay = await plans.attach_receipt(session, pay_id or 0, tg.id, rtype, file_id)
    await save_builder_session(user.id, context, pending_state="", draft={})
    if pay is None:
        await message.reply_text("⚠️ Bu to‘lov topilmadi yoki allaqachon yuborilgan. Tariflar bo‘limidan qayta boshlang.")
        return
    await message.reply_text("✅ Chek yuborildi. Admin tekshirgach, sizga xabar beraman.",
                             reply_markup=InlineKeyboardMarkup([[Btn("⬅️ Botlarim", callback_data="back_to_bots")]]))
    await notify_admins(context.bot, pay, tg.full_name or "", tg.username)


async def receipt_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Chek rasmini (skrinshot) yuboring yoki /cancel bosing.")


def _admin_caption(pay: PlanPayment, name: str, username: str | None) -> str:
    who = html.escape(name or "—") + (f" @{html.escape(username)}" if username else "")
    return (f"💳 <b>To‘lov #{pay.id}</b>\n{who} · <code>{pay.tg_user_id}</code>\n"
            f"{plans.describe(pay)}\nSumma: <b>{plans.money(pay.amount)}</b>")


def _admin_markup(pay_id: int):
    return InlineKeyboardMarkup([[Btn("✅ Tasdiqlash", callback_data=f"pla:ok:{pay_id}"),
                                  Btn("❌ Rad etish", callback_data=f"pla:no:{pay_id}")]])


async def notify_admins(bot, pay: PlanPayment, name: str, username: str | None) -> int:
    sent = 0
    for admin_id in settings.admin_ids_list:
        try:
            kwargs = dict(chat_id=admin_id, caption=_admin_caption(pay, name, username), parse_mode="HTML",
                          reply_markup=_admin_markup(pay.id))
            if pay.receipt_type == "photo":
                await bot.send_photo(photo=pay.receipt_file_id, **kwargs)
            else:
                await bot.send_document(document=pay.receipt_file_id, **kwargs)
            sent += 1
        except TelegramError as exc:
            logger.warning("plan payment %s not delivered to admin %s: %s", pay.id, admin_id, exc)
    return sent


# ------------------------------------------------------------------ admin decision

async def decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in settings.admin_ids_list:
        await query.answer("Bu tugma faqat adminlar uchun.", show_alert=True)
        return
    _, action, raw = query.data.split(":")
    approve = action == "ok"
    async with AsyncSessionLocal() as session:
        pay = await plans.decide(session, int(raw), update.effective_user.id, approve)
        if pay is None:
            await query.answer("Bu to‘lov allaqachon hal qilingan.", show_alert=True)
            return
        text = await _result_text(session, pay, approve)
    await query.answer("✅ Tasdiqlandi" if approve else "❌ Rad etildi")
    mark = "✅ Tasdiqlandi" if approve else "❌ Rad etildi"
    try:
        await query.message.edit_caption(caption=f"{query.message.caption_html or ''}\n\n<b>{mark}</b>", parse_mode="HTML")
    except TelegramError as exc:
        logger.info("admin message not edited: %s", exc)
    try:
        await context.bot.send_message(chat_id=pay.tg_user_id, text=text, parse_mode="HTML")
    except TelegramError as exc:
        logger.info("payer %s not told about payment %s: %s", pay.tg_user_id, pay.id, exc)


async def _result_text(session, pay: PlanPayment, approve: bool) -> str:
    if not approve:
        return (f"❌ To‘lov #{pay.id} ({plans.describe(pay)}) tasdiqlanmadi.\n"
                "Chek noto‘g‘ri bo‘lsa, qayta yuboring yoki admin bilan bog‘laning.")
    if pay.target == "plan":
        acc = await plans.get_account(session, pay.user_id)
        return f"✅ To‘lov #{pay.id} tasdiqlandi. <b>{PLANS[pay.plan].title}</b> tarifi {day(acc.expires_at)} gacha faol."
    lic = (await session.execute(select(plans.BotLicense).where(plans.BotLicense.bot_id == pay.bot_id))).scalar_one()
    bot = await session.get(Bot, pay.bot_id)
    return (f"✅ To‘lov #{pay.id} tasdiqlandi. <b>{html.escape(bot.name)}</b> ({plans.KIND_TITLES.get(pay.kind, pay.kind)}) "
            f"{day(lic.expires_at)} gacha cheksiz ishlaydi.")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``/payments``: an admin gets every undecided payment again (a lost message must not lose a payment)."""
    if update.effective_user.id not in settings.admin_ids_list:
        return
    async with AsyncSessionLocal() as session:
        rows = await plans.pending_payments(session)
    if not rows:
        await update.message.reply_text("Kutilayotgan to‘lovlar yo‘q.")
        return
    for pay in rows:
        await notify_admins_one(context.bot, update.effective_user.id, pay)


async def notify_admins_one(bot, admin_id: int, pay: PlanPayment) -> None:
    kwargs = dict(chat_id=admin_id, caption=_admin_caption(pay, "", None), parse_mode="HTML", reply_markup=_admin_markup(pay.id))
    if pay.receipt_type == "photo":
        await bot.send_photo(photo=pay.receipt_file_id, **kwargs)
    else:
        await bot.send_document(document=pay.receipt_file_id, **kwargs)
