"""Admin panel of quiz bots (``/admin``): moderation of all tests, creation policy, statistics.

Admins can also manage any test with the regular «⚙️ Boshqarish» screen.
"""
from sqlalchemy import func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from engine import cinema
from engine import quiz as core
from models.quiz import ATTEMPT_FINISHED, QuizAttempt, QuizTest

esc = cinema.esc
show = cinema._show
PAGE = 8
LIMITS = (5, 10, 30, 100, 0)


def back(target="qa:home", label="⬅️ Orqaga"):
    return [Btn(label, callback_data=target)]


async def show_home(tg, callback, chat_id, session, bot):
    st = await core.get_settings(session, bot.id)
    hidden = (await session.execute(select(func.count(QuizTest.id)).where(QuizTest.bot_id == bot.id, QuizTest.is_active.is_(False)))).scalar() or 0
    rows = [
        [Btn("📚 Barcha testlar", callback_data="qa:all:0"), Btn("🚫 Yashirilganlar" + (f" ({hidden})" if hidden else ""), callback_data="qa:hid:0")],
        [Btn("📊 Statistika", callback_data="qa:stats")],
        [Btn(f"👥 Kim test yaratadi: {'hamma' if st.who_can_create == 'everyone' else 'faqat adminlar'}", callback_data="qa:who")],
        [Btn(f"🔢 Foydalanuvchi limiti: {st.max_tests_per_user or 'cheksiz'}", callback_data="qa:lim")],
        [Btn("🏠 Foydalanuvchi menyusi", callback_data="qz:home")],
    ]
    await show(tg, callback, chat_id, "🛠 <b>Test bot — admin paneli</b>", Markup(rows))


async def list_tests(tg, callback, chat_id, session, bot, hidden: bool, page: int):
    conds = (QuizTest.bot_id == bot.id,) + ((QuizTest.is_active.is_(False),) if hidden else ())
    total = (await session.execute(select(func.count(QuizTest.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    items = (await session.execute(select(QuizTest).where(*conds).order_by(QuizTest.id.desc()).limit(PAGE).offset(page * PAGE))).scalars().all()
    rows = [[Btn(f"{'🚫 ' if not t.is_active else ''}{t.title} · {t.questions_count} · {t.owner_name}"[:60], callback_data=f"qz:m:{t.id}"),
             Btn("👁" if not t.is_active else "🚫", callback_data=f"qa:tog:{t.id}:{1 if hidden else 0}:{page}")] for t in items]
    nav_prefix = "qa:hid" if hidden else "qa:all"
    nav = ([Btn("◀️", callback_data=f"{nav_prefix}:{page - 1}")] if page else []) + \
          ([Btn("▶️", callback_data=f"{nav_prefix}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        rows.append(nav)
    rows.append(back())
    title = "🚫 <b>Yashirilgan testlar</b>" if hidden else "📚 <b>Barcha testlar</b>"
    hint = "\n\nTugma: 🚫 yashirish / 👁 ko‘rsatish. Nomini bossangiz — boshqarish." if items else "\n\nTest yo‘q."
    await show(tg, callback, chat_id, f"{title} ({total}){hint}", Markup(rows))


async def show_stats(tg, callback, chat_id, session, bot):
    async def scalar(q):
        return (await session.execute(q)).scalar() or 0
    tests = await scalar(select(func.count(QuizTest.id)).where(QuizTest.bot_id == bot.id, QuizTest.is_draft.is_(False)))
    questions = await scalar(select(func.coalesce(func.sum(QuizTest.questions_count), 0)).where(QuizTest.bot_id == bot.id))
    creators = await scalar(select(func.count(func.distinct(QuizTest.owner_tg_id))).where(QuizTest.bot_id == bot.id))
    done = await scalar(select(func.count(QuizAttempt.id)).where(QuizAttempt.bot_id == bot.id, QuizAttempt.status == ATTEMPT_FINISHED))
    solvers = await scalar(select(func.count(func.distinct(QuizAttempt.tg_user_id))).where(QuizAttempt.bot_id == bot.id))
    avg = (await session.execute(select(func.avg(QuizAttempt.score * 100.0 / QuizAttempt.total)).where(
        QuizAttempt.bot_id == bot.id, QuizAttempt.status == ATTEMPT_FINISHED, QuizAttempt.total > 0))).scalar()
    top = (await session.execute(select(QuizTest.title, QuizTest.plays).where(QuizTest.bot_id == bot.id, QuizTest.plays > 0)
                                 .order_by(QuizTest.plays.desc()).limit(5))).all()
    authors = (await session.execute(select(QuizTest.owner_name, func.count(QuizTest.id)).where(QuizTest.bot_id == bot.id)
                                     .group_by(QuizTest.owner_name).order_by(func.count(QuizTest.id).desc()).limit(3))).all()
    lines = ["📊 <b>Statistika</b>", "", f"📚 Testlar: <b>{tests}</b> · ❓ savollar: <b>{questions}</b> · ✍️ mualliflar: <b>{creators}</b>",
             f"🏁 Yakunlangan urinishlar: <b>{done}</b> · 👥 ishtirokchilar: <b>{solvers}</b>"]
    if avg is not None:
        lines.append(f"📈 O‘rtacha natija: <b>{round(avg)}%</b>")
    if top:
        lines += ["", "🔥 <b>Eng ko‘p ishlangan:</b>"] + [f"{n}. {esc(t)} — {p}" for n, (t, p) in enumerate(top, 1)]
    if authors:
        lines += ["", "✍️ <b>Faol mualliflar:</b>"] + [f"• {esc(a)} — {c} ta" for a, c in authors]
    await show(tg, callback, chat_id, "\n".join(lines), Markup([back()]))


async def on_callback(bot, callback, session, tg, us):
    uid = callback["from"]["id"]
    parts = callback["data"].split(":")
    act = parts[1] if len(parts) > 1 else ""
    num = [int(p) for p in parts[2:] if p.lstrip("-").isdigit()]
    if act == "home":
        await core.set_state(session, us)
        return await show_home(tg, callback, uid, session, bot)
    if act in ("all", "hid"):
        return await list_tests(tg, callback, uid, session, bot, act == "hid", num[0] if num else 0)
    if act == "tog" and len(num) >= 3:
        test = await session.get(QuizTest, num[0])
        if test and test.bot_id == bot.id:
            test.is_active = not test.is_active
            await session.commit()
        return await list_tests(tg, callback, uid, session, bot, bool(num[1]), num[2])
    if act == "stats":
        return await show_stats(tg, callback, uid, session, bot)
    st = await core.get_settings(session, bot.id)
    if act == "who":
        st.who_can_create = "admins" if st.who_can_create == "everyone" else "everyone"
        await session.commit()
        return await show_home(tg, callback, uid, session, bot)
    if act == "lim":
        st.max_tests_per_user = LIMITS[(LIMITS.index(st.max_tests_per_user) + 1) % len(LIMITS)] if st.max_tests_per_user in LIMITS else LIMITS[0]
        await session.commit()
        return await show_home(tg, callback, uid, session, bot)


async def on_message(bot, message, session, tg, us) -> bool:
    await core.set_state(session, us)  # the admin panel has no free-text steps
    return False
