"""Join-request bots: approve or decline ``chat_join_request`` updates of channels/groups.

Per channel/group the admin picks a mode (``models.join``): auto (optionally after a delay), manual
(admins press ✅/❌) or captcha (a button the applicant must press, then auto). Up to 3 questions can be
asked first. Telegram lets the bot write to the applicant only while the request is open, so every
direct message is best-effort: when it fails the request goes to the admins to decide by hand.

Admin side: ``engine/join_admin.py`` (``ja:`` callbacks, ``ja_*`` states). Applicant side: ``jn:``
callbacks and the ``jn_q`` state (answering a question).
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select, update
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, TelegramError

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import cinema, join_admin, join_logic as logic
from engine.audience import touch_user
from engine.booking_time import utcnow
from engine.telegram_client import get_client
from models.bots import Bot
from models.join import (
    MODE_CAPTCHA, MODE_MANUAL, OPEN_STATUSES, ST_APPROVED, ST_CAPTCHA, ST_DECLINED, ST_EXPIRED, ST_PENDING,
    ST_QUESTIONS, ST_REVIEW, ST_SCHEDULED, JoinChat, JoinLink, JoinRequest, JoinSettings,
)
from models.user_sessions import UserSession

logger = get_logger("join")
esc = cinema.esc
show = cinema._show

WELCOME = ("📨 <b>Ariza qabul qiluvchi bot</b>\n\nBu bot kanal yoki guruhga qo‘shilish arizalarini ko‘rib chiqadi. "
           "Arizangizni yuborgan bo‘lsangiz, natijani shu yerda kutib turing.")
DEFAULT_WELCOME = "👋 Salom, {name}! «{chat}» ga qo‘shilish arizangiz qabul qilindi."
EXPIRE_MINUTES = 60  # captcha/questions left unanswered this long: the request is declined
INTERVAL = 15
GONE = ("hide_requester_missing", "user_already_participant", "request_not_found", "chat_join_request")


# ------------------------------------------------------------------ basics

async def get_settings(session, bot_id: int) -> JoinSettings:
    st = (await session.execute(select(JoinSettings).where(JoinSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = JoinSettings(bot_id=bot_id)
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> JoinSettings:
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


def full_name(user: dict) -> str:
    return " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or user.get("username") or "Foydalanuvchi"


async def get_chat(session, bot_id: int, chat_id: int) -> JoinChat | None:
    return (await session.execute(select(JoinChat).where(JoinChat.bot_id == bot_id, JoinChat.chat_id == chat_id))).scalar_one_or_none()


async def register_chat(session, bot, chat: dict) -> tuple[JoinChat, bool]:
    """Remember a channel/group the bot administers. Returns (row, created)."""
    title = (chat.get("title") or chat.get("username") or str(chat["id"]))[:255]
    kind = "channel" if chat.get("type") == "channel" else "group"
    jc = await get_chat(session, bot.id, chat["id"])
    created = jc is None
    if created:
        jc = JoinChat(bot_id=bot.id, chat_id=chat["id"], title=title, chat_type=kind, questions=[])
        session.add(jc)
    else:
        jc.title, jc.chat_type = title, kind
    await session.commit()
    return jc, created


# ------------------------------------------------------------------ sending

async def dm(tg, r: JoinRequest, text: str, markup=None) -> bool:
    """Write to the applicant (only possible while the request is open). Never raises."""
    chat_id = r.user_chat_id or r.tg_user_id
    try:
        await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)
        return True
    except TelegramError as exc:
        logger.info("join: applicant %s not reachable: %s", r.tg_user_id, exc)
        return False


def review_text(jc: JoinChat, r: JoinRequest, link_name: str | None, note: str | None = None) -> str:
    who = f"<b>{esc(r.full_name)}</b>" + (f" (@{esc(r.username)})" if r.username else "") + f"  <code>{r.tg_user_id}</code>"
    text = f"📨 <b>Yangi ariza</b>\n📢 {esc(jc.title)}\n👤 {who}"
    if link_name:
        text += f"\n🔗 Havola: {esc(link_name)}"
    if r.answers:
        text += "\n\n" + esc(logic.format_answers(jc.questions, r.answers))
    if note:
        text += f"\n\n⚠️ {esc(note)}"
    return text


def review_markup(r: JoinRequest) -> Markup:
    return Markup([[Btn("✅ Qabul qilish", callback_data=f"ja:ok:{r.id}"), Btn("❌ Rad etish", callback_data=f"ja:no:{r.id}")]])


async def link_name_of(session, r: JoinRequest) -> str | None:
    if r.link_id is None:
        return None
    link = await session.get(JoinLink, r.link_id)
    return link.name if link else None


async def notify_review(tg, session, bot, jc, r, note=None):
    text = review_text(jc, r, await link_name_of(session, r), note)
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await tg.send_message(chat_id=admin_id, text=text[:4096], parse_mode="HTML", reply_markup=review_markup(r))
        except TelegramError as exc:
            logger.info("join: review notice to %s failed: %s", admin_id, exc)


# ------------------------------------------------------------------ decisions

async def decide(tg, session, bot, r: JoinRequest, *, approve: bool, by: int | None = None, final: str | None = None) -> bool:
    """Approve/decline one open request exactly once. Returns False when it was already decided."""
    final = final or (ST_APPROVED if approve else ST_DECLINED)
    previous = r.status
    claimed = await session.execute(
        update(JoinRequest).where(JoinRequest.id == r.id, JoinRequest.status.in_(OPEN_STATUSES))
        .values(status=final, decided_at=utcnow(), decided_by=by))
    await session.commit()
    if claimed.rowcount == 0:
        await session.refresh(r)
        return False
    jc = await session.get(JoinChat, r.chat_ref)
    try:
        call = tg.approve_chat_join_request if approve else tg.decline_chat_join_request
        await call(chat_id=jc.chat_id, user_id=r.tg_user_id)
    except BadRequest as exc:
        if any(word in str(exc).lower() for word in GONE):  # the applicant cancelled or already joined
            await session.execute(update(JoinRequest).where(JoinRequest.id == r.id).values(status=ST_EXPIRED))
            await session.commit()
            await session.refresh(r)
            return False
        await _revert(session, r, previous)
        raise
    except TelegramError:
        await _revert(session, r, previous)
        raise
    await session.refresh(r)
    st = await get_settings(session, bot.id)
    template = st.approved_text if approve else st.declined_text
    if template:
        await dm(tg, r, esc(logic.render(template, r.full_name, jc.title)))
    return True


async def _revert(session, r, previous):
    await session.execute(update(JoinRequest).where(JoinRequest.id == r.id).values(status=previous, decided_at=None, decided_by=None))
    await session.commit()
    await session.refresh(r)


# ------------------------------------------------------------------ the request flow

async def on_request(bot, req: dict, session, tg):
    chat, user = req["chat"], req["from"]
    jc = await get_chat(session, bot.id, chat["id"])
    if jc is None:
        jc, _ = await register_chat(session, bot, chat)
    if not jc.is_active:
        return  # paused: the requests stay open for the admins to decide in Telegram itself
    url = (req.get("invite_link") or {}).get("invite_link")
    link = (await session.execute(select(JoinLink).where(JoinLink.bot_id == bot.id, JoinLink.url == url))).scalars().first() if url else None
    r = (await session.execute(select(JoinRequest).where(
        JoinRequest.chat_ref == jc.id, JoinRequest.tg_user_id == user["id"], JoinRequest.status.in_(OPEN_STATUSES)))).scalars().first()
    if r is None:
        r = JoinRequest(bot_id=bot.id, chat_ref=jc.id, tg_user_id=user["id"], created_at=utcnow())
        session.add(r)
    r.user_chat_id = req.get("user_chat_id")
    r.username, r.full_name = user.get("username"), full_name(user)[:255]
    r.link_id = link.id if link else None
    r.status, r.step, r.answers, r.dm_failed, r.due_at, r.created_at = ST_PENDING, 0, [], False, None, utcnow()
    await session.commit()
    await begin(bot, jc, r, session, tg)


async def begin(bot, jc, r, session, tg):
    st = await get_settings(session, bot.id)
    welcome = esc(logic.render(st.welcome_text or DEFAULT_WELCOME, r.full_name, jc.title))
    if jc.mode == MODE_CAPTCHA:
        r.status = ST_CAPTCHA
        await session.commit()
        markup = Markup([[Btn("✅ Men bot emasman", callback_data=f"jn:c:{r.id}")]])
        if not await dm(tg, r, welcome, markup):
            return await _needs_admin(tg, session, bot, jc, r, "Foydalanuvchiga captcha yuborib bo‘lmadi.")
        return
    await dm(tg, r, welcome)
    await proceed(bot, jc, r, session, tg)


async def _needs_admin(tg, session, bot, jc, r, note):
    r.dm_failed, r.status = True, ST_REVIEW
    await session.commit()
    await notify_review(tg, session, bot, jc, r, note)


async def proceed(bot, jc, r, session, tg):
    """Checks (captcha) passed: ask the next question, or finish."""
    if r.step < len(jc.questions or []):
        r.status = ST_QUESTIONS
        await session.commit()
        us = await session_of(session, bot, r.tg_user_id)
        await set_state(session, us, "jn_q", {"req": r.id})
        sent = await dm(tg, r, f"❓ <b>Savol {r.step + 1}/{len(jc.questions)}</b>\n\n{esc(jc.questions[r.step])}")
        if not sent:
            await set_state(session, us)
            await _needs_admin(tg, session, bot, jc, r, "Foydalanuvchiga savol yuborib bo‘lmadi.")
        return
    await complete(bot, jc, r, session, tg)


async def complete(bot, jc, r, session, tg):
    if jc.mode == MODE_MANUAL:
        r.status = ST_REVIEW
        await session.commit()
        return await notify_review(tg, session, bot, jc, r)
    if jc.delay_seconds > 0:
        r.status, r.due_at = ST_SCHEDULED, utcnow() + timedelta(seconds=jc.delay_seconds)
        await session.commit()
        return
    r.status = ST_SCHEDULED  # decide() accepts every open status; this keeps the row open until then
    await session.commit()
    try:
        await decide(tg, session, bot, r, approve=True)
    except TelegramError as exc:
        logger.warning("join: auto-approve failed for request %s: %s", r.id, exc)
        await _needs_admin(tg, session, bot, jc, r, f"Avto-qabul bo‘lmadi: {exc}")


async def on_answer(bot, message, session, tg, us) -> bool:
    """A text message while answering questions. Returns True when it was consumed."""
    data = us.state_data or {}
    r = await session.get(JoinRequest, data.get("req") or 0)
    if r is None or r.tg_user_id != message["from"]["id"] or r.status != ST_QUESTIONS:
        await set_state(session, us)
        return False
    text = (message.get("text") or "").strip()
    if not text:
        await tg.send_message(chat_id=r.tg_user_id, text="Iltimos, javobni matn bilan yozing.")
        return True
    jc = await session.get(JoinChat, r.chat_ref)
    r.answers = [*r.answers, text[:500]]
    r.step += 1
    await session.commit()
    await set_state(session, us)
    await proceed(bot, jc, r, session, tg)
    return True


async def on_captcha(bot, callback, session, tg, request_id: int):
    uid = callback["from"]["id"]
    r = await session.get(JoinRequest, request_id)
    if r is None or r.tg_user_id != uid or r.status != ST_CAPTCHA:
        return
    jc = await session.get(JoinChat, r.chat_ref)
    await show(tg, callback, uid, "✅ Tasdiqlandi.", None)
    await proceed(bot, jc, r, session, tg)


# ------------------------------------------------------------------ membership of the bot in chats

async def on_membership(bot, event: dict, session, tg):
    """The bot was made administrator of (or removed from) a channel/group."""
    chat = event.get("chat") or {}
    if chat.get("type") not in ("channel", "group", "supergroup"):
        return
    status = (event.get("new_chat_member") or {}).get("status")
    if status == "administrator":
        jc, created = await register_chat(session, bot, chat)
        if created:
            markup = Markup([[Btn("⚙️ Sozlash", callback_data=f"ja:c:{jc.id}")]])
            for admin_id in await cinema.admin_ids(session, bot):
                try:
                    await tg.send_message(chat_id=admin_id, text=f"✅ <b>{esc(jc.title)}</b> ulandi. Rejim: {logic.MODE_NAMES[jc.mode]}.",
                                          parse_mode="HTML", reply_markup=markup)
                except TelegramError:
                    pass
    elif status in ("left", "kicked"):
        jc = await get_chat(session, bot.id, chat["id"])
        if jc:
            jc.is_active = False
            await session.commit()


# ------------------------------------------------------------------ entry point

async def handle(bot, update_, session, tg):
    if update_.get("chat_join_request"):
        await on_request(bot, update_["chat_join_request"], session, tg)
    elif update_.get("callback_query"):
        await _on_callback(bot, update_["callback_query"], session, tg)
    elif update_.get("message"):
        await _on_message(bot, update_["message"], session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    uid = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    if data.startswith("ja:"):
        if await cinema.is_admin(session, bot, uid):
            await join_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    parts = data.split(":")
    if parts[0] == "jn" and len(parts) == 3 and parts[1] == "c" and parts[2].isdigit():
        await on_captcha(bot, callback, session, tg, int(parts[2]))


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
        if us.state and us.state.startswith("ja_") and admin and cmd == "/cancel":
            await tg.send_message(chat_id=uid, text="Bekor qilindi.")
        await set_state(session, us)
        extra = "\n\n⚙️ Sozlash uchun /admin yozing." if admin else ""
        return await tg.send_message(chat_id=uid, text=WELCOME + extra, parse_mode="HTML")
    if admin and cmd == "/admin":
        await set_state(session, us)
        return await join_admin.show_home(tg, None, uid, session, bot)
    if us.state == "jn_q":
        if await on_answer(bot, message, session, tg, us):
            return
    if us.state and us.state.startswith("ja_") and admin:
        await join_admin.on_message(bot, message, session, tg, us)


# ------------------------------------------------------------------ background

async def _default_client(bot):
    return await get_client(bot.plain_token)


async def run_once(session, *, now=None, client_for=_default_client) -> int:
    """Approve the delayed requests that are due; decline captcha/questions left unanswered. Returns how many."""
    now = now or utcnow()
    done = 0
    due = (await session.execute(
        select(JoinRequest, Bot).join(Bot, Bot.id == JoinRequest.bot_id)
        .where(JoinRequest.status == ST_SCHEDULED, JoinRequest.due_at <= now, Bot.is_active.is_(True), Bot.kind == "join")
        .order_by(JoinRequest.id).limit(100))).all()
    stale = (await session.execute(
        select(JoinRequest, Bot).join(Bot, Bot.id == JoinRequest.bot_id)
        .where(JoinRequest.status.in_((ST_CAPTCHA, ST_QUESTIONS)), JoinRequest.created_at <= now - timedelta(minutes=EXPIRE_MINUTES),
               Bot.is_active.is_(True), Bot.kind == "join")
        .order_by(JoinRequest.id).limit(100))).all()
    for approve, rows in ((True, due), (False, stale)):
        for r, bot in rows:
            try:
                tg = await client_for(bot)
                if await decide(tg, session, bot, r, approve=approve, final=None if approve else ST_EXPIRED):
                    done += 1
            except Exception:
                logger.exception("join: scheduled decision failed for request %s", r.id)
                await session.rollback()
    return done


async def loop(interval: int = INTERVAL, session_factory=AsyncSessionLocal) -> None:
    logger.info("Join request loop started")
    while True:
        try:
            async with session_factory() as session:
                await run_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Join request tick failed")
        await asyncio.sleep(interval)
