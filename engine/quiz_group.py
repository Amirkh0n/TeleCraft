"""Live quiz contests in group chats.

Anyone in a group writes ``/test`` (or ``/test@botname``), picks a test and presses «Boshlash». The bot then
asks every question as a non-anonymous poll for the whole group at the same time. A correct answer is worth
1000 points plus up to 500 for speed; after each question the bot shows the right answer and the top 3, and
at the end the final ranking. Ties go to the member who answered correctly in less total time.

The game is one background task per group (``run_game``). Its state lives in the database (``QuizGame``),
so a restart resumes a game that is still fresh (``resume_games``). Members' first answer to each question
is stored once (``QuizGameAnswer``); later votes are ignored.
"""
import asyncio
import random
import weakref
from datetime import timedelta

from sqlalchemy import case, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.database import AsyncSessionLocal
from core.logger import get_logger
from engine import cinema, quiz_group_logic as gl
from engine.booking_time import as_utc, utcnow
from engine.quiz_parse import poll_explanation, poll_view
from engine.telegram_client import get_client
from models.bots import Bot
from models.quiz import GAME_FINISHED, GAME_RUNNING, GAME_STOPPED, QuizGame, QuizGameAnswer, QuizQuestion, QuizTest

logger = get_logger("quiz.group")
esc = cinema.esc
show = cinema._show

GROUP_TYPES = ("group", "supergroup")
START_DELAY = 5
PAUSE = 4
GRACE = 1.0
MAX_IDLE = 3          # questions in a row nobody answers -> the game stops itself
STALE_MINUTES = 10    # after a restart, older games are closed instead of resumed
PAGE = 6
ANSWER_GRACE = 3      # seconds after the deadline in which a vote still counts

HELP = ("👥 <b>Guruhda test</b>\n\n/test — testni tanlash va boshlash\n/test &lt;raqam yoki nom&gt; — aniq testni topish\n"
        "/top — joriy reyting\n/stoptest — o‘yinni to‘xtatish (boshlagan, guruh admini yoki bot admini)\n\n"
        "Savollar hamma uchun bir vaqtda keladi: to‘g‘ri javob 1000 ball + tezlik uchun 500 gacha qo‘shimcha.\n"
        "<i>Buyruqlarni <code>/test@{username}</code> ko‘rinishida yozing.</i>")

_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()
_start_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()
_runners: dict = {}


def game_lock(game_id: int) -> asyncio.Lock:
    lock = _locks.get(game_id)
    if lock is None:
        lock = _locks[game_id] = asyncio.Lock()
    return lock


def chat_lock(chat_id: int) -> asyncio.Lock:
    lock = _start_locks.get(chat_id)
    if lock is None:
        lock = _start_locks[chat_id] = asyncio.Lock()
    return lock


def display_name(user: dict) -> str:
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return (name or user.get("username") or "Ishtirokchi")[:60]


def fmt_limit(sec: int) -> str:
    return f"{sec} soniya" if sec < 60 else f"{sec // 60} daqiqa" + (f" {sec % 60} soniya" if sec % 60 else "")


async def active_game(session, bot_id: int, chat_id: int):
    return (await session.execute(select(QuizGame).where(
        QuizGame.bot_id == bot_id, QuizGame.chat_id == chat_id, QuizGame.status == GAME_RUNNING).order_by(QuizGame.id.desc()))).scalars().first()


async def standings(session, game_id: int):
    rows = (await session.execute(
        select(QuizGameAnswer.tg_user_id, func.max(QuizGameAnswer.user_name), func.sum(QuizGameAnswer.points),
               func.sum(case((QuizGameAnswer.ok.is_(True), 1), else_=0)), func.count(QuizGameAnswer.id),
               func.sum(case((QuizGameAnswer.ok.is_(True), QuizGameAnswer.ms), else_=0)))
        .where(QuizGameAnswer.game_id == game_id).group_by(QuizGameAnswer.tg_user_id))).all()
    return gl.rank([(r[0], r[1] or "", int(r[2] or 0), int(r[3] or 0), int(r[4] or 0), int(r[5] or 0)) for r in rows])


def board_lines(ranked, limit: int):
    return [f"{gl.medal(i)} {esc(r[1])} — <b>{gl.fmt_points(r[2])}</b> ball · {r[3]}/{r[4]} ✅" for i, r in enumerate(ranked[:limit])]


# ------------------------------------------------------------------ choosing a test

async def listed_tests(session, bot, query: str | None, page: int):
    conds = [QuizTest.bot_id == bot.id, QuizTest.is_public.is_(True), QuizTest.is_active.is_(True),
             QuizTest.is_draft.is_(False), QuizTest.questions_count > 0]
    if query:
        conds.append(QuizTest.title.ilike(f"%{query[:60]}%"))
    total = (await session.execute(select(func.count(QuizTest.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(QuizTest).where(*conds).order_by(QuizTest.id.desc()).limit(PAGE).offset(page * PAGE))).scalars().all()
    return rows, total, pages, page


async def show_list(tg, callback, chat_id, session, bot, query=None, page=0):
    rows, total, pages, page = await listed_tests(session, bot, query, page)
    if not rows:
        text = "Hech narsa topilmadi. /test bilan to‘liq ro‘yxatni ko‘ring." if query else "Hozircha guruh uchun tayyor test yo‘q."
        return await show(tg, callback, chat_id, text, None)
    kb = [[Btn(f"{t.title} · {t.questions_count} savol"[:60], callback_data=f"qg:t:{t.id}")] for t in rows]
    if not query:
        nav = ([Btn("⬅️", callback_data=f"qg:pg:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"qg:pg:{page + 1}")] if page < pages - 1 else [])
        if nav:
            kb.append(nav)
    await show(tg, callback, chat_id, f"🧠 <b>Guruh uchun testlar</b> ({total})\nBittasini tanlang:", Markup(kb))


async def question_count(session, test) -> int:
    n = (await session.execute(select(func.count(QuizQuestion.id)).where(QuizQuestion.test_id == test.id))).scalar() or 0
    return min(n, test.pick_count) if test.pick_count and test.pick_count > 0 else n


async def show_card(tg, callback, chat_id, session, test):
    n = await question_count(session, test)
    text = (f"🧠 <b>{esc(test.title)}</b>\n" + (f"{esc(test.description[:300])}\n" if test.description else "")
            + f"\n❓ {n} ta savol · ⏱ har biriga {fmt_limit(max(5, min(600, test.time_limit_sec)))}\n"
              "🏆 To‘g‘ri javob 1000 ball + tezlik uchun 500 gacha\n\nSavollar guruhdagi hamma uchun bir vaqtda keladi.")
    await show(tg, callback, chat_id, text, Markup([[Btn("▶️ Boshlash", callback_data=f"qg:go:{test.id}")],
                                                    [Btn("⬅️ Ro‘yxat", callback_data="qg:pg:0")]]))


async def usable_test(session, bot, test_id: int, user_id: int):
    test = await session.get(QuizTest, test_id)
    if test is None or test.bot_id != bot.id or test.is_draft or test.questions_count <= 0:
        return None
    if (test.is_active and test.is_public) or test.owner_tg_id == user_id or await cinema.is_admin(session, bot, user_id):
        return test
    return None


# ------------------------------------------------------------------ permissions & stopping

async def can_stop(session, bot, tg, game, user_id: int) -> bool:
    if game.starter_id == user_id or await cinema.is_admin(session, bot, user_id):
        return True
    try:
        member = await tg.get_chat_member(chat_id=game.chat_id, user_id=user_id)
        return getattr(member, "status", "") in ("creator", "administrator")
    except TelegramError:
        return False


async def stop_game(session, tg, game, *, reason: str):
    async with game_lock(game.id):
        await session.refresh(game)
        if game.status != GAME_RUNNING:
            return False
        game.status, game.finished_at = GAME_STOPPED, utcnow()
        message_id, game.poll_id = game.poll_message_id, None
        await session.commit()
    task = _runners.pop(game.id, None)
    if task and task is not asyncio.current_task():
        task.cancel()
    if message_id:
        try:
            await tg.stop_poll(chat_id=game.chat_id, message_id=message_id)
        except TelegramError:
            pass
    ranked = await standings(session, game.id)
    text = f"⏹ <b>Test to‘xtatildi</b> {reason}".rstrip()
    if ranked:
        text += "\n\n📊 <b>Natija</b>\n" + "\n".join(board_lines(ranked, 10))
    await tg.send_message(chat_id=game.chat_id, text=text, parse_mode="HTML")
    return True


# ------------------------------------------------------------------ the game loop

async def _default_client(bot):
    return await get_client(bot.plain_token)


def schedule_game(game_id: int, **kw):
    task = asyncio.create_task(run_game(game_id, **kw))
    _runners[game_id] = task
    task.add_done_callback(lambda t: _runners.pop(game_id, None) if _runners.get(game_id) is t else None)
    return task


async def run_game(game_id: int, *, session_factory=AsyncSessionLocal, client_for=_default_client, sleep=asyncio.sleep):
    try:
        async with session_factory() as session:
            game = await session.get(QuizGame, game_id)
            if game is None or game.status != GAME_RUNNING:
                return
            fresh = game.current == -1 and game.poll_id is None
        if fresh:
            await sleep(START_DELAY)
        while True:
            state, deadline = await _send_next(game_id, session_factory, client_for)
            if state != "open":
                return
            await sleep(max(0.0, (as_utc(deadline) - utcnow()).total_seconds()) + GRACE)
            if await _close_question(game_id, session_factory, client_for) != "continue":
                return
            await sleep(PAUSE)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("quiz group: game %s crashed", game_id)


async def _send_next(game_id, session_factory, client_for):
    """Send the next question (or finish). Returns ("open", deadline) or (state, None)."""
    async with session_factory() as session:
        async with game_lock(game_id):
            game = await session.get(QuizGame, game_id)
            if game is None:
                return "gone", None
            await session.refresh(game)
            if game.status != GAME_RUNNING:
                return "stopped", None
            if game.poll_id:  # resumed while a question was open
                return "open", game.deadline
            bot, test = await session.get(Bot, game.bot_id), await session.get(QuizTest, game.test_id)
            tg = await client_for(bot)
            while True:
                idx = game.current + 1
                if idx >= game.total:
                    await _finish(session, tg, game, test)
                    return "finished", None
                question = await session.get(QuizQuestion, game.order[idx])
                if question is not None:
                    break
                game.current = idx  # deleted since the game started: skip it
            order = list(range(len(question.options)))
            if test.shuffle_options:
                random.shuffle(order)
            options = [question.options[i] for i in order]
            shown = [order.index(c) for c in question.correct]
            is_quiz = len(shown) == 1
            pre, text, poll_options = poll_view(f"{idx + 1}/{game.total}. {question.text}", options)
            kwargs = dict(chat_id=game.chat_id, question=text, options=poll_options, is_anonymous=False, open_period=game.limit_sec)
            if is_quiz:
                kwargs.update(type="quiz", correct_option_id=shown[0])
                if poll_explanation(question.explanation):
                    kwargs["explanation"] = poll_explanation(question.explanation)
            else:
                kwargs.update(type="regular", allows_multiple_answers=True)
            try:
                if pre:
                    await tg.send_message(chat_id=game.chat_id, text=pre, parse_mode="HTML")
                msg = await tg.send_poll(**kwargs)
            except TelegramError as exc:  # kicked from the group, no rights, ...
                logger.warning("quiz group: cannot send a question to chat %s: %s", game.chat_id, exc)
                game.status, game.finished_at = GAME_STOPPED, utcnow()
                await session.commit()
                return "error", None
            now = utcnow()
            game.current, game.poll_id, game.poll_message_id = idx, msg.poll.id, msg.message_id
            game.option_order, game.is_quiz, game.sent_at = order, is_quiz, now
            game.deadline = now + timedelta(seconds=game.limit_sec)
            await session.commit()
            return "open", game.deadline


async def _close_question(game_id, session_factory, client_for):
    async with session_factory() as session:
        async with game_lock(game_id):
            game = await session.get(QuizGame, game_id)
            if game is None:
                return "gone"
            await session.refresh(game)
            if game.status != GAME_RUNNING:
                return "stopped"
            if not game.poll_id:
                return "continue"
            idx, message_id = game.current, game.poll_message_id
            game.poll_id = None  # late votes are ignored from now on
            bot = await session.get(Bot, game.bot_id)
            tg = await client_for(bot)
            answers = (await session.execute(select(QuizGameAnswer).where(
                QuizGameAnswer.game_id == game.id, QuizGameAnswer.qidx == idx))).scalars().all()
            game.idle_streak = 0 if answers else game.idle_streak + 1
            idle_out = game.idle_streak >= MAX_IDLE and idx + 1 < game.total
            await session.commit()
            question = await session.get(QuizQuestion, game.order[idx])
            ranked = await standings(session, game.id)
        try:
            await tg.stop_poll(chat_id=game.chat_id, message_id=message_id)
        except TelegramError:
            pass  # Telegram already closed it by open_period
        lines = []
        if question:
            right = ", ".join(esc(question.options[i]) for i in question.correct)
            lines.append(f"✅ To‘g‘ri javob: <b>{right}</b>")
            if question.explanation:
                lines.append(f"💡 {esc(question.explanation)}")
        right_count = sum(1 for a in answers if a.ok)
        lines.append(f"👥 Javob berdi: {len(answers)} · to‘g‘ri: {right_count}")
        if ranked and answers:
            lines += ["", "📊 <b>Hozirgi reyting</b>"] + board_lines(ranked, 3)
        try:
            await tg.send_message(chat_id=game.chat_id, text="\n".join(lines), parse_mode="HTML")
        except TelegramError as exc:
            logger.info("quiz group: summary not sent to %s: %s", game.chat_id, exc)
        if idle_out:
            await stop_game(session, tg, game, reason=f"— {MAX_IDLE} ta savol ketma-ket javobsiz qoldi.")
            return "stopped"
        return "continue"


async def _finish(session, tg, game, test):
    game.status, game.finished_at, game.poll_id = GAME_FINISHED, utcnow(), None
    if test is not None:
        test.plays += 1
    await session.commit()
    ranked = await standings(session, game.id)
    title = esc(test.title) if test else "Test"
    if ranked:
        text = (f"🏁 <b>{title}</b> — yakuniy natijalar\n\n" + "\n".join(board_lines(ranked, 15))
                + f"\n\n👥 Qatnashchilar: {len(ranked)} · ❓ Savollar: {game.total}\nYana o‘ynash: /test")
    else:
        text = f"🏁 <b>{title}</b> tugadi. Hech kim qatnashmadi. 😔\nYana urinib ko‘rish: /test"
    try:
        await tg.send_message(chat_id=game.chat_id, text=text, parse_mode="HTML")
    except TelegramError as exc:
        logger.info("quiz group: results not sent to %s: %s", game.chat_id, exc)


async def resume_games(*, session_factory=AsyncSessionLocal, client_for=_default_client, sleep=asyncio.sleep) -> int:
    """After a restart: continue games that are still fresh, close the stale ones silently."""
    async with session_factory() as session:
        games = (await session.execute(select(QuizGame).where(QuizGame.status == GAME_RUNNING))).scalars().all()
        now, resumed = utcnow(), []
        for g in games:
            seen = as_utc(g.deadline or g.sent_at or g.created_at)
            if now - seen > timedelta(minutes=STALE_MINUTES):
                g.status, g.finished_at = GAME_STOPPED, now
            else:
                resumed.append(g.id)
        await session.commit()
    for game_id in resumed:
        schedule_game(game_id, session_factory=session_factory, client_for=client_for, sleep=sleep)
    return len(resumed)


# ------------------------------------------------------------------ answers

async def on_poll_answer(bot, answer: dict, session) -> bool:
    """True when the poll belongs to a group game (so the personal-test code must not see it)."""
    poll_id = str(answer.get("poll_id"))
    game = (await session.execute(select(QuizGame).where(QuizGame.poll_id == poll_id, QuizGame.bot_id == bot.id))).scalars().first()
    if game is None:
        return False
    user = answer.get("user") or {}
    option_ids = answer.get("option_ids") or []
    if not option_ids or user.get("id") is None or user.get("is_bot"):
        return True
    async with game_lock(game.id):
        await session.refresh(game)
        now = utcnow()
        if game.status != GAME_RUNNING or game.poll_id != poll_id or now > as_utc(game.deadline) + timedelta(seconds=ANSWER_GRACE):
            return True
        existing = (await session.execute(select(QuizGameAnswer.id).where(
            QuizGameAnswer.game_id == game.id, QuizGameAnswer.qidx == game.current, QuizGameAnswer.tg_user_id == user["id"]))).first()
        if existing:
            return True
        question = await session.get(QuizQuestion, game.order[game.current])
        order = game.option_order or []
        chosen = sorted({order[i] for i in option_ids if 0 <= i < len(order)})
        ok = bool(question) and chosen == sorted(question.correct)
        limit_ms = game.limit_sec * 1000
        elapsed = int((now - as_utc(game.sent_at)).total_seconds() * 1000)
        session.add(QuizGameAnswer(game_id=game.id, qidx=game.current, tg_user_id=user["id"], user_name=display_name(user),
                                   ok=ok, points=gl.points(ok, elapsed, limit_ms), ms=min(max(0, elapsed), limit_ms)))
        await session.commit()
    return True


# ------------------------------------------------------------------ updates from the group

def _command(text: str, username):
    """('/test', 'arg') for '/test@MyBot arg'. None when the command is addressed to another bot."""
    if not text.startswith("/"):
        return None, ""
    head, _, rest = text.partition(" ")
    name, _, target = head.partition("@")
    if target and username and target.lower() != username.lower():
        return None, ""
    return name.lower(), rest.strip()


async def handle_message(bot, message, session, tg):
    sender = message.get("from") or {}
    if sender.get("is_bot") or sender.get("id") is None:
        return
    chat_id = message["chat"]["id"]
    cmd, arg = _command((message.get("text") or "").strip(), bot.username)
    if cmd in ("/start", "/help", "/yordam"):
        return await tg.send_message(chat_id=chat_id, parse_mode="HTML", text=HELP.format(username=bot.username or "bot"))
    if cmd in ("/test", "/quiz"):
        game = await active_game(session, bot.id, chat_id)
        if game:
            test = await session.get(QuizTest, game.test_id)
            return await tg.send_message(chat_id=chat_id, parse_mode="HTML",
                                         text=f"⏳ Hozir «{esc(test.title if test else 'test')}» o‘tmoqda. To‘xtatish: /stoptest · reyting: /top")
        if arg.isdigit():
            test = await usable_test(session, bot, int(arg), sender["id"])
            if test:
                return await show_card(tg, None, chat_id, session, test)
            return await tg.send_message(chat_id=chat_id, text="Bunday test topilmadi.")
        return await show_list(tg, None, chat_id, session, bot, query=arg or None)
    if cmd == "/top":
        game = await active_game(session, bot.id, chat_id)
        ranked = await standings(session, game.id) if game else []
        text = "📊 <b>Hozirgi reyting</b>\n\n" + "\n".join(board_lines(ranked, 10)) if ranked else "Hozircha reyting yo‘q."
        return await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    if cmd == "/stoptest":
        game = await active_game(session, bot.id, chat_id)
        if game is None:
            return await tg.send_message(chat_id=chat_id, text="Hozir o‘tayotgan test yo‘q.")
        if not await can_stop(session, bot, tg, game, sender["id"]):
            return await tg.send_message(chat_id=chat_id, text="⛔️ Testni faqat uni boshlagan odam yoki guruh adminlari to‘xtata oladi.")
        await stop_game(session, tg, game, reason="")


async def handle_callback(bot, callback, session, tg):
    user = callback.get("from") or {}
    chat = (callback.get("message") or {}).get("chat") or {}
    if chat.get("type") not in GROUP_TYPES or user.get("id") is None:
        return
    chat_id = chat["id"]
    parts = (callback.get("data") or "").split(":")
    act, arg = parts[1], parts[2:]
    num = int(arg[0]) if arg and arg[0].isdigit() else 0

    if act == "pg":
        return await show_list(tg, callback, chat_id, session, bot, page=num)
    if act == "stop":
        game = await active_game(session, bot.id, chat_id)
        if game is None:
            return
        if not await can_stop(session, bot, tg, game, user["id"]):
            return await tg.send_message(chat_id=chat_id, text="⛔️ Testni faqat uni boshlagan odam yoki guruh adminlari to‘xtata oladi.")
        return await stop_game(session, tg, game, reason="")
    test = await usable_test(session, bot, num, user["id"])
    if test is None:
        return await show_list(tg, callback, chat_id, session, bot)
    if act == "t":
        return await show_card(tg, callback, chat_id, session, test)
    if act != "go":
        return
    async with chat_lock(chat_id):
        if await active_game(session, bot.id, chat_id):
            return await tg.send_message(chat_id=chat_id, text="⏳ Bu guruhda test allaqachon o‘tmoqda.")
        questions = (await session.execute(select(QuizQuestion.id).where(QuizQuestion.test_id == test.id).order_by(QuizQuestion.position, QuizQuestion.id))).scalars().all()
        ids = list(questions)
        if not ids:
            return await tg.send_message(chat_id=chat_id, text="Bu testda savol yo‘q.")
        if test.pick_count and 0 < test.pick_count < len(ids):
            ids = random.sample(ids, test.pick_count) if test.shuffle_questions else ids[:test.pick_count]
        if test.shuffle_questions:
            random.shuffle(ids)
        limit = max(5, min(600, test.time_limit_sec))
        game = QuizGame(bot_id=bot.id, test_id=test.id, chat_id=chat_id, starter_id=user["id"], order=ids, total=len(ids), limit_sec=limit)
        session.add(game)
        await session.commit()
    await show(tg, callback, chat_id,
               (f"🏁 <b>{esc(test.title)}</b> boshlanmoqda!\n❓ {len(ids)} ta savol · ⏱ har biriga {fmt_limit(limit)}\n\n"
                f"Tayyor bo‘ling — {START_DELAY} soniyadan keyin birinchi savol. Hamma javob bera oladi!"),
               Markup([[Btn("⏹ To‘xtatish", callback_data="qg:stop")]]))
    schedule_game(game.id)
