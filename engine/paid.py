"""Paid-channel bots: students buy a plan (card receipt, promo codes, optional free trial) and get a
single-use invite link to the guarded channels; when the subscription ends the bot removes them
(without a permanent ban) and offers a renewal. Admin side: ``engine/paid_admin.py`` (``pa:`` callbacks,
``pa_*`` states); student side: ``pc:`` callbacks and ``pc_*`` states; the expiry loop is ``paid_notify``.
"""
from datetime import timedelta

from sqlalchemy import select, update
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.logger import get_logger
from engine import cinema, paid_admin, paid_logic as logic
from engine.audience import touch_user
from engine.booking_time import as_utc, fmt_dt, tz_of, utcnow
from models.paid import (
    PAY_APPROVED, PAY_PENDING, PAY_REJECTED, SUB_ACTIVE, PaidChannel, PaidPayment, PaidPlan, PaidPlanChannel,
    PaidPromo, PaidSettings, PaidSub,
)
from models.user_sessions import UserSession

logger = get_logger("paid")
esc = cinema.esc
show = cinema._show
money = logic.fmt_money
INVITE_TTL = timedelta(hours=24)
WELCOME = ("💎 <b>Yopiq kanalga obuna</b>\n\nTarifni tanlang va to‘lang: kanalga kirish havolasini darhol olasiz. "
           "Obuna tugashidan oldin eslatamiz.")


# ------------------------------------------------------------------ basics

async def get_settings(session, bot_id: int) -> PaidSettings:
    st = (await session.execute(select(PaidSettings).where(PaidSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = PaidSettings(bot_id=bot_id)
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> PaidSettings:
    st = await get_settings(session, bot.id)
    await cinema.ensure_start_menu(session, bot, WELCOME)
    return st


async def session_of(session, bot, user_id: int) -> UserSession:
    from engine.actions import get_user_session
    us = await get_user_session(session, bot.id, user_id)
    if us is None:
        menu = await cinema.ensure_start_menu(session, bot, WELCOME)
        us = UserSession(bot_id=bot.id, tg_user_id=user_id, current_menu_id=menu.id)
        session.add(us)
        await session.commit()
    return us


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


def person_of(user: dict) -> dict:
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or user.get("username") or "Foydalanuvchi"
    return {"id": user["id"], "name": name[:255], "username": user.get("username")}


def when(dt) -> str:
    return fmt_dt(dt, tz_of(None))


# ------------------------------------------------------------------ queries

async def plans_of(session, bot_id: int, active_only: bool = True) -> list[PaidPlan]:
    q = select(PaidPlan).where(PaidPlan.bot_id == bot_id).order_by(PaidPlan.id)
    if active_only:
        q = q.where(PaidPlan.is_active.is_(True))
    return list((await session.execute(q)).scalars().all())


async def plan_channels(session, plan_id: int, active_only: bool = True) -> list[PaidChannel]:
    q = (select(PaidChannel).join(PaidPlanChannel, PaidPlanChannel.channel_id == PaidChannel.id)
         .where(PaidPlanChannel.plan_id == plan_id).order_by(PaidChannel.id))
    if active_only:
        q = q.where(PaidChannel.is_active.is_(True))
    return list((await session.execute(q)).scalars().all())


async def user_subs(session, bot_id: int, uid: int) -> list[tuple[PaidSub, PaidPlan]]:
    rows = (await session.execute(
        select(PaidSub, PaidPlan).join(PaidPlan, PaidPlan.id == PaidSub.plan_id)
        .where(PaidSub.bot_id == bot_id, PaidSub.tg_user_id == uid).order_by(PaidSub.id))).all()
    return [(s, p) for s, p in rows]


def is_live(sub: PaidSub, now) -> bool:
    return sub.status == SUB_ACTIVE and as_utc(sub.expires_at) > now


async def access_channels(session, bot_id: int, uid: int, now, *, skip_sub: int | None = None) -> list[PaidChannel]:
    """Channels the user may be in right now: the union over their live subscriptions."""
    seen: dict[int, PaidChannel] = {}
    for sub, plan in await user_subs(session, bot_id, uid):
        if sub.id == skip_sub or not is_live(sub, now):
            continue
        for ch in await plan_channels(session, plan.id):
            seen[ch.id] = ch
    return list(seen.values())


# ------------------------------------------------------------------ telegram access

async def make_links(tg, channels, uid: int, now) -> list[tuple[str, str]]:
    out = []
    for ch in channels:
        try:
            link = await tg.create_chat_invite_link(chat_id=ch.chat_id, name=str(uid)[:32], member_limit=1,
                                                    expire_date=now + INVITE_TTL)
            out.append((ch.title, link.invite_link))
        except TelegramError as exc:
            logger.warning("paid: invite link for chat %s failed: %s", ch.chat_id, exc)
    return out


async def send_access(tg, session, bot, uid: int, intro: str, *, now=None) -> bool:
    """Intro text + one single-use link button per channel the user is entitled to."""
    now = now or utcnow()
    links = await make_links(tg, await access_channels(session, bot.id, uid, now), uid, now)
    rows = [[Btn(f"🔗 {title[:40]}", url=url)] for title, url in links]
    note = "\n\n⏳ Havolalar bir martalik va 24 soat amal qiladi." if links else \
        "\n\n⚠️ Kirish havolasini yaratib bo‘lmadi. Admin bilan bog‘laning."
    rows.append([Btn("🔄 Yangi havola", callback_data="pc:links"), Btn("🏠 Bosh sahifa", callback_data="pc:home")])
    try:
        await tg.send_message(chat_id=uid, text=intro + note, parse_mode="HTML", reply_markup=Markup(rows))
        return bool(links)
    except TelegramError as exc:
        logger.info("paid: access message to %s failed: %s", uid, exc)
        return False


async def remove_from(tg, channels, uid: int):
    """Kick without a permanent ban: ban, then lift the ban at once so they can come back after renewing."""
    for ch in channels:
        try:
            await tg.ban_chat_member(chat_id=ch.chat_id, user_id=uid)
            await tg.unban_chat_member(chat_id=ch.chat_id, user_id=uid, only_if_banned=True)
        except TelegramError as exc:
            logger.warning("paid: could not remove %s from chat %s: %s", uid, ch.chat_id, exc)


# ------------------------------------------------------------------ subscriptions

async def grant(session, bot, plan, person: dict, days: int, *, trial: bool = False, now=None) -> PaidSub:
    """Create or extend the person's subscription to ``plan`` by ``days``."""
    now = now or utcnow()
    sub = (await session.execute(select(PaidSub).where(
        PaidSub.bot_id == bot.id, PaidSub.tg_user_id == person["id"], PaidSub.plan_id == plan.id))).scalar_one_or_none()
    if sub is None:
        sub = PaidSub(bot_id=bot.id, plan_id=plan.id, tg_user_id=person["id"], started_at=now,
                      expires_at=logic.extend(None, now, days))
        session.add(sub)
    else:
        live = is_live(sub, now)
        sub.expires_at = logic.extend(sub.expires_at if live else None, now, days)
        if not live:
            sub.started_at = now
    sub.status, sub.is_trial = SUB_ACTIVE, trial
    sub.trial_used = sub.trial_used or trial
    sub.reminded_3 = sub.reminded_1 = False
    sub.user_name, sub.username = person["name"], person.get("username")
    await session.commit()
    return sub


async def trial_available(session, bot, uid: int) -> PaidPlan | None:
    st = await get_settings(session, bot.id)
    if not st.trial_enabled or not st.trial_plan_id:
        return None
    plan = await session.get(PaidPlan, st.trial_plan_id)
    if plan is None or plan.bot_id != bot.id or not plan.is_active:
        return None
    used = (await session.execute(select(PaidSub.id).where(
        PaidSub.bot_id == bot.id, PaidSub.tg_user_id == uid, PaidSub.trial_used.is_(True)).limit(1))).first()
    return None if used else plan


# ------------------------------------------------------------------ payments

async def reserve_promo(session, promo_id: int, now) -> bool:
    """Atomically take one use of a promo code."""
    res = await session.execute(
        update(PaidPromo).where(
            PaidPromo.id == promo_id, PaidPromo.is_active.is_(True),
            (PaidPromo.max_uses.is_(None)) | (PaidPromo.used_count < PaidPromo.max_uses),
            (PaidPromo.expires_at.is_(None)) | (PaidPromo.expires_at > now))
        .values(used_count=PaidPromo.used_count + 1))
    await session.commit()
    return res.rowcount == 1


async def release_promo(session, promo_id: int | None):
    if promo_id:
        await session.execute(update(PaidPromo).where(PaidPromo.id == promo_id, PaidPromo.used_count > 0)
                              .values(used_count=PaidPromo.used_count - 1))
        await session.commit()


async def draft_for(session, bot, plan, person: dict) -> PaidPayment:
    """The student's open, not yet submitted payment for ``plan`` (price snapshot refreshed)."""
    pay = (await session.execute(select(PaidPayment).where(
        PaidPayment.bot_id == bot.id, PaidPayment.plan_id == plan.id, PaidPayment.tg_user_id == person["id"],
        PaidPayment.status == "draft"))).scalars().first()
    if pay is None:
        pay = PaidPayment(bot_id=bot.id, plan_id=plan.id, tg_user_id=person["id"], status="draft",
                          original_price=plan.price, price=plan.price, days=plan.days)
        session.add(pay)
    pay.user_name, pay.username, pay.plan_title = person["name"], person.get("username"), plan.title
    pay.days, pay.original_price = plan.days, plan.price
    promo = await session.get(PaidPromo, pay.promo_id) if pay.promo_id else None
    pay.price = logic.discounted(plan.price, promo) if promo and not logic.promo_error(promo, utcnow()) else plan.price
    if promo is None or logic.promo_error(promo, utcnow()):
        pay.promo_id = pay.promo_code = None
    await session.commit()
    return pay


async def pending_of(session, bot_id: int, uid: int, plan_id: int) -> PaidPayment | None:
    return (await session.execute(select(PaidPayment).where(
        PaidPayment.bot_id == bot_id, PaidPayment.tg_user_id == uid, PaidPayment.plan_id == plan_id,
        PaidPayment.status == PAY_PENDING))).scalars().first()


def payment_text(pay: PaidPayment) -> str:
    who = f"👤 {esc(pay.user_name)}" + (f" @{esc(pay.username)}" if pay.username else "") + f"  <code>{pay.tg_user_id}</code>"
    text = f"🧾 <b>To‘lov #{pay.id}</b>\n{who}\n📦 {esc(pay.plan_title)} · {pay.days} kun\n💰 <b>{money(pay.price)}</b>"
    if pay.promo_code:
        text += f"  (🎟 {esc(pay.promo_code)}, asl narx {money(pay.original_price)})"
    return text


async def decide_payment(tg, session, bot, pay: PaidPayment, *, approve: bool, by: int | None = None,
                         reason: str | None = None) -> bool:
    """Approve or reject a submitted payment exactly once. Returns False if it was already decided."""
    final = PAY_APPROVED if approve else PAY_REJECTED
    claimed = await session.execute(
        update(PaidPayment).where(PaidPayment.id == pay.id, PaidPayment.status == PAY_PENDING)
        .values(status=final, decided_by=by, decided_at=utcnow(), reject_reason=reason))
    await session.commit()
    if claimed.rowcount == 0:
        await session.refresh(pay)
        return False
    await session.refresh(pay)
    if approve:
        plan = await session.get(PaidPlan, pay.plan_id)
        person = {"id": pay.tg_user_id, "name": pay.user_name, "username": pay.username}
        sub = await grant(session, bot, plan, person, pay.days)
        await send_access(tg, session, bot, pay.tg_user_id,
                          f"✅ <b>To‘lov tasdiqlandi!</b>\n📦 {esc(plan.title)}\n📅 Obuna: <b>{when(sub.expires_at)}</b> gacha")
    else:
        await release_promo(session, pay.promo_id)
        text = "❌ <b>To‘lov rad etildi.</b>" + (f"\nSabab: {esc(reason)}" if reason else "")
        try:
            await tg.send_message(chat_id=pay.tg_user_id, text=text, parse_mode="HTML", reply_markup=Markup(
                [[Btn("🔁 Qayta urinish", callback_data=f"pc:p:{pay.plan_id}")]]))
        except TelegramError as exc:
            logger.info("paid: rejection notice to %s failed: %s", pay.tg_user_id, exc)
    return True


# ------------------------------------------------------------------ student screens

async def show_home(tg, callback, uid, session, bot):
    st = await get_settings(session, bot.id)
    rows = [[Btn("💳 Obuna olish", callback_data="pc:plans"), Btn("🔗 Mening obunam", callback_data="pc:my")]]
    trial = await trial_available(session, bot, uid)
    if trial:
        rows.append([Btn(f"🎁 Bepul sinov ({st.trial_days} kun)", callback_data="pc:trial")])
    if await cinema.is_admin(session, bot, uid):
        rows.append([Btn("🛠 Admin panel", callback_data="pa:home")])
    menu = await cinema.ensure_start_menu(session, bot, WELCOME)
    await show(tg, callback, uid, st.welcome_text or menu.message_text or WELCOME, Markup(rows))


async def show_plans(tg, callback, uid, session, bot):
    plans = await plans_of(session, bot.id)
    rows = [[Btn(f"{p.title} — {money(p.price)} ({p.days} kun)"[:60], callback_data=f"pc:p:{p.id}")] for p in plans]
    rows.append([Btn("🏠 Bosh sahifa", callback_data="pc:home")])
    await show(tg, callback, uid, "💳 <b>Tariflar</b>\n\n" + ("Tanlang:" if plans else "Hozircha tarif yo‘q."), Markup(rows))


async def show_plan(tg, callback, uid, session, bot, plan, person):
    draft = await draft_for(session, bot, plan, person)
    channels = await plan_channels(session, plan.id)
    text = f"📦 <b>{esc(plan.title)}</b>\n"
    if plan.description:
        text += f"\n{esc(plan.description)}\n"
    text += f"\n⏱ Muddat: <b>{plan.days} kun</b>\n📢 Kanallar: {', '.join(esc(c.title) for c in channels) or '—'}\n"
    if draft.promo_code:
        text += f"💰 Narx: <s>{money(plan.price)}</s> → <b>{money(draft.price)}</b>  (🎟 {esc(draft.promo_code)})"
    else:
        text += f"💰 Narx: <b>{money(plan.price)}</b>"
    rows = [[Btn("💳 Sotib olish" if draft.price else "🎁 Bepul olish", callback_data=f"pc:buy:{plan.id}")],
            [Btn("🎟 Promokod", callback_data=f"pc:promo:{plan.id}")],
            [Btn("⬅️ Tariflar", callback_data="pc:plans")]]
    await show(tg, callback, uid, text, Markup(rows))


async def show_my(tg, callback, uid, session, bot):
    now = utcnow()
    lines, live = [], False
    for sub, plan in await user_subs(session, bot.id, uid):
        if is_live(sub, now):
            live = True
            lines.append(f"✅ <b>{esc(plan.title)}</b>{' (sinov)' if sub.is_trial else ''} — {when(sub.expires_at)} gacha "
                         f"({logic.days_left(sub.expires_at, now)} kun)")
        else:
            lines.append(f"⌛️ {esc(plan.title)} — tugagan")
    rows = []
    if live:
        rows.append([Btn("🔗 Kirish havolasi", callback_data="pc:links")])
    rows.append([Btn("🔄 Uzaytirish / sotib olish", callback_data="pc:plans")])
    rows.append([Btn("🏠 Bosh sahifa", callback_data="pc:home")])
    await show(tg, callback, uid, "🔗 <b>Mening obunam</b>\n\n" + ("\n".join(lines) or "Hali obunangiz yo‘q."), Markup(rows))


async def start_buy(tg, callback, uid, session, bot, us, plan, person):
    if (await pending_of(session, bot.id, uid, plan.id)) is not None:
        return await show(tg, callback, uid, "⏳ Bu tarif uchun to‘lovingiz tekshirilmoqda. Natijani shu yerda xabar qilamiz.",
                          Markup([[Btn("🏠 Bosh sahifa", callback_data="pc:home")]]))
    previous = (await session.execute(select(PaidPayment.promo_code).where(
        PaidPayment.bot_id == bot.id, PaidPayment.plan_id == plan.id, PaidPayment.tg_user_id == uid,
        PaidPayment.status == "draft"))).scalars().first()
    draft = await draft_for(session, bot, plan, person)
    dropped = previous and not draft.promo_code  # the code expired or ran out since it was entered
    if draft.price == 0:  # a 100% promo code: nothing to pay
        return await submit(tg, uid, session, bot, us, draft, None, None)
    st = await get_settings(session, bot.id)
    if not st.card_number:
        return await show(tg, callback, uid, "⚠️ To‘lov usuli hali sozlanmagan. Admin bilan bog‘laning.",
                          Markup([[Btn("⬅️ Orqaga", callback_data=f"pc:p:{plan.id}")]]))
    await set_state(session, us, "pc_receipt", {"pay": draft.id})
    text = ("⚠️ Promokod endi amal qilmaydi, narx asl holatiga qaytdi.\n\n" if dropped else "")
    text += (f"💳 <b>To‘lov</b>\n\n📦 {esc(plan.title)} · {plan.days} kun\n💰 Summa: <b>{money(draft.price)}</b>\n\n"
            f"Karta: <code>{esc(st.card_number)}</code>\n" + (f"Egasi: {esc(st.card_holder)}\n" if st.card_holder else "")
            + (f"\n{esc(st.pay_note)}\n" if st.pay_note else "")
            + "\n📸 O‘tkazgach <b>chek rasmini</b> shu yerga yuboring. Bekor qilish: /cancel")
    await show(tg, callback, uid, text, Markup([[Btn("✖️ Bekor qilish", callback_data=f"pc:p:{plan.id}")]]))


async def submit(tg, uid, session, bot, us, pay: PaidPayment, file_id, kind) -> bool:
    """Draft -> pending (or approved at once when free). Takes the promo use; False if the code ran out."""
    now = utcnow()
    if pay.promo_id and not await reserve_promo(session, pay.promo_id, now):
        pay.promo_id = pay.promo_code = None
        pay.price = pay.original_price
        await session.commit()
        await set_state(session, us)
        await tg.send_message(chat_id=uid, text="⚠️ Promokod ishlatilib bo‘lingan, narx asl holatiga qaytdi.",
                              reply_markup=Markup([[Btn("📦 Tarif", callback_data=f"pc:p:{pay.plan_id}")]]))
        return False
    pay.status, pay.receipt_file_id, pay.receipt_type = PAY_PENDING, file_id, kind
    await session.commit()
    await set_state(session, us)
    if pay.price == 0:
        await decide_payment(tg, session, bot, pay, approve=True, by=None)
        return True
    await tg.send_message(chat_id=uid, text="✅ Chek yuborildi. Admin tekshirgach xabar beramiz.",
                          reply_markup=Markup([[Btn("🏠 Bosh sahifa", callback_data="pc:home")]]))
    await paid_admin.notify_receipt(tg, session, bot, pay)
    return True


async def on_receipt(bot, message, session, tg, us, uid) -> bool:
    pay = await session.get(PaidPayment, (us.state_data or {}).get("pay") or 0)
    if pay is None or pay.bot_id != bot.id or pay.tg_user_id != uid or pay.status != "draft":
        await set_state(session, us)
        return False
    if message.get("photo"):
        file_id, kind = message["photo"][-1]["file_id"], "photo"
    elif (message.get("document") or {}).get("mime_type", "").startswith("image/"):
        file_id, kind = message["document"]["file_id"], "document"
    else:
        await tg.send_message(chat_id=uid, text="📸 Chekning rasmini yuboring. Bekor qilish: /cancel")
        return True
    await submit(tg, uid, session, bot, us, pay, file_id, kind)
    return True


async def on_promo_text(bot, message, session, tg, us, uid, person) -> bool:
    plan = await session.get(PaidPlan, (us.state_data or {}).get("plan") or 0)
    if plan is None or plan.bot_id != bot.id or not plan.is_active:
        await set_state(session, us)
        return False
    code = logic.norm_code(message.get("text") or "")
    promo = (await session.execute(select(PaidPromo).where(PaidPromo.bot_id == bot.id, PaidPromo.code == code))).scalar_one_or_none()
    error = logic.promo_error(promo, utcnow())
    if error:
        await tg.send_message(chat_id=uid, text=f"❌ {error} Boshqa kod yuboring yoki /cancel.")
        return True
    draft = await draft_for(session, bot, plan, person)
    draft.promo_id, draft.promo_code = promo.id, promo.code
    await session.commit()
    await set_state(session, us)
    await tg.send_message(chat_id=uid, text=f"✅ Promokod qo‘llandi: <b>{logic.promo_label(promo)}</b> chegirma.", parse_mode="HTML")
    await show_plan(tg, None, uid, session, bot, plan, person)
    return True


# ------------------------------------------------------------------ bot membership of channels

async def on_membership(bot, event: dict, session, tg):
    chat = event.get("chat") or {}
    if chat.get("type") not in ("channel", "group", "supergroup"):
        return
    member = event.get("new_chat_member") or {}
    status = member.get("status")
    ch = (await session.execute(select(PaidChannel).where(PaidChannel.bot_id == bot.id, PaidChannel.chat_id == chat["id"]))).scalar_one_or_none()
    if status == "administrator":
        title = (chat.get("title") or chat.get("username") or str(chat["id"]))[:255]
        created = ch is None
        if created:
            ch = PaidChannel(bot_id=bot.id, chat_id=chat["id"], title=title,
                             chat_type="channel" if chat.get("type") == "channel" else "group")
            session.add(ch)
        ch.title, ch.is_active = title, True
        await session.commit()
        missing = [name for key, name in (("can_invite_users", "«Foydalanuvchilarni taklif qilish»"),
                                          ("can_restrict_members", "«Foydalanuvchilarni cheklash»")) if member.get(key) is False]
        text = f"✅ <b>{esc(title)}</b> ulandi." + (f"\n⚠️ Botga {', '.join(missing)} huquqini bering." if missing else "")
        if created or missing:
            for admin_id in await cinema.admin_ids(session, bot):
                try:
                    await tg.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
                except TelegramError:
                    pass
    elif status in ("left", "kicked") and ch:
        ch.is_active = False
        await session.commit()


# ------------------------------------------------------------------ entry point

async def handle(bot, update_, session, tg):
    if update_.get("callback_query"):
        await _on_callback(bot, update_["callback_query"], session, tg)
    elif update_.get("message"):
        await _on_message(bot, update_["message"], session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    uid = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    if data.startswith("pa:"):
        if await cinema.is_admin(session, bot, uid):
            await paid_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    if not data.startswith("pc:"):
        return
    us = await session_of(session, bot, uid)
    parts = data.split(":")
    act, arg = parts[1], parts[2:]
    num = int(arg[0]) if arg and arg[0].isdigit() else None
    if us.state and us.state.startswith("pc_"):
        await set_state(session, us)
    person = person_of(user)
    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "plans":
        return await show_plans(tg, callback, uid, session, bot)
    if act == "my":
        return await show_my(tg, callback, uid, session, bot)
    if act == "links":
        if not await access_channels(session, bot.id, uid, utcnow()):
            return await show(tg, callback, uid, "Faol obunangiz yo‘q.", Markup([[Btn("💳 Obuna olish", callback_data="pc:plans")]]))
        await send_access(tg, session, bot, uid, "🔗 <b>Kirish havolalari</b>")
        return
    if act == "trial":
        plan = await trial_available(session, bot, uid)
        if plan is None:
            return await show_home(tg, callback, uid, session, bot)
        st = await get_settings(session, bot.id)
        sub = await grant(session, bot, plan, person, st.trial_days, trial=True)
        return await send_access(tg, session, bot, uid, f"🎁 <b>Bepul sinov boshlandi!</b>\n📅 {when(sub.expires_at)} gacha")
    if num is None:
        return
    plan = await session.get(PaidPlan, num)
    if plan is None or plan.bot_id != bot.id or not plan.is_active:
        return await show_plans(tg, callback, uid, session, bot)
    if act == "p":
        return await show_plan(tg, callback, uid, session, bot, plan, person)
    if act == "promo":
        await set_state(session, us, "pc_promo", {"plan": plan.id})
        return await show(tg, callback, uid, "🎟 Promokodni yozing. Bekor qilish: /cancel",
                          Markup([[Btn("✖️ Bekor qilish", callback_data=f"pc:p:{plan.id}")]]))
    if act == "buy":
        return await start_buy(tg, callback, uid, session, bot, us, plan, person)


async def _on_message(bot, message, session, tg):
    if (message.get("chat") or {}).get("type") != "private":
        return
    sender = message["from"]
    uid = sender["id"]
    if sender.get("is_bot"):
        return
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    await touch_user(session, bot.id, sender)
    admin = await cinema.is_admin(session, bot, uid)
    us = await session_of(session, bot, uid)
    if cmd in ("/start", "/cancel"):
        had = bool(us.state and us.state.startswith(("pc_", "pa_")))
        await set_state(session, us)
        if cmd == "/cancel" and had:
            await tg.send_message(chat_id=uid, text="Bekor qilindi.")
        return await show_home(tg, None, uid, session, bot)
    if admin and cmd == "/admin":
        await set_state(session, us)
        return await paid_admin.show_home(tg, None, uid, session, bot)
    state = us.state or ""
    if state.startswith("pa_") and admin:
        if await paid_admin.on_message(bot, message, session, tg, us):
            return
    elif state == "pc_receipt":
        await on_receipt(bot, message, session, tg, us, uid)
    elif state == "pc_promo":
        await on_promo_text(bot, message, session, tg, us, uid, person_of(sender))
