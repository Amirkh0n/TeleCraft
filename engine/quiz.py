"""Quiz bots: anyone can create tests (TXT file, pasted text or a Telegram quiz poll), anyone can
take them as timed Telegram polls, and the bot keeps results and leaderboards.

Play engine: one attempt = one user taking one test. Each question is a non-anonymous poll with
``open_period`` = the test's time per question. The poll row is stored in the database, so an
answer (``poll_answer`` update) or a timeout is handled correctly even after a restart.
"""
import asyncio
import random
import weakref
from datetime import timedelta

from sqlalchemy import func, or_, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import cinema, quiz_admin, quiz_create, subscription
from engine.audience import touch_user
from engine.booking_time import as_utc, utcnow
from engine.quiz_parse import poll_explanation, poll_view
from engine.telegram_client import get_client
from models.bots import Bot
from models.quiz import (
    ATTEMPT_ABANDONED, ATTEMPT_ACTIVE, ATTEMPT_FINISHED, QuizAttempt, QuizPoll, QuizQuestion, QuizSettings, QuizTest,
)
from models.user_sessions import UserSession

logger = get_logger("quiz")
esc = cinema.esc
show = cinema._show

WELCOME = ("🧠 <b>Test botiga xush kelibsiz!</b>\n\nTayyor testlarni ishlang, natijangizni reyting bilan solishtiring "
           "yoki o‘zingiz test yarating — hatto bitta txt fayldan.")
PAGE = 8
LETTER_HINT = "\n\n<i>Variantlar yuqoridagi xabarda.</i>"
MAX_MISSED_IN_A_ROW = 2

_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()
_tasks: set = set()


def attempt_lock(attempt_id: int) -> asyncio.Lock:
    lock = _locks.get(attempt_id)
    if lock is None:
        lock = _locks[attempt_id] = asyncio.Lock()
    return lock


# ------------------------------------------------------------------ settings & sessions

async def get_settings(session, bot_id: int) -> QuizSettings:
    st = (await session.execute(select(QuizSettings).where(QuizSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = QuizSettings(bot_id=bot_id)
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> QuizSettings:
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


async def can_create(session, bot, user_id: int) -> bool:
    st = await get_settings(session, bot.id)
    return st.who_can_create == "everyone" or await cinema.is_admin(session, bot, user_id)


def deep_link(bot, test) -> str:
    return f"https://t.me/{bot.username}?start=t{test.id}" if bot.username else ""


def display_name(user: dict) -> str:
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return (name or user.get("username") or "Foydalanuvchi")[:120]


def fmt_seconds(sec: int) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m} daq {s} s" if m else f"{s} s"


def fmt_limit(sec: int) -> str:
    return f"{sec // 60} daq" if sec % 60 == 0 and sec >= 60 else f"{sec} s"


# ------------------------------------------------------------------ leaderboard

async def leaderboard(session, test_id: int, limit: int | None = 10):
    """Best finished attempt per user, ordered by score then speed."""
    rows = (await session.execute(
        select(QuizAttempt.tg_user_id, QuizAttempt.user_name, QuizAttempt.score, QuizAttempt.total, QuizAttempt.time_spent_sec)
        .where(QuizAttempt.test_id == test_id, QuizAttempt.status == ATTEMPT_FINISHED)
        .order_by(QuizAttempt.score.desc(), QuizAttempt.time_spent_sec.asc(), QuizAttempt.id).limit(5000)
    )).all()
    best, seen = [], set()
    for row in rows:
        if row.tg_user_id not in seen:
            seen.add(row.tg_user_id)
            best.append(row)
    return best[:limit] if limit else best


async def show_leaderboard(tg, callback, chat_id, session, bot, test):
    board = await leaderboard(session, test.id, 10)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>{esc(test.title)}</b> — reyting", ""]
    if not board:
        lines.append("Hali hech kim yakunlamagan. Birinchi bo‘ling!")
    for i, r in enumerate(board):
        lines.append(f"{medals[i] if i < 3 else f'{i + 1}.'} {esc(r.user_name)} — <b>{r.score}/{r.total}</b> · {fmt_seconds(r.time_spent_sec)}")
    await show(tg, callback, chat_id, "\n".join(lines),
               Markup([[Btn("▶️ Boshlash", callback_data=f"qz:go:{test.id}")], [Btn("⬅️ Test", callback_data=f"qz:t:{test.id}")]]))


# ------------------------------------------------------------------ play engine

async def questions_of(session, test_id: int):
    return list((await session.execute(
        select(QuizQuestion).where(QuizQuestion.test_id == test_id).order_by(QuizQuestion.position, QuizQuestion.id)
    )).scalars().all())


async def start_attempt(session, tg, bot, test, user: dict):
    questions = await questions_of(session, test.id)
    if not questions:
        return None
    ids = [q.id for q in questions]
    if test.pick_count and 0 < test.pick_count < len(ids):
        ids = random.sample(ids, test.pick_count) if test.shuffle_questions else ids[:test.pick_count]
    if test.shuffle_questions:
        random.shuffle(ids)
    for old in (await session.execute(select(QuizAttempt).where(
            QuizAttempt.bot_id == bot.id, QuizAttempt.tg_user_id == user["id"], QuizAttempt.status == ATTEMPT_ACTIVE))).scalars().all():
        old.status = ATTEMPT_ABANDONED  # one running test per user: the old one's pending polls become no-ops
    attempt = QuizAttempt(bot_id=bot.id, test_id=test.id, tg_user_id=user["id"], user_name=display_name(user),
                          order=ids, total=len(ids), answers=[])
    test.plays += 1
    session.add(attempt)
    await session.commit()
    await tg.send_message(
        chat_id=user["id"], parse_mode="HTML",
        text=(f"🚀 <b>{esc(test.title)}</b>\n\n❓ {attempt.total} ta savol · ⏱ har biriga {fmt_limit(test.time_limit_sec)}\n"
              "Vaqt tugasa savol o‘tkazib yuboriladi. To‘xtatish: /stop"),
    )
    await send_question(session, tg, bot, test, attempt)
    return attempt


async def send_question(session, tg, bot, test, attempt):
    """Send the attempt's current question as a poll (skipping questions that no longer exist)."""
    while attempt.current < attempt.total:
        q = await session.get(QuizQuestion, attempt.order[attempt.current])
        if q is not None:
            break
        attempt.answers = attempt.answers + [{"q": attempt.order[attempt.current], "ok": None, "sel": []}]
        attempt.current += 1
    else:
        await finish_attempt(session, tg, bot, test, attempt)
        return
    order = list(range(len(q.options)))
    if test.shuffle_options:
        random.shuffle(order)
    options = [q.options[i] for i in order]
    correct_shown = [order.index(c) for c in q.correct]
    is_quiz = len(correct_shown) == 1
    prefix = f"{attempt.current + 1}/{attempt.total}. "
    pre, question, poll_options = poll_view(prefix + q.text, options)
    if pre:
        await tg.send_message(chat_id=attempt.tg_user_id, text=pre, parse_mode="HTML")
    limit = max(5, min(600, test.time_limit_sec))
    kwargs = dict(chat_id=attempt.tg_user_id, question=question, options=poll_options, is_anonymous=False, open_period=limit)
    if is_quiz:
        kwargs.update(type="quiz", correct_option_id=correct_shown[0])
        if poll_explanation(q.explanation):
            kwargs["explanation"] = poll_explanation(q.explanation)
    else:
        kwargs.update(type="regular", allows_multiple_answers=True)
    msg = await tg.send_poll(**kwargs)
    session.add(QuizPoll(poll_id=msg.poll.id, attempt_id=attempt.id, question_id=q.id, chat_id=attempt.tg_user_id,
                         message_id=msg.message_id, option_order=order, is_quiz=is_quiz,
                         deadline=utcnow() + timedelta(seconds=limit)))
    await session.commit()
    schedule_expiry(msg.poll.id, limit + 2)


async def advance(session, tg, bot, test, attempt):
    if attempt.current >= attempt.total:
        await finish_attempt(session, tg, bot, test, attempt)
    else:
        await send_question(session, tg, bot, test, attempt)


async def on_poll_answer(bot, answer: dict, session, tg):
    option_ids = answer.get("option_ids") or []
    user = answer.get("user") or {}
    if not option_ids:
        return  # the vote was retracted
    poll = await session.get(QuizPoll, str(answer.get("poll_id")))
    if poll is None or poll.answered:
        return
    attempt = await session.get(QuizAttempt, poll.attempt_id)
    if attempt is None or attempt.tg_user_id != user.get("id") or attempt.bot_id != bot.id:
        return
    async with attempt_lock(attempt.id):
        await session.refresh(poll)
        await session.refresh(attempt)
        if poll.answered or attempt.status != ATTEMPT_ACTIVE:
            return
        question = await session.get(QuizQuestion, poll.question_id)
        chosen = sorted({poll.option_order[i] for i in option_ids if 0 <= i < len(poll.option_order)})
        ok = bool(question) and chosen == sorted(question.correct)
        poll.answered = True
        attempt.answers = attempt.answers + [{"q": poll.question_id, "ok": ok, "sel": chosen}]
        attempt.score += 1 if ok else 0
        attempt.current += 1
        attempt.missed_streak = 0
        await session.commit()
        test = await session.get(QuizTest, attempt.test_id)
        if not poll.is_quiz and question:  # multi-answer polls give no native feedback
            if ok:
                note = "✅ To‘g‘ri!"
            else:
                right = ", ".join(esc(question.options[i]) for i in question.correct)
                note = f"❌ Noto‘g‘ri. To‘g‘ri javob: <b>{right}</b>"
            if question.explanation:
                note += f"\n💡 {esc(question.explanation)}"
            await tg.send_message(chat_id=attempt.tg_user_id, text=note, parse_mode="HTML")
            try:
                await tg.stop_poll(chat_id=poll.chat_id, message_id=poll.message_id)
            except TelegramError:
                pass
        await advance(session, tg, bot, test, attempt)


def schedule_expiry(poll_id: str, delay: float):
    task = asyncio.create_task(expire_poll(poll_id, delay=delay))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _default_client(bot):
    return await get_client(bot.plain_token)


async def expire_poll(poll_id: str, *, delay: float = 0, session_factory=AsyncSessionLocal,
                      client_for=_default_client, sleep=asyncio.sleep):
    """The time for a question is over: count it as missed and move on (or pause the test)."""
    try:
        if delay:
            await sleep(delay)
        async with session_factory() as session:
            poll = await session.get(QuizPoll, poll_id)
            if poll is None or poll.answered:
                return
            attempt = await session.get(QuizAttempt, poll.attempt_id)
            if attempt is None:
                return
            async with attempt_lock(attempt.id):
                await session.refresh(poll)
                await session.refresh(attempt)
                if poll.answered:
                    return
                poll.answered = True
                if attempt.status != ATTEMPT_ACTIVE:
                    await session.commit()
                    return
                attempt.answers = attempt.answers + [{"q": poll.question_id, "ok": None, "sel": []}]
                attempt.current += 1
                attempt.missed_streak += 1
                bot = await session.get(Bot, attempt.bot_id)
                test = await session.get(QuizTest, attempt.test_id)
                tg = await client_for(bot)
                if attempt.missed_streak >= MAX_MISSED_IN_A_ROW and attempt.current < attempt.total:
                    attempt.status = ATTEMPT_ABANDONED
                    await session.commit()
                    await tg.send_message(
                        chat_id=attempt.tg_user_id, parse_mode="HTML",
                        text=(f"⏸ <b>{esc(test.title)}</b> to‘xtatildi: ketma-ket {MAX_MISSED_IN_A_ROW} ta savolga javob bermadingiz.\n"
                              f"Hozircha {attempt.score} ta to‘g‘ri javob."),
                        reply_markup=Markup([[Btn("▶️ Davom ettirish", callback_data=f"qz:resume:{attempt.id}")],
                                             [Btn("🏠 Bosh sahifa", callback_data="qz:home")]]))
                    return
                await session.commit()
                await advance(session, tg, bot, test, attempt)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("quiz: expiry of poll %s failed", poll_id)


async def resume_pending(*, session_factory=AsyncSessionLocal) -> int:
    """After a restart: re-arm the timers of polls that are still open."""
    async with session_factory() as session:
        rows = (await session.execute(
            select(QuizPoll.poll_id, QuizPoll.deadline).join(QuizAttempt, QuizAttempt.id == QuizPoll.attempt_id)
            .where(QuizPoll.answered.is_(False), QuizAttempt.status == ATTEMPT_ACTIVE)
        )).all()
    now = utcnow()
    for poll_id, deadline in rows:
        schedule_expiry(poll_id, max(0.0, (as_utc(deadline) - now).total_seconds()) + 2)
    return len(rows)


# ------------------------------------------------------------------ results

def grade(percent: int) -> str:
    if percent >= 90:
        return "🏆 A’lo!"
    if percent >= 70:
        return "👍 Yaxshi"
    if percent >= 50:
        return "🙂 Qoniqarli"
    return "💪 Yana urinib ko‘ring"


async def finish_attempt(session, tg, bot, test, attempt):
    attempt.status = ATTEMPT_FINISHED
    attempt.finished_at = utcnow()
    attempt.time_spent_sec = int((attempt.finished_at - as_utc(attempt.started_at)).total_seconds())
    await session.commit()
    board = await leaderboard(session, test.id, None)
    rank = next((i + 1 for i, r in enumerate(board) if r.tg_user_id == attempt.tg_user_id), None)
    percent = round(100 * attempt.score / attempt.total) if attempt.total else 0
    wrong = sum(1 for a in attempt.answers if a["ok"] is False)
    missed = sum(1 for a in attempt.answers if a["ok"] is None)
    lines = [f"🏁 <b>{esc(test.title)}</b> yakunlandi", "",
             f"✅ To‘g‘ri: <b>{attempt.score}/{attempt.total}</b> ({percent}%)",
             f"❌ Xato: {wrong}   ⏭ O‘tkazib yuborilgan: {missed}",
             f"⏱ Vaqt: {fmt_seconds(attempt.time_spent_sec)}",
             f"🏅 Reytingda: <b>{rank}-o‘rin</b> ({len(board)} ishtirokchidan)" if rank else "", "", grade(percent)]
    rows = []
    if wrong + missed:
        rows.append([Btn(f"🔍 Xatolarni ko‘rish ({wrong + missed})", callback_data=f"qz:rev:{attempt.id}")])
    rows.append([Btn("🔁 Qayta ishlash", callback_data=f"qz:go:{test.id}"), Btn("🏆 Reyting", callback_data=f"qz:top:{test.id}")])
    link = deep_link(bot, test)
    if link:
        text = f"{test.title}: men {attempt.score}/{attempt.total} natija ko‘rsatdim. Siz ham sinab ko‘ring!"
        rows.append([Btn("📤 Do‘stlarga ulashish", url=f"https://t.me/share/url?url={link}&text={_quote(text)}")])
    rows.append([Btn("🏠 Bosh sahifa", callback_data="qz:home")])
    await tg.send_message(chat_id=attempt.tg_user_id, text="\n".join(x for x in lines if x is not None),
                          parse_mode="HTML", reply_markup=Markup(rows))


def _quote(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")


async def show_review(tg, chat_id, session, attempt):
    wrong = [a for a in attempt.answers if a["ok"] is not True]
    if not wrong:
        await tg.send_message(chat_id=chat_id, text="🎉 Xato yo‘q!")
        return
    chunks, current = [], "🔍 <b>Xatolar tahlili</b>\n"
    for a in wrong[:30]:
        q = await session.get(QuizQuestion, a["q"])
        if q is None:
            continue
        right = ", ".join(esc(q.options[i]) for i in q.correct)
        mine = ", ".join(esc(q.options[i]) for i in a["sel"] if i < len(q.options)) or "<i>javob berilmagan</i>"
        block = f"\n❓ {esc(q.text[:400])}\n❌ Sizniki: {mine}\n✅ To‘g‘ri: <b>{right}</b>\n"
        if q.explanation:
            block += f"💡 {esc(q.explanation[:300])}\n"
        if len(current) + len(block) > 3800:
            chunks.append(current)
            current = ""
        current += block
    chunks.append(current)
    for chunk in chunks:
        await tg.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


# ------------------------------------------------------------------ catalog & cards

async def home_markup(session, bot, user_id: int) -> Markup:
    rows = [[Btn("📚 Testlar", callback_data="qz:cat:p:0"), Btn("🔎 Qidirish", callback_data="qz:find")]]
    if await can_create(session, bot, user_id):
        rows.append([Btn("➕ Test yaratish", callback_data="qz:new"), Btn("🗂 Mening testlarim", callback_data="qz:my:0")])
    rows.append([Btn("📊 Natijalarim", callback_data="qz:res"), Btn("❓ Yordam", callback_data="qz:help")])
    if await cinema.is_admin(session, bot, user_id):
        rows.append([Btn("🛠 Admin panel", callback_data="qa:home")])
    return Markup(rows)


async def show_home(tg, callback, chat_id, session, bot):
    menu = await cinema.ensure_start_menu(session, bot, WELCOME)
    await show(tg, callback, chat_id, menu.message_text or WELCOME, await home_markup(session, bot, chat_id))


def _listable(bot):
    return (QuizTest.bot_id == bot.id, QuizTest.is_public.is_(True), QuizTest.is_active.is_(True),
            QuizTest.is_draft.is_(False), QuizTest.questions_count > 0)


async def show_tests(tg, callback, chat_id, session, bot, *, title, conds, order, page, nav_prefix, empty, extra_rows=()):
    total = (await session.execute(select(func.count(QuizTest.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    items = (await session.execute(select(QuizTest).where(*conds).order_by(*order).limit(PAGE).offset(page * PAGE))).scalars().all()
    rows = [[Btn(f"{'📝 ' if not t.is_draft else '✏️ '}{t.title} · {t.questions_count}"[:60], callback_data=f"qz:t:{t.id}")] for t in items]
    nav = ([Btn("◀️", callback_data=f"{nav_prefix}:{page - 1}")] if page else []) + \
          ([Btn("▶️", callback_data=f"{nav_prefix}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        rows.append(nav)
    rows += [list(r) for r in extra_rows]
    rows.append([Btn("🏠 Bosh sahifa", callback_data="qz:home")])
    text = f"{title} ({total})" if items else f"{title}\n\n{empty}"
    await show(tg, callback, chat_id, text, Markup(rows))


async def show_catalog(tg, callback, chat_id, session, bot, mode: str, page: int):
    order = (QuizTest.plays.desc(), QuizTest.id.desc()) if mode == "p" else (QuizTest.id.desc(),)
    other = "n" if mode == "p" else "p"
    switch = [Btn("🆕 Yangilari" if mode == "p" else "🔥 Ommabop", callback_data=f"qz:cat:{other}:0")]
    await show_tests(tg, callback, chat_id, session, bot, title="🔥 <b>Ommabop testlar</b>" if mode == "p" else "🆕 <b>Yangi testlar</b>",
                     conds=_listable(bot), order=order, page=page, nav_prefix=f"qz:cat:{mode}",
                     empty="Hali test yo‘q. Birinchisini siz yarating!", extra_rows=[switch])


async def search_tests(tg, chat_id, session, bot, query: str):
    like = f"%{query.strip().lower()}%"
    conds = (*_listable(bot), or_(func.lower(QuizTest.title).like(like), func.lower(QuizTest.description).like(like)))
    await show_tests(tg, None, chat_id, session, bot, title=f"🔎 «{esc(query[:40])}»", conds=conds,
                     order=(QuizTest.plays.desc(), QuizTest.id.desc()), page=0, nav_prefix="qz:cat:p",
                     empty="Hech narsa topilmadi. Boshqa so‘z yozing.")


async def visible_test(session, bot, test_id: int, user_id: int):
    test = await session.get(QuizTest, test_id)
    if test is None or test.bot_id != bot.id:
        return None
    if (test.is_active and not test.is_draft) or test.owner_tg_id == user_id or await cinema.is_admin(session, bot, user_id):
        return test
    return None


async def show_test(tg, callback, chat_id, session, bot, test):
    best = (await leaderboard(session, test.id, 1))
    avg = (await session.execute(select(func.avg(QuizAttempt.score * 100.0 / QuizAttempt.total)).where(
        QuizAttempt.test_id == test.id, QuizAttempt.status == ATTEMPT_FINISHED, QuizAttempt.total > 0))).scalar()
    lines = [f"📝 <b>{esc(test.title)}</b>"]
    if test.description:
        lines += ["", esc(test.description)]
    count = test.pick_count if test.pick_count and test.pick_count < test.questions_count else test.questions_count
    lines += ["", f"❓ Savollar: <b>{count}</b>" + (f" (jami {test.questions_count} tadan tasodifiy)" if count != test.questions_count else ""),
              f"⏱ Har biriga: <b>{fmt_limit(test.time_limit_sec)}</b>", f"👥 Ishlangan: <b>{test.plays}</b> marta"]
    if avg is not None:
        lines.append(f"📈 O‘rtacha natija: <b>{round(avg)}%</b>")
    if best:
        lines.append(f"🥇 Eng yaxshi: {esc(best[0].user_name)} — {best[0].score}/{best[0].total}")
    if test.owner_name:
        lines.append(f"👤 Muallif: {esc(test.owner_name)}")
    flags = ([] if test.is_active else ["🚫 admin tomonidan yashirilgan"]) + (["✏️ qoralama"] if test.is_draft else []) + \
            ([] if test.is_public or test.is_draft else ["🔒 faqat havola orqali"])
    if flags:
        lines.append("\n" + " · ".join(flags))
    rows = []
    if test.questions_count and test.is_active:
        rows.append([Btn("▶️ Boshlash", callback_data=f"qz:go:{test.id}")])
    rows.append([Btn("🏆 Reyting", callback_data=f"qz:top:{test.id}")])
    if bot.username and not test.is_draft:
        rows.append([Btn("📤 Ulashish", url=f"https://t.me/share/url?url={deep_link(bot, test)}&text={_quote(test.title)}")])
    if test.owner_tg_id == chat_id or await cinema.is_admin(session, bot, chat_id):
        rows.append([Btn("⚙️ Boshqarish", callback_data=f"qz:m:{test.id}")])
    rows.append([Btn("⬅️ Testlar", callback_data="qz:cat:p:0")])
    await show(tg, callback, chat_id, "\n".join(lines), Markup(rows))


async def show_my_results(tg, callback, chat_id, session, bot):
    from engine.booking_time import fmt_dt, tz_of
    tz = tz_of(None)
    rows = (await session.execute(
        select(QuizAttempt, QuizTest.title).join(QuizTest, QuizTest.id == QuizAttempt.test_id)
        .where(QuizAttempt.bot_id == bot.id, QuizAttempt.tg_user_id == chat_id, QuizAttempt.status == ATTEMPT_FINISHED)
        .order_by(QuizAttempt.id.desc()).limit(10)
    )).all()
    if not rows:
        await show(tg, callback, chat_id, "📊 Hali birorta testni yakunlamagansiz.", Markup([[Btn("📚 Testlar", callback_data="qz:cat:p:0")]]))
        return
    lines = ["📊 <b>Oxirgi natijalaringiz</b>", ""]
    lines += [f"• {esc(title)} — <b>{a.score}/{a.total}</b> · {fmt_dt(a.finished_at, tz)}" for a, title in rows]
    await show(tg, callback, chat_id, "\n".join(lines), Markup([[Btn("🏠 Bosh sahifa", callback_data="qz:home")]]))


HELP = (
    "❓ <b>Qanday ishlaydi?</b>\n\n"
    "📚 «Testlar» — tayyor testlar. Testni tanlab «Boshlash» ni bosing: savollar Telegram so‘rovnomasi ko‘rinishida keladi, "
    "har biriga cheklangan vaqt beriladi.\n"
    "🔎 Test nomini shunchaki yozsangiz ham qidiradi.\n"
    "➕ «Test yaratish» — nom, tavsif, savol vaqti va savollarni kiriting. Savollarni <b>txt fayl</b>, matn yoki Telegram «Quiz» so‘rovi sifatida yuborish mumkin.\n\n"
    "<b>TXT format:</b>\n<code>#Savol matni\n+To‘g‘ri javob\n-Noto‘g‘ri javob\n!Izoh (ixtiyoriy)</code>\n"
    "Bir nechta <code>+</code> bo‘lsa — ko‘p javobli savol.\n\n"
    "To‘xtatish: /stop"
)


# ------------------------------------------------------------------ dispatch

async def handle(bot, update, session, tg):
    if update.get("poll_answer"):
        await on_poll_answer(bot, update["poll_answer"], session, tg)
    elif update.get("callback_query"):
        await _on_callback(bot, update["callback_query"], session, tg)
    elif update.get("message"):
        await _on_message(bot, update["message"], session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    uid = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    admin = await cinema.is_admin(session, bot, uid)
    if data.startswith("qa:"):
        if admin:
            await quiz_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    if data == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, uid, session, use_cache=False):
            await show_home(tg, None, uid, session, bot)
        return
    if not data.startswith("qz:"):
        return
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)
    parts = data.split(":")
    act = parts[1]
    arg = parts[2:]
    num = [int(p) for p in arg if p.lstrip("-").isdigit()]

    if act == "home":
        await set_state(session, us)
        return await show_home(tg, callback, uid, session, bot)
    if act == "help":
        return await show(tg, callback, uid, HELP, Markup([[Btn("🏠 Bosh sahifa", callback_data="qz:home")]]))
    if act == "cat":
        return await show_catalog(tg, callback, uid, session, bot, arg[0] if arg and arg[0] in "pn" else "p", num[-1] if num else 0)
    if act == "find":
        await set_state(session, us, "qz_find", {})
        return await show(tg, callback, uid, "🔎 Test nomini yoki mavzusini yozing.",
                          Markup([[Btn("✖️ Bekor qilish", callback_data="qz:home")]]))
    if act == "res":
        return await show_my_results(tg, callback, uid, session, bot)
    if act in ("t", "go", "top") and num:
        test = await visible_test(session, bot, num[0], uid)
        if test is None:
            return await show(tg, callback, uid, "Test topilmadi yoki yashirilgan.", Markup([[Btn("📚 Testlar", callback_data="qz:cat:p:0")]]))
        if act == "t":
            return await show_test(tg, callback, uid, session, bot, test)
        if act == "top":
            return await show_leaderboard(tg, callback, uid, session, bot, test)
        if not test.is_active or test.is_draft or not test.questions_count:
            return await show(tg, callback, uid, "Bu testni hozircha ishlab bo‘lmaydi.", Markup([[Btn("📚 Testlar", callback_data="qz:cat:p:0")]]))
        await set_state(session, us)
        await start_attempt(session, tg, bot, test, user)
        return
    if act in ("rev", "resume") and num:
        attempt = await session.get(QuizAttempt, num[0])
        if attempt is None or attempt.tg_user_id != uid or attempt.bot_id != bot.id:
            return
        if act == "rev":
            return await show_review(tg, uid, session, attempt)
        test = await session.get(QuizTest, attempt.test_id)
        if attempt.status != ATTEMPT_ABANDONED or test is None or attempt.current >= attempt.total:
            return
        for other in (await session.execute(select(QuizAttempt).where(
                QuizAttempt.bot_id == bot.id, QuizAttempt.tg_user_id == uid, QuizAttempt.status == ATTEMPT_ACTIVE))).scalars().all():
            other.status = ATTEMPT_ABANDONED
        attempt.status, attempt.missed_streak = ATTEMPT_ACTIVE, 0
        await session.commit()
        await tg.send_message(chat_id=uid, text="▶️ Davom etamiz!")
        return await send_question(session, tg, bot, test, attempt)
    await quiz_create.on_callback(bot, callback, session, tg, us, act, arg, num)


async def _on_message(bot, message, session, tg):
    if (message.get("chat") or {}).get("type") != "private":
        return
    sender = message["from"]
    uid = sender["id"]
    if sender.get("is_bot"):
        return
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    payload = text.split(maxsplit=1)[1].strip() if cmd == "/start" and len(text.split()) > 1 else None
    await touch_user(session, bot.id, sender, source=payload)
    admin = await cinema.is_admin(session, bot, uid)
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)

    if cmd == "/stop":
        stopped = (await session.execute(select(QuizAttempt).where(
            QuizAttempt.bot_id == bot.id, QuizAttempt.tg_user_id == uid, QuizAttempt.status == ATTEMPT_ACTIVE))).scalars().all()
        for a in stopped:
            a.status = ATTEMPT_ABANDONED
        await session.commit()
        await tg.send_message(chat_id=uid, text="⏹ Test to‘xtatildi." if stopped else "Hozir ishlayotgan test yo‘q.")
        return
    if cmd in ("/start", "/cancel"):
        if us.state and us.state.startswith("qz_") and cmd == "/cancel":
            await quiz_create.cancel(bot, session, tg, us, uid)
        await set_state(session, us)
        if cmd == "/start" and payload and payload[0] == "t" and payload[1:].isdigit():
            test = await visible_test(session, bot, int(payload[1:]), uid)
            if test:
                return await show_test(tg, None, uid, session, bot, test)
        return await show_home(tg, None, uid, session, bot)
    if admin and cmd == "/admin":
        await set_state(session, us)
        return await quiz_admin.show_home(tg, None, uid, session, bot)
    if us.state and us.state.startswith("qa_") and admin:
        if await quiz_admin.on_message(bot, message, session, tg, us):
            return
    if us.state and us.state.startswith("qz_"):
        if us.state == "qz_find" and text:
            await set_state(session, us)
            return await search_tests(tg, uid, session, bot, text)
        if await quiz_create.on_message(bot, message, session, tg, us):
            return
    if text and not text.startswith("/"):
        return await search_tests(tg, uid, session, bot, text)  # typing a name anywhere searches the catalog
    await show_home(tg, None, uid, session, bot)
