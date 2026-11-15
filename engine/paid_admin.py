"""Admin side of paid-channel bots (``/admin`` in the child bot): channels, plans, payments, subscribers,
promo codes, settings, statistics. Callbacks ``pa:*``, states ``pa_*``."""
from datetime import timedelta

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.logger import get_logger
from engine import cinema, paid_logic as logic
from engine.booking_time import as_utc, utcnow
from models.paid import (
    PAY_APPROVED, PAY_PENDING, SUB_ACTIVE, SUB_CANCELLED, SUB_EXPIRED, PaidChannel, PaidPayment, PaidPlan,
    PaidPlanChannel, PaidPromo, PaidSub,
)

logger = get_logger("paid.admin")
esc = cinema.esc
show = cinema._show
money = logic.fmt_money
PAGE = 8
FILTERS = {"a": "✅ Faol", "e": "⏰ Tugayotgan", "x": "⌛️ Tugagan"}
SETTING_FIELDS = {
    "card": ("card_number", "💳 Karta raqami", 40), "holder": ("card_holder", "👤 Karta egasi", 120),
    "note": ("pay_note", "📝 To‘lov izohi", 700), "welcome": ("welcome_text", "👋 Salomlashish matni", 1500),
}


def kb(rows):
    return Markup(rows)


def back(data="pa:home", text="⬅️ Orqaga"):
    return [Btn(text, callback_data=data)]


def core():
    from engine import paid
    return paid


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


async def count(session, model, *where) -> int:
    return (await session.execute(select(func.count(model.id)).where(*where))).scalar() or 0


async def live_where(bot_id: int, now):
    return (PaidSub.bot_id == bot_id, PaidSub.status == SUB_ACTIVE, PaidSub.expires_at > now)


# ------------------------------------------------------------------ notifications

def receipt_markup(pay):
    return kb([[Btn("✅ To‘lov to‘g‘ri", callback_data=f"pa:pok:{pay.id}"), Btn("❌ Rad etish", callback_data=f"pa:prj:{pay.id}")]])


async def send_receipt(tg, admin_id, pay):
    text = core().payment_text(pay)
    if pay.receipt_type == "document":
        await tg.send_document(chat_id=admin_id, document=pay.receipt_file_id, caption=text, parse_mode="HTML", reply_markup=receipt_markup(pay))
    else:
        await tg.send_photo(chat_id=admin_id, photo=pay.receipt_file_id, caption=text, parse_mode="HTML", reply_markup=receipt_markup(pay))


async def notify_receipt(tg, session, bot, pay):
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await send_receipt(tg, admin_id, pay)
        except TelegramError as exc:
            logger.info("receipt notice to %s failed: %s", admin_id, exc)


# ------------------------------------------------------------------ home

async def show_home(tg, callback, uid, session, bot):
    now = utcnow()
    pending = await count(session, PaidPayment, PaidPayment.bot_id == bot.id, PaidPayment.status == PAY_PENDING)
    live = await count(session, PaidSub, *await live_where(bot.id, now))
    rows = [[Btn("📢 Kanallar", callback_data="pa:ch"), Btn("💳 Tariflar", callback_data="pa:pl")],
            [Btn(f"🧾 To‘lovlar ({pending})", callback_data="pa:pays"), Btn(f"👥 Obunachilar ({live})", callback_data="pa:subs:a:0")],
            [Btn("🎟 Promokodlar", callback_data="pa:pr"), Btn("⚙️ Sozlamalar", callback_data="pa:set")],
            [Btn("📊 Statistika", callback_data="pa:stats")]]
    channels = await count(session, PaidChannel, PaidChannel.bot_id == bot.id)
    text = "💎 <b>Pullik kanal paneli</b>\n\n" + (
        "Botni yopiq kanalingizga <b>administrator</b> qiling («Foydalanuvchilarni taklif qilish» va «Foydalanuvchilarni cheklash» "
        "huquqlari bilan): u shu yerda paydo bo‘ladi. Keyin tarif yarating va to‘lov kartasini kiriting."
        if not channels else f"Faol obunachilar: <b>{live}</b> · Kutilayotgan to‘lovlar: <b>{pending}</b>")
    await show(tg, callback, uid, text, kb(rows))


# ------------------------------------------------------------------ channels

async def show_channels(tg, callback, uid, session, bot):
    chans = (await session.execute(select(PaidChannel).where(PaidChannel.bot_id == bot.id).order_by(PaidChannel.id))).scalars().all()
    rows = [[Btn(("✅ " if c.is_active else "⏸ ") + c.title[:40], callback_data=f"pa:cht:{c.id}")] for c in chans]
    rows.append(back())
    await show(tg, callback, uid, "📢 <b>Kanallar</b>\n\nYoqish/o‘chirish uchun bosing. O‘chirilgan kanalga yangi havola berilmaydi."
               + ("" if chans else "\n\nHali yo‘q: botni kanalga administrator qiling."), kb(rows))


# ------------------------------------------------------------------ plans

async def show_plans(tg, callback, uid, session, bot):
    plans = await core().plans_of(session, bot.id, active_only=False)
    rows = [[Btn(("" if p.is_active else "⏸ ") + f"{p.title} — {money(p.price)} / {p.days} kun"[:55], callback_data=f"pa:p:{p.id}")] for p in plans]
    rows.insert(0, [Btn("➕ Yangi tarif", callback_data="pa:pn")])
    rows.append(back())
    await show(tg, callback, uid, "💳 <b>Tariflar</b>", kb(rows))


async def show_plan(tg, callback, uid, session, bot, plan):
    linked = {c.id for c in await core().plan_channels(session, plan.id, active_only=False)}
    chans = (await session.execute(select(PaidChannel).where(PaidChannel.bot_id == bot.id).order_by(PaidChannel.id))).scalars().all()
    subs = await count(session, PaidSub, PaidSub.plan_id == plan.id)
    text = (f"💳 <b>{esc(plan.title)}</b>{'' if plan.is_active else '  ⏸'}\n⏱ {plan.days} kun · 💰 {money(plan.price)}\n"
            f"📝 {esc(plan.description) or '—'}\n👥 Obunachilar: {subs}\n\n📢 Kirish beradigan kanallar (bosib o‘zgartiring):"
            + ("" if chans else "\n⚠️ Avval botni kanalga administrator qiling."))
    f = f"pa:pe:{plan.id}:"
    rows = [[Btn("✏️ Nom", callback_data=f + "title"), Btn("⏱ Kun", callback_data=f + "days"), Btn("💰 Narx", callback_data=f + "price")],
            [Btn("📝 Tavsif", callback_data=f + "desc")]]
    rows += [[Btn(("✅ " if c.id in linked else "▫️ ") + c.title[:40], callback_data=f"pa:pc:{plan.id}:{c.id}")] for c in chans]
    rows.append([Btn("▶️ Yoqish" if not plan.is_active else "⏸ To‘xtatish", callback_data=f"pa:pt:{plan.id}"),
                 Btn("🗑 O‘chirish", callback_data=f"pa:pd:{plan.id}")])
    rows.append(back("pa:pl"))
    await show(tg, callback, uid, text, kb(rows))


async def delete_plan(tg, callback, uid, session, bot, plan):
    used = await count(session, PaidSub, PaidSub.plan_id == plan.id) + await count(session, PaidPayment, PaidPayment.plan_id == plan.id)
    if used:
        plan.is_active = False
        await session.commit()
        return await show(tg, callback, uid, "ℹ️ Bu tarifda obuna/to‘lovlar bor, shuning uchun o‘chirilmadi — to‘xtatildi (yangi sotilmaydi).",
                          kb([back(f"pa:p:{plan.id}")]))
    await session.execute(delete(PaidPlanChannel).where(PaidPlanChannel.plan_id == plan.id))
    await session.delete(plan)
    await session.commit()
    await show_plans(tg, callback, uid, session, bot)


# ------------------------------------------------------------------ payments

async def show_payments(tg, callback, uid, session, bot):
    pays = (await session.execute(select(PaidPayment).where(PaidPayment.bot_id == bot.id, PaidPayment.status == PAY_PENDING)
                                  .order_by(PaidPayment.id).limit(30))).scalars().all()
    rows = [[Btn(f"🧾 #{p.id} {p.user_name[:18]} · {money(p.price)}", callback_data=f"pa:pay:{p.id}")] for p in pays]
    rows.append(back())
    await show(tg, callback, uid, f"🧾 <b>Kutilayotgan to‘lovlar</b> ({len(pays)})", kb(rows))


async def decide(bot, callback, session, tg, uid, pay, approve: bool, reason=None):
    done = await core().decide_payment(tg, session, bot, pay, approve=approve, by=uid, reason=reason)
    who = esc((callback.get("from") or {}).get("first_name") or "admin") if callback else "admin"
    text = (core().payment_text(pay) + f"\n\n{'✅ Tasdiqlandi' if approve else '❌ Rad etildi'} — {who}") if done \
        else "ℹ️ Bu to‘lov allaqachon ko‘rib chiqilgan."
    message = (callback or {}).get("message") or {}
    if message.get("photo") or message.get("document") or message.get("caption"):
        try:
            await tg.edit_message_caption(chat_id=uid, message_id=callback["message"]["message_id"], caption=text, parse_mode="HTML")
            return
        except TelegramError:
            pass
    await show(tg, callback, uid, text, None)


# ------------------------------------------------------------------ subscribers

def _filter(f: str, bot_id: int, now):
    base = [PaidSub.bot_id == bot_id]
    if f == "a":
        return base + [PaidSub.status == SUB_ACTIVE, PaidSub.expires_at > now]
    if f == "e":
        return base + [PaidSub.status == SUB_ACTIVE, PaidSub.expires_at > now, PaidSub.expires_at <= now + timedelta(days=3)]
    return base + [(PaidSub.status != SUB_ACTIVE) | (PaidSub.expires_at <= now)]


async def show_subs(tg, callback, uid, session, bot, f: str, page: int):
    now = utcnow()
    where = _filter(f, bot.id, now)
    total = await count(session, PaidSub, *where)
    rows_db = (await session.execute(select(PaidSub, PaidPlan).join(PaidPlan, PaidPlan.id == PaidSub.plan_id).where(*where)
                                     .order_by(PaidSub.expires_at).limit(PAGE).offset(page * PAGE))).all()
    rows = [[Btn((f"{s.user_name[:18]} · {p.title[:14]} · " + core().when(s.expires_at)[:10])[:60], callback_data=f"pa:s:{s.id}")] for s, p in rows_db]
    nav = []
    if page > 0:
        nav.append(Btn("◀️", callback_data=f"pa:subs:{f}:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(Btn("▶️", callback_data=f"pa:subs:{f}:{page + 1}"))
    tabs = [Btn(("•" if k == f else "") + v, callback_data=f"pa:subs:{k}:0") for k, v in FILTERS.items()]
    rows = [tabs] + rows + ([nav] if nav else []) + [[Btn("➕ Qo‘lda qo‘shish", callback_data="pa:gr")], back()]
    await show(tg, callback, uid, f"👥 <b>Obunachilar</b> — {FILTERS[f]}: {total}", kb(rows))


async def show_sub(tg, callback, uid, session, bot, sub):
    plan = await session.get(PaidPlan, sub.plan_id)
    now = utcnow()
    live = core().is_live(sub, now)
    text = (f"👤 <b>{esc(sub.user_name)}</b>" + (f" @{esc(sub.username)}" if sub.username else "") + f"  <code>{sub.tg_user_id}</code>\n"
            f"📦 {esc(plan.title)}{' (sinov)' if sub.is_trial else ''}\n"
            + (f"✅ Faol — {core().when(sub.expires_at)} gacha ({logic.days_left(sub.expires_at, now)} kun)" if live
               else f"⌛️ {'Bekor qilingan' if sub.status == SUB_CANCELLED else 'Tugagan'} ({core().when(sub.expires_at)})"))
    rows = [[Btn("➕ 7 kun", callback_data=f"pa:sx:{sub.id}:7"), Btn("➕ 30 kun", callback_data=f"pa:sx:{sub.id}:30")],
            [Btn("🔗 Havola yuborish", callback_data=f"pa:sl:{sub.id}")]]
    if live:
        rows.append([Btn("⛔ Bekor qilish", callback_data=f"pa:sc:{sub.id}")])
    rows.append(back("pa:subs:a:0"))
    await show(tg, callback, uid, text, kb(rows))


async def cancel_sub(tg, session, bot, sub, status=SUB_CANCELLED):
    """End a subscription now and remove the user from channels no other live subscription covers."""
    plan = await session.get(PaidPlan, sub.plan_id)
    sub.status = status
    await session.commit()
    keep = {c.id for c in await core().access_channels(session, bot.id, sub.tg_user_id, utcnow(), skip_sub=sub.id)}
    gone = [c for c in await core().plan_channels(session, plan.id, active_only=False) if c.id not in keep]
    await core().remove_from(tg, gone, sub.tg_user_id)
    return gone


# ------------------------------------------------------------------ promos

async def show_promos(tg, callback, uid, session, bot):
    promos = (await session.execute(select(PaidPromo).where(PaidPromo.bot_id == bot.id).order_by(PaidPromo.id))).scalars().all()
    rows = [[Btn(("" if p.is_active else "⏸ ") + f"{p.code} · {logic.promo_label(p)} · {p.used_count}/{p.max_uses or '∞'}", callback_data=f"pa:pro:{p.id}")] for p in promos]
    rows.insert(0, [Btn("➕ Yangi promokod", callback_data="pa:prn")])
    rows.append(back())
    await show(tg, callback, uid, "🎟 <b>Promokodlar</b>", kb(rows))


# ------------------------------------------------------------------ settings / stats

async def show_settings(tg, callback, uid, session, bot):
    st = await core().get_settings(session, bot.id)
    plan = await session.get(PaidPlan, st.trial_plan_id) if st.trial_plan_id else None
    text = ("⚙️ <b>Sozlamalar</b>\n\n"
            f"💳 Karta: {esc(st.card_number) or '—'}\n👤 Egasi: {esc(st.card_holder) or '—'}\n📝 Izoh: {esc(st.pay_note) or '—'}\n\n"
            f"🎁 Bepul sinov: <b>{'yoqilgan' if st.trial_enabled else 'o‘chiq'}</b> · {st.trial_days} kun · tarif: {esc(plan.title) if plan else '—'}")
    rows = [[Btn("💳 Karta", callback_data="pa:se:card"), Btn("👤 Egasi", callback_data="pa:se:holder")],
            [Btn("📝 Izoh", callback_data="pa:se:note"), Btn("👋 Salomlashish", callback_data="pa:se:welcome")],
            [Btn("🎁 Sinovni " + ("o‘chirish" if st.trial_enabled else "yoqish"), callback_data="pa:trt"),
             Btn("⏱ Sinov kunlari", callback_data="pa:trd")],
            [Btn("📦 Sinov tarifi", callback_data="pa:trp")], back()]
    await show(tg, callback, uid, text, kb(rows))


async def show_stats(tg, callback, uid, session, bot):
    now = utcnow()
    live = await count(session, PaidSub, *_filter("a", bot.id, now))
    soon = await count(session, PaidSub, *_filter("e", bot.id, now))
    ended = await count(session, PaidSub, *_filter("x", bot.id, now))
    trials = await count(session, PaidSub, *_filter("a", bot.id, now), PaidSub.is_trial.is_(True))
    ok = (PaidPayment.bot_id == bot.id, PaidPayment.status == PAY_APPROVED)
    total = (await session.execute(select(func.coalesce(func.sum(PaidPayment.price), 0)).where(*ok))).scalar() or 0
    month = (await session.execute(select(func.coalesce(func.sum(PaidPayment.price), 0)).where(*ok, PaidPayment.decided_at >= now - timedelta(days=30)))).scalar() or 0
    lines = [f"✅ Faol: <b>{live}</b> (shundan sinov: {trials})", f"⏰ 3 kunda tugaydi: <b>{soon}</b>", f"⌛️ Tugagan/bekor: <b>{ended}</b>",
             f"\n💰 Jami tushum: <b>{money(total)}</b>", f"💰 Oxirgi 30 kun: <b>{money(month)}</b>"]
    for plan in await core().plans_of(session, bot.id, active_only=False):
        n = await count(session, PaidSub, *_filter("a", bot.id, now), PaidSub.plan_id == plan.id)
        lines.append(f"• {esc(plan.title)}: {n} faol")
    await show(tg, callback, uid, "📊 <b>Statistika</b>\n\n" + "\n".join(lines), kb([back()]))


# ------------------------------------------------------------------ routing

async def on_callback(bot, callback, session, tg, us):
    uid = callback["from"]["id"]
    parts = (callback.get("data") or "").split(":")[1:]
    act, arg = (parts[0] if parts else "home"), parts[1:]
    num = int(arg[0]) if arg and arg[0].isdigit() else None
    if us.state and us.state.startswith("pa_"):
        await set_state(session, us)
    c = core()

    simple = {"home": show_home, "ch": show_channels, "pl": show_plans, "pays": show_payments, "pr": show_promos,
              "set": show_settings, "stats": show_stats}
    if act in simple:
        return await simple[act](tg, callback, uid, session, bot)
    if act == "subs":
        return await show_subs(tg, callback, uid, session, bot, arg[0] if arg and arg[0] in FILTERS else "a",
                               int(arg[1]) if len(arg) > 1 and arg[1].isdigit() else 0)
    if act == "pn":
        await set_state(session, us, "pa_pn", {"step": "title"})
        return await show(tg, callback, uid, "💳 Yangi tarif nomini yozing (masalan: <i>1 oylik</i>).", kb([back("pa:pl", "✖️ Bekor qilish")]))
    if act == "prn":
        await set_state(session, us, "pa_prn", {"step": "code"})
        return await show(tg, callback, uid, "🎟 Promokod yozing (3–40 belgi: harf, raqam, - yoki _).", kb([back("pa:pr", "✖️ Bekor qilish")]))
    if act == "gr":
        await set_state(session, us, "pa_gr", {"step": "id"})
        return await show(tg, callback, uid, "➕ Obuna beriladigan foydalanuvchining <b>Telegram ID</b> sini yozing.", kb([back("pa:subs:a:0", "✖️ Bekor qilish")]))
    if act == "se" and arg and arg[0] in SETTING_FIELDS:
        _, label, _ = SETTING_FIELDS[arg[0]]
        await set_state(session, us, "pa_se", {"field": arg[0]})
        return await show(tg, callback, uid, f"{label}\n\nYangi qiymatni yozing. O‘chirish: <code>/clear</code>.", kb([back("pa:set", "✖️ Bekor qilish")]))
    if act == "trt":
        st = await c.get_settings(session, bot.id)
        st.trial_enabled = not st.trial_enabled
        await session.commit()
        return await show_settings(tg, callback, uid, session, bot)
    if act == "trd":
        await set_state(session, us, "pa_se", {"field": "trial_days"})
        return await show(tg, callback, uid, "⏱ Bepul sinov necha kun bo‘lsin? (1–365)", kb([back("pa:set", "✖️ Bekor qilish")]))
    if act == "trp":
        plans = await c.plans_of(session, bot.id)
        rows = [[Btn(p.title[:40], callback_data=f"pa:trs:{p.id}")] for p in plans] + [back("pa:set")]
        return await show(tg, callback, uid, "📦 Bepul sinov qaysi tarif kanallariga kirish bersin?", kb(rows))
    if num is None:
        return
    if act == "trs":
        plan = await session.get(PaidPlan, num)
        if plan and plan.bot_id == bot.id:
            (await c.get_settings(session, bot.id)).trial_plan_id = plan.id
            await session.commit()
        return await show_settings(tg, callback, uid, session, bot)
    if act == "cht":
        ch = await session.get(PaidChannel, num)
        if ch and ch.bot_id == bot.id:
            ch.is_active = not ch.is_active
            await session.commit()
        return await show_channels(tg, callback, uid, session, bot)
    if act in ("p", "pe", "pt", "pd", "pd2", "pc"):
        plan = await session.get(PaidPlan, num)
        if plan is None or plan.bot_id != bot.id:
            return await show_plans(tg, callback, uid, session, bot)
        if act == "p":
            return await show_plan(tg, callback, uid, session, bot, plan)
        if act == "pt":
            plan.is_active = not plan.is_active
            await session.commit()
            return await show_plan(tg, callback, uid, session, bot, plan)
        if act == "pd":
            return await show(tg, callback, uid, f"🗑 «{esc(plan.title)}» tarifi o‘chirilsinmi?",
                              kb([[Btn("✅ Ha", callback_data=f"pa:pd2:{plan.id}"), Btn("✖️ Yo‘q", callback_data=f"pa:p:{plan.id}")]]))
        if act == "pd2":
            return await delete_plan(tg, callback, uid, session, bot, plan)
        if act == "pc" and len(arg) > 1 and arg[1].isdigit():
            ch = await session.get(PaidChannel, int(arg[1]))
            if ch and ch.bot_id == bot.id:
                link = await session.get(PaidPlanChannel, (plan.id, ch.id))
                if link:
                    await session.delete(link)
                else:
                    session.add(PaidPlanChannel(plan_id=plan.id, channel_id=ch.id))
                await session.commit()
            return await show_plan(tg, callback, uid, session, bot, plan)
        if act == "pe" and len(arg) > 1 and arg[1] in ("title", "days", "price", "desc"):
            labels = {"title": "nomini", "days": "muddatini (kun)", "price": "narxini (so‘m)", "desc": "tavsifini (o‘chirish: /clear)"}
            await set_state(session, us, "pa_pe", {"plan": plan.id, "field": arg[1]})
            return await show(tg, callback, uid, f"✏️ Tarif {labels[arg[1]]} yozing.", kb([back(f"pa:p:{plan.id}", "✖️ Bekor qilish")]))
        return
    if act in ("pay", "pok", "prj"):
        pay = await session.get(PaidPayment, num)
        if pay is None or pay.bot_id != bot.id:
            return
        if act == "pay":
            return await send_receipt(tg, uid, pay) if pay.status == PAY_PENDING else await show(tg, callback, uid, "ℹ️ Bu to‘lov allaqachon ko‘rib chiqilgan.", kb([back("pa:pays")]))
        if act == "pok":
            return await decide(bot, callback, session, tg, uid, pay, True)
        await set_state(session, us, "pa_rj", {"pay": pay.id})
        return await tg.send_message(chat_id=uid, text="❌ Rad etish sababini yozing (yoki /skip — sababsiz).")
    if act in ("s", "sx", "sl", "sc", "sc2"):
        sub = await session.get(PaidSub, num)
        if sub is None or sub.bot_id != bot.id:
            return
        plan = await session.get(PaidPlan, sub.plan_id)
        person = {"id": sub.tg_user_id, "name": sub.user_name, "username": sub.username}
        if act == "s":
            return await show_sub(tg, callback, uid, session, bot, sub)
        if act == "sx" and len(arg) > 1 and arg[1].isdigit():
            sub = await c.grant(session, bot, plan, person, int(arg[1]), trial=False)
            await c.send_access(tg, session, bot, sub.tg_user_id, f"➕ Obunangiz uzaytirildi: <b>{c.when(sub.expires_at)}</b> gacha.")
            return await show_sub(tg, callback, uid, session, bot, sub)
        if act == "sl":
            await c.send_access(tg, session, bot, sub.tg_user_id, "🔗 <b>Kirish havolalari</b>")
            return await show_sub(tg, callback, uid, session, bot, sub)
        if act == "sc":
            return await show(tg, callback, uid, f"⛔ {esc(sub.user_name)} obunasi bekor qilinib, kanaldan chiqarilsinmi?",
                              kb([[Btn("✅ Ha", callback_data=f"pa:sc2:{sub.id}"), Btn("✖️ Yo‘q", callback_data=f"pa:s:{sub.id}")]]))
        if act == "sc2":
            await cancel_sub(tg, session, bot, sub)
            try:
                await tg.send_message(chat_id=sub.tg_user_id, text="⛔ Obunangiz bekor qilindi.")
            except TelegramError:
                pass
            return await show_sub(tg, callback, uid, session, bot, sub)
    if act == "gp" and len(arg) > 1 and arg[1].lstrip("-").isdigit():  # manual grant: plan chosen for the typed id
        plan = await session.get(PaidPlan, num)
        if plan is None or plan.bot_id != bot.id:
            return
        target = int(arg[1])
        person = {"id": target, "name": f"ID {target}", "username": None}
        sub = await c.grant(session, bot, plan, person, plan.days)
        await c.send_access(tg, session, bot, target, f"🎁 Sizga obuna berildi: <b>{esc(plan.title)}</b>\n📅 {c.when(sub.expires_at)} gacha")
        return await show_sub(tg, callback, uid, session, bot, sub)
    if act == "pro":
        promo = await session.get(PaidPromo, num)
        if promo is None or promo.bot_id != bot.id:
            return
        if len(arg) > 1 and arg[1] == "t":
            promo.is_active = not promo.is_active
            await session.commit()
        if len(arg) > 1 and arg[1] == "d":
            await session.delete(promo)
            await session.commit()
            return await show_promos(tg, callback, uid, session, bot)
        text = (f"🎟 <b>{esc(promo.code)}</b> — {logic.promo_label(promo)}\nIshlatilgan: {promo.used_count}/{promo.max_uses or '∞'}"
                f"\nHolat: {'faol' if promo.is_active else 'o‘chiq'}")
        return await show(tg, callback, uid, text, kb([[Btn("▶️ Yoqish" if not promo.is_active else "⏸ O‘chirish", callback_data=f"pa:pro:{promo.id}:t"),
                                                       Btn("🗑 O‘chirish", callback_data=f"pa:pro:{promo.id}:d")], back("pa:pr")]))


# ------------------------------------------------------------------ text input

async def on_message(bot, message, session, tg, us) -> bool:
    uid = message["from"]["id"]
    text = (message.get("text") or "").strip()
    data = dict(us.state_data or {})
    c = core()

    async def say(msg):
        await tg.send_message(chat_id=uid, text=msg, parse_mode="HTML")
        return True

    if us.state == "pa_pn":
        step = data.get("step")
        try:
            if step == "title":
                if not text or text.startswith("/") or len(text) > 120:
                    raise ValueError("Nom 1–120 belgi bo‘lsin.")
                await set_state(session, us, "pa_pn", {"step": "days", "title": text})
                return await say("⏱ Necha kunlik obuna? (masalan 30)")
            if step == "days":
                days = logic.parse_int(text, minimum=1, maximum=3650)
                await set_state(session, us, "pa_pn", {**data, "step": "price", "days": days})
                return await say("💰 Narxi (so‘m)? Bepul uchun 0.")
            if step == "price":
                price = logic.parse_int(text, minimum=0)
                plan = PaidPlan(bot_id=bot.id, title=data["title"], days=data["days"], price=price)
                session.add(plan)
                await session.flush()
                for ch in (await session.execute(select(PaidChannel).where(PaidChannel.bot_id == bot.id, PaidChannel.is_active.is_(True)))).scalars().all():
                    session.add(PaidPlanChannel(plan_id=plan.id, channel_id=ch.id))
                await session.commit()
                await set_state(session, us)
                await show_plan(tg, None, uid, session, bot, plan)
                return True
        except ValueError as exc:
            return await say(f"❌ {esc(exc)}")
    if us.state == "pa_pe":
        plan = await session.get(PaidPlan, data.get("plan") or 0)
        field = data.get("field")
        if plan is None or plan.bot_id != bot.id:
            return False
        try:
            if field == "title":
                if not text or len(text) > 120:
                    raise ValueError("Nom 1–120 belgi bo‘lsin.")
                plan.title = text
            elif field == "days":
                plan.days = logic.parse_int(text, minimum=1, maximum=3650)
            elif field == "price":
                plan.price = logic.parse_int(text, minimum=0)
            else:
                plan.description = None if text == "/clear" else text[:1500]
        except ValueError as exc:
            return await say(f"❌ {esc(exc)}")
        await session.commit()
        await set_state(session, us)
        await show_plan(tg, None, uid, session, bot, plan)
        return True
    if us.state == "pa_rj":
        pay = await session.get(PaidPayment, data.get("pay") or 0)
        if pay is None or pay.bot_id != bot.id:
            return False
        await set_state(session, us)
        reason = None if text == "/skip" else text[:500]
        await decide(bot, None, session, tg, uid, pay, False, reason)
        return True
    if us.state == "pa_gr":
        if not text.lstrip("-").isdigit():
            return await say("❌ Telegram ID faqat raqamlardan iborat.")
        await set_state(session, us)
        plans = await c.plans_of(session, bot.id)
        rows = [[Btn(f"{p.title} ({p.days} kun)"[:50], callback_data=f"pa:gp:{p.id}:{int(text)}")] for p in plans] + [back("pa:subs:a:0")]
        await tg.send_message(chat_id=uid, text="📦 Qaysi tarif berilsin?", reply_markup=kb(rows))
        return True
    if us.state == "pa_prn":
        step = data.get("step")
        try:
            if step == "code":
                code = logic.norm_code(text)
                if not logic.valid_code(code):
                    raise ValueError("Kod 3–40 belgi: faqat harf, raqam, - va _.")
                if (await session.execute(select(PaidPromo.id).where(PaidPromo.bot_id == bot.id, PaidPromo.code == code))).first():
                    raise ValueError("Bunday kod allaqachon bor.")
                await set_state(session, us, "pa_prn", {"step": "disc", "code": code})
                return await say("💸 Chegirma: foiz (<code>20%</code>) yoki summa (<code>15000</code>).")
            if step == "disc":
                percent, amount = logic.parse_discount(text)
                await set_state(session, us, "pa_prn", {**data, "step": "max", "percent": percent, "amount": amount})
                return await say("🔢 Necha marta ishlatilsin? Cheklovsiz: /skip")
            if step == "max":
                limit = None if text == "/skip" else logic.parse_int(text, minimum=1, maximum=1_000_000)
                promo = PaidPromo(bot_id=bot.id, code=data["code"], percent=data.get("percent"), amount=data.get("amount"), max_uses=limit)
                session.add(promo)
                await session.commit()
                await set_state(session, us)
                await show_promos(tg, None, uid, session, bot)
                return True
        except ValueError as exc:
            return await say(f"❌ {esc(exc)}")
    if us.state == "pa_se":
        field = data.get("field")
        st = await c.get_settings(session, bot.id)
        if field == "trial_days":
            try:
                st.trial_days = logic.parse_int(text, minimum=1, maximum=365)
            except ValueError as exc:
                return await say(f"❌ {esc(exc)}")
        elif field in SETTING_FIELDS:
            attr, _, limit = SETTING_FIELDS[field]
            if text == "/clear":
                setattr(st, attr, None)
            elif not text or len(text) > limit:
                return await say(f"❌ 1–{limit} belgi bo‘lsin.")
            else:
                setattr(st, attr, text)
        else:
            return False
        await session.commit()
        await set_state(session, us)
        await show_settings(tg, None, uid, session, bot)
        return True
    return False
