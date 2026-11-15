"""Admin side of join-request bots (``/admin`` inside the child bot): channels/groups, modes, questions,
named invite links, pending requests, statistics, texts. Callbacks are ``ja:*``, states ``ja_*``."""
import asyncio

from sqlalchemy import func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.logger import get_logger
from engine import cinema, join_logic as logic
from models.join import (
    MODES, OPEN_STATUSES, ST_APPROVED, ST_DECLINED, ST_EXPIRED, ST_REVIEW, JoinChat, JoinLink, JoinRequest,
)

logger = get_logger("join.admin")
esc = cinema.esc
show = cinema._show
PAGE = 8
TEXT_FIELDS = {
    "welcome": ("welcome_text", "👋 Salomlashish xabari", "Ariza kelganda foydalanuvchiga yuboriladi."),
    "approved": ("approved_text", "✅ Qabul qilingandan keyingi xabar", "Qabul qilinganda yuboriladi (ixtiyoriy)."),
    "declined": ("declined_text", "❌ Rad etilgandan keyingi xabar", "Rad etilganda yuboriladi (ixtiyoriy)."),
}


def kb(rows):
    return Markup(rows)


def back(data="ja:home", text="⬅️ Orqaga"):
    return [Btn(text, callback_data=data)]


def _join():
    from engine import join
    return join


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


async def counts(session, bot_id: int, *, chat_ref=None, link_id=None) -> dict:
    query = select(JoinRequest.status, func.count(JoinRequest.id)).where(JoinRequest.bot_id == bot_id)
    if chat_ref is not None:
        query = query.where(JoinRequest.chat_ref == chat_ref)
    if link_id is not None:
        query = query.where(JoinRequest.link_id == link_id)
    rows = (await session.execute(query.group_by(JoinRequest.status))).all()
    out = {status: n for status, n in rows}
    out["open"] = sum(n for status, n in rows if status in OPEN_STATUSES)
    out["total"] = sum(n for _, n in rows)
    return out


def stat_line(c: dict) -> str:
    return (f"jami {c['total']} · ⏳ {c['open']} · ✅ {c.get(ST_APPROVED, 0)} · ❌ {c.get(ST_DECLINED, 0)}"
            + (f" · ⌛️ {c[ST_EXPIRED]}" if c.get(ST_EXPIRED) else ""))


# ------------------------------------------------------------------ home

async def show_home(tg, callback, chat_id, session, bot):
    c = await counts(session, bot.id)
    chats = (await session.execute(select(func.count(JoinChat.id)).where(JoinChat.bot_id == bot.id))).scalar() or 0
    rows = [[Btn(f"📢 Kanal va guruhlar ({chats})", callback_data="ja:chats")],
            [Btn(f"⏳ Kutilayotganlar ({c['open']})", callback_data="ja:pend:0"), Btn("📊 Statistika", callback_data="ja:stats")],
            [Btn("✍️ Matnlar", callback_data="ja:txt")]]
    text = ("📨 <b>Ariza bot paneli</b>\n\n"
            + ("Botni kanal yoki guruhingizga <b>administrator</b> qiling («Foydalanuvchilarni taklif qilish» huquqi bilan) — "
               "u shu yerda o‘zi paydo bo‘ladi. Keyin «So‘rov bilan qo‘shilish» yoqilgan taklif havolasi yarating."
               if not chats else f"Arizalar: {stat_line(c)}"))
    await show(tg, callback, chat_id, text, kb(rows))


# ------------------------------------------------------------------ chats

async def show_chats(tg, callback, uid, session, bot):
    chats = (await session.execute(select(JoinChat).where(JoinChat.bot_id == bot.id).order_by(JoinChat.id))).scalars().all()
    rows = [[Btn(("" if c.is_active else "⏸ ") + ("📣 " if c.chat_type == "channel" else "👥 ") + c.title[:40], callback_data=f"ja:c:{c.id}")] for c in chats]
    rows.append(back())
    text = "📢 <b>Kanal va guruhlar</b>\n\n" + ("Tanlang:" if chats else "Hali yo‘q. Botni kanal/guruhga administrator qiling.")
    await show(tg, callback, uid, text, kb(rows))


async def own_chat(session, bot, chat_id: int) -> JoinChat | None:
    jc = await session.get(JoinChat, chat_id)
    return jc if jc and jc.bot_id == bot.id else None


async def show_chat(tg, callback, uid, session, bot, jc):
    c = await counts(session, bot.id, chat_ref=jc.id)
    qs = "\n".join(f"  {i}. {esc(q)}" for i, q in enumerate(jc.questions or [], 1)) or "  yo‘q"
    text = (f"{'📣' if jc.chat_type == 'channel' else '👥'} <b>{esc(jc.title)}</b>"
            + ("" if jc.is_active else "  ⏸ <i>to‘xtatilgan</i>")
            + f"\n\nRejim: <b>{logic.MODE_NAMES[jc.mode]}</b>\nKechikish: <b>{logic.delay_label(jc.delay_seconds)}</b>"
              f"\nSavollar:\n{qs}\n\nArizalar: {stat_line(c)}")
    mode_row = [Btn(("✔️ " if jc.mode == m else "") + logic.MODE_NAMES[m].split(" ", 1)[1].split(" +")[0], callback_data=f"ja:m:{jc.id}:{m}") for m in MODES]
    delay_row = [Btn(("✔️ " if jc.delay_seconds == d else "") + logic.delay_label(d), callback_data=f"ja:d:{jc.id}:{d}") for d in logic.DELAYS]
    rows = [mode_row, delay_row,
            [Btn("❓ Savollar", callback_data=f"ja:q:{jc.id}"), Btn("🔗 Havolalar", callback_data=f"ja:links:{jc.id}")],
            [Btn(f"✅ Hammasini qabul ({c['open']})", callback_data=f"ja:allok:{jc.id}"), Btn("❌ Hammasini rad", callback_data=f"ja:allno:{jc.id}")],
            [Btn("▶️ Davom ettirish" if not jc.is_active else "⏸ To‘xtatish", callback_data=f"ja:t:{jc.id}")],
            back("ja:chats")]
    await show(tg, callback, uid, text, kb(rows))


# ------------------------------------------------------------------ pending / requests

async def show_pending(tg, callback, uid, session, bot, page: int):
    base = select(JoinRequest, JoinChat).join(JoinChat, JoinChat.id == JoinRequest.chat_ref).where(
        JoinRequest.bot_id == bot.id, JoinRequest.status.in_(OPEN_STATUSES))
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows_db = (await session.execute(base.order_by(JoinRequest.id).limit(PAGE).offset(page * PAGE))).all()
    rows = [[Btn(f"{'🖐' if r.status == ST_REVIEW else '⏳'} {r.full_name[:24]} · {c.title[:18]}", callback_data=f"ja:r:{r.id}")] for r, c in rows_db]
    nav = []
    if page > 0:
        nav.append(Btn("◀️", callback_data=f"ja:pend:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(Btn("▶️", callback_data=f"ja:pend:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(back())
    await show(tg, callback, uid, f"⏳ <b>Kutilayotgan arizalar</b> ({total})\n\n🖐 — sizning qaroringizni kutmoqda.", kb(rows))


async def show_request(tg, callback, uid, session, bot, r):
    jc = await session.get(JoinChat, r.chat_ref)
    text = _join().review_text(jc, r, await _join().link_name_of(session, r), "Foydalanuvchiga xabar yuborib bo‘lmagan." if r.dm_failed else None)
    text += f"\n\nHolat: <b>{r.status}</b>"
    rows = [[Btn("✅ Qabul qilish", callback_data=f"ja:ok:{r.id}"), Btn("❌ Rad etish", callback_data=f"ja:no:{r.id}")]] if r.status in OPEN_STATUSES else []
    rows.append(back("ja:pend:0"))
    await show(tg, callback, uid, text, kb(rows))


async def decide_one(bot, callback, session, tg, uid, r, approve: bool):
    j = _join()
    jc = await session.get(JoinChat, r.chat_ref)
    try:
        done = await j.decide(tg, session, bot, r, approve=approve, by=uid)
    except TelegramError as exc:
        return await show(tg, callback, uid, f"❌ Telegram xatosi: {esc(exc)}", kb([back("ja:pend:0")]))
    who = esc(((callback.get("from") or {}).get("first_name")) or "admin")
    if done:
        text = j.review_text(jc, r, await j.link_name_of(session, r)) + f"\n\n{'✅ Qabul qilindi' if approve else '❌ Rad etildi'} — {who}"
    else:
        text = "ℹ️ Bu ariza allaqachon ko‘rib chiqilgan yoki foydalanuvchi uni bekor qilgan."
    await show(tg, callback, uid, text, None)


async def bulk(bot, callback, session, tg, uid, jc, approve: bool):
    j = _join()
    reqs = (await session.execute(select(JoinRequest).where(
        JoinRequest.chat_ref == jc.id, JoinRequest.status.in_(OPEN_STATUSES)).order_by(JoinRequest.id))).scalars().all()
    ok = 0
    for r in reqs:
        try:
            ok += bool(await j.decide(tg, session, bot, r, approve=approve, by=uid))
        except TelegramError as exc:
            logger.info("bulk decision failed for %s: %s", r.id, exc)
        if len(reqs) > 20:
            await asyncio.sleep(0.05)
    await show(tg, callback, uid, f"{'✅ Qabul qilindi' if approve else '❌ Rad etildi'}: <b>{ok}</b> / {len(reqs)}",
               kb([back(f"ja:c:{jc.id}")]))


# ------------------------------------------------------------------ links

async def show_links(tg, callback, uid, session, bot, jc):
    links = (await session.execute(select(JoinLink).where(JoinLink.chat_ref == jc.id).order_by(JoinLink.id))).scalars().all()
    lines, rows = [], []
    for link in links:
        c = await counts(session, bot.id, link_id=link.id)
        lines.append(f"{'🚫 ' if link.is_revoked else '🔗 '}<b>{esc(link.name)}</b>: {stat_line(c)}\n<code>{esc(link.url)}</code>")
        if not link.is_revoked:
            rows.append([Btn(f"🚫 «{link.name[:20]}» ni o‘chirish", callback_data=f"ja:lr:{link.id}")])
    rows.insert(0, [Btn("➕ Yangi havola", callback_data=f"ja:ln:{jc.id}")])
    rows.append(back(f"ja:c:{jc.id}"))
    text = f"🔗 <b>{esc(jc.title)} — havolalar</b>\n\n" + ("\n\n".join(lines) if lines else "Hali havola yo‘q. Har manba (Instagram, reklama…) uchun alohida havola yarating — qaysi biri nechta odam keltirishi ko‘rinadi.")
    await show(tg, callback, uid, text, kb(rows))


# ------------------------------------------------------------------ statistics / texts

async def show_stats(tg, callback, uid, session, bot):
    chats = (await session.execute(select(JoinChat).where(JoinChat.bot_id == bot.id).order_by(JoinChat.id))).scalars().all()
    total = await counts(session, bot.id)
    lines = [f"<b>Jami:</b> {stat_line(total)}"]
    for jc in chats:
        lines.append(f"\n📢 <b>{esc(jc.title)}</b>: {stat_line(await counts(session, bot.id, chat_ref=jc.id))}")
    await show(tg, callback, uid, "📊 <b>Statistika</b>\n\n" + "\n".join(lines), kb([back()]))


async def show_texts(tg, callback, uid, session, bot):
    j = _join()
    st = await j.get_settings(session, bot.id)
    rows = [[Btn(label, callback_data=f"ja:tx:{key}")] for key, (_, label, _) in TEXT_FIELDS.items()]
    rows.append(back())
    await show(tg, callback, uid, "✍️ <b>Matnlar</b>\n\nO‘zgaruvchilar: <code>{name}</code> — ism, <code>{chat}</code> — kanal nomi.\n\n"
               f"Salomlashish: {esc(st.welcome_text) if st.welcome_text else '<i>standart</i>'}", kb(rows))


# ------------------------------------------------------------------ routing

async def on_callback(bot, callback, session, tg, us):
    uid = callback["from"]["id"]
    parts = (callback.get("data") or "").split(":")[1:]
    act, arg = (parts[0] if parts else "home"), parts[1:]
    num = int(arg[0]) if arg and arg[0].isdigit() else None
    if us.state and us.state.startswith("ja_"):
        await set_state(session, us)

    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "chats":
        return await show_chats(tg, callback, uid, session, bot)
    if act == "stats":
        return await show_stats(tg, callback, uid, session, bot)
    if act == "txt":
        return await show_texts(tg, callback, uid, session, bot)
    if act == "pend":
        return await show_pending(tg, callback, uid, session, bot, num or 0)
    if act == "tx":
        if arg and arg[0] in TEXT_FIELDS:
            await on_callback_text_field(bot, callback, session, tg, us, arg[0])
        return
    if num is None:
        return
    if act in ("r", "ok", "no"):
        r = await session.get(JoinRequest, num)
        if r is None or r.bot_id != bot.id:
            return
        if act == "r":
            return await show_request(tg, callback, uid, session, bot, r)
        return await decide_one(bot, callback, session, tg, uid, r, act == "ok")
    if act == "lr":
        link = await session.get(JoinLink, num)
        jc = await own_chat(session, bot, link.chat_ref) if link else None
        if jc is None:
            return
        try:
            await tg.revoke_chat_invite_link(chat_id=jc.chat_id, invite_link=link.url)
        except TelegramError as exc:
            logger.info("revoke failed: %s", exc)
        link.is_revoked = True
        await session.commit()
        return await show_links(tg, callback, uid, session, bot, jc)
    jc = await own_chat(session, bot, num)
    if jc is None:
        return
    if act == "c":
        return await show_chat(tg, callback, uid, session, bot, jc)
    if act == "m" and len(arg) > 1 and arg[1] in MODES:
        jc.mode = arg[1]
        await session.commit()
        return await show_chat(tg, callback, uid, session, bot, jc)
    if act == "d" and len(arg) > 1 and arg[1].isdigit() and int(arg[1]) in logic.DELAYS:
        jc.delay_seconds = int(arg[1])
        await session.commit()
        return await show_chat(tg, callback, uid, session, bot, jc)
    if act == "t":
        jc.is_active = not jc.is_active
        await session.commit()
        return await show_chat(tg, callback, uid, session, bot, jc)
    if act == "q":
        await set_state(session, us, "ja_q", {"chat": jc.id})
        return await show(tg, callback, uid, "❓ <b>Savollar</b>\n\nHar qatorga bitta savol yozing (ko‘pi bilan 3 ta). "
                          "O‘chirish uchun <code>/clear</code>.", kb([back(f"ja:c:{jc.id}", "✖️ Bekor qilish")]))
    if act == "links":
        return await show_links(tg, callback, uid, session, bot, jc)
    if act == "ln":
        await set_state(session, us, "ja_ln", {"chat": jc.id})
        return await show(tg, callback, uid, "🔗 Havola nomini yozing (masalan: <i>Instagram</i>).",
                          kb([back(f"ja:links:{jc.id}", "✖️ Bekor qilish")]))
    if act in ("allok", "allno"):
        c = await counts(session, bot.id, chat_ref=jc.id)
        return await show(tg, callback, uid, f"{'Qabul qilinsinmi' if act == 'allok' else 'Rad etilsinmi'}: <b>{c['open']}</b> ta ariza?",
                          kb([[Btn("✅ Ha", callback_data=f"ja:{act}2:{jc.id}"), Btn("✖️ Yo‘q", callback_data=f"ja:c:{jc.id}")]]))
    if act in ("allok2", "allno2"):
        return await bulk(bot, callback, session, tg, uid, jc, act == "allok2")


async def on_callback_text_field(bot, callback, session, tg, us, key):
    uid = callback["from"]["id"]
    field, label, hint = TEXT_FIELDS[key]
    await set_state(session, us, "ja_tx", {"field": field})
    await show(tg, callback, uid, f"{label}\n\n{hint}\nYangi matnni yozing. Standartga qaytarish: <code>/clear</code>. "
               "O‘zgaruvchilar: <code>{name}</code>, <code>{chat}</code>.", kb([back("ja:txt", "✖️ Bekor qilish")]))


async def on_message(bot, message, session, tg, us) -> bool:
    uid = message["from"]["id"]
    text = (message.get("text") or "").strip()
    data = us.state_data or {}
    if us.state == "ja_q":
        jc = await own_chat(session, bot, data.get("chat") or 0)
        if jc is None:
            return False
        try:
            jc.questions = [] if text == "/clear" else logic.parse_questions(text)
        except ValueError as exc:
            await tg.send_message(chat_id=uid, text=f"❌ {exc}")
            return True
        await session.commit()
        await set_state(session, us)
        await show_chat(tg, None, uid, session, bot, jc)
        return True
    if us.state == "ja_ln":
        jc = await own_chat(session, bot, data.get("chat") or 0)
        if jc is None:
            return False
        if not text or text.startswith("/") or len(text) > 64:
            await tg.send_message(chat_id=uid, text="❌ Nom 1–64 belgi bo‘lsin.")
            return True
        try:
            created = await tg.create_chat_invite_link(chat_id=jc.chat_id, name=text, creates_join_request=True)
        except TelegramError as exc:
            await set_state(session, us)
            await tg.send_message(chat_id=uid, text=f"❌ Havola yaratib bo‘lmadi: {exc}\nBot administrator va «Foydalanuvchilarni taklif qilish» huquqiga ega ekanini tekshiring.")
            return True
        session.add(JoinLink(bot_id=bot.id, chat_ref=jc.id, name=text, url=created.invite_link))
        await session.commit()
        await set_state(session, us)
        await show_links(tg, None, uid, session, bot, jc)
        return True
    if us.state == "ja_tx":
        field = data.get("field")
        if field not in {f for f, _, _ in TEXT_FIELDS.values()}:
            return False
        st = await _join().get_settings(session, bot.id)
        if text == "/clear":
            setattr(st, field, None)
        elif not text or len(text) > 3000:
            await tg.send_message(chat_id=uid, text="❌ Matn 1–3000 belgi bo‘lsin.")
            return True
        else:
            setattr(st, field, text)
        await session.commit()
        await set_state(session, us)
        await show_texts(tg, None, uid, session, bot)
        return True
    return False
