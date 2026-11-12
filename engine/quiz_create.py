"""Creating and managing quiz tests inside the child bot: every user may create tests (unless the
admins restrict it), the owner and admins manage them.

Creation: title -> description -> time per question -> questions (TXT file, pasted text, or a
Telegram *Quiz* poll sent to the bot; any number of times) -> "Tayyor".
"""
from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, LinkPreviewOptions

from engine import cinema
from engine import quiz as core  # circular import: attributes are only used at call time
from engine.quiz_parse import AI_PROMPT, EXAMPLE, MAX_QUESTIONS, Question, decode, format_txt, parse, validate
from models.quiz import QuizAttempt, QuizPoll, QuizQuestion, QuizTest

esc = cinema.esc
show = cinema._show
TIME_CHOICES = (15, 30, 45, 60, 120, 180, 300)
MAX_FILE_BYTES = 1_000_000

FORMAT_HELP = (
    "<b>TXT format:</b>\n<code>#Savol matni\n+To‘g‘ri javob\n-Noto‘g‘ri javob\n-Noto‘g‘ri javob\n!Izoh (ixtiyoriy)</code>\n\n"
    "• Har savol <code>#</code> bilan, to‘g‘ri javob <code>+</code>, noto‘g‘ri <code>-</code> bilan boshlanadi.\n"
    "• Bir nechta <code>+</code> bo‘lsa — ko‘p javobli savol.\n• Savollar orasida bo‘sh qator qo‘ysangiz yaxshi.\n"
    "• 2–10 ta variant, kamida bitta to‘g‘ri javob."
)


def back(target: str, label: str = "⬅️ Orqaga"):
    return [Btn(label, callback_data=target)]


# ------------------------------------------------------------------ data helpers

async def add_questions(session, test, questions: list[Question]) -> tuple[int, int]:
    """Append questions; returns (added, skipped because the test is full)."""
    room = max(0, MAX_QUESTIONS - test.questions_count)
    take = questions[:room]
    position = (await session.execute(select(func.coalesce(func.max(QuizQuestion.position), 0)).where(QuizQuestion.test_id == test.id))).scalar()
    for i, q in enumerate(take, 1):
        session.add(QuizQuestion(test_id=test.id, position=position + i, text=q.text, options=q.options,
                                 correct=q.correct, explanation=q.explanation))
    test.questions_count += len(take)
    await session.commit()
    return len(take), len(questions) - len(take)


async def recount(session, test):
    test.questions_count = (await session.execute(select(func.count(QuizQuestion.id)).where(QuizQuestion.test_id == test.id))).scalar() or 0
    await session.commit()


async def delete_test(session, test):
    attempt_ids = select(QuizAttempt.id).where(QuizAttempt.test_id == test.id)
    await session.execute(delete(QuizPoll).where(QuizPoll.attempt_id.in_(attempt_ids)))
    await session.execute(delete(QuizAttempt).where(QuizAttempt.test_id == test.id))
    await session.execute(delete(QuizQuestion).where(QuizQuestion.test_id == test.id))
    await session.delete(test)
    await session.commit()


async def managed(session, bot, test_id, uid):
    test = await session.get(QuizTest, test_id)
    if test is None or test.bot_id != bot.id:
        return None
    return test if test.owner_tg_id == uid or await cinema.is_admin(session, bot, uid) else None


async def quota_problem(session, bot, uid):
    st = await core.get_settings(session, bot.id)
    if not await core.can_create(session, bot, uid):
        return "Hozircha test yaratish faqat adminlarga ruxsat etilgan."
    if st.max_tests_per_user and not await cinema.is_admin(session, bot, uid):
        have = (await session.execute(select(func.count(QuizTest.id)).where(QuizTest.bot_id == bot.id, QuizTest.owner_tg_id == uid))).scalar()
        if have >= st.max_tests_per_user:
            return f"Siz {st.max_tests_per_user} tagacha test yarata olasiz. Eskilarini o‘chiring."
    return None


# ------------------------------------------------------------------ creation prompts

def questions_markup(test) -> Markup:
    return Markup([
        [Btn(f"✅ Tayyor ({test.questions_count})" if test.is_draft else f"✅ Tayyor ({test.questions_count})", callback_data=f"qz:done:{test.id}")],
        [Btn("📄 Namuna fayl", callback_data="qz:tpl"), Btn("🤖 AI uchun so‘rov", callback_data="qz:ai")],
        [Btn("✖️ Bekor qilish", callback_data="qz:cancel")],
    ])


async def ask_questions(tg, chat_id, test, intro=""):
    text = (f"{intro}📥 <b>Endi savollarni yuboring</b> («{esc(test.title)}», jami: {test.questions_count}).\n\n"
            "Quyidagi usullardan birini tanlang (bir necha marta yuborib, qo‘shib borishingiz mumkin):\n"
            "1️⃣ <b>.txt fayl</b> yuboring (eng qulayi)\n2️⃣ Savollarni <b>matn</b> qilib shu yerga yozing/joylang\n"
            "3️⃣ Telegram’da <b>Quiz so‘rovi</b> yarating (📎 → So‘rov → Quiz) va shu yerga yuboring\n\n"
            f"{FORMAT_HELP}\n\nTugagach «✅ Tayyor» ni bosing.")
    await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=questions_markup(test))


async def cancel(bot, session, tg, us, uid):
    data = us.state_data or {}
    test = await session.get(QuizTest, data["test"]) if data.get("test") else None
    if test and test.bot_id == bot.id and test.owner_tg_id == uid and test.is_draft:
        await delete_test(session, test)
        await tg.send_message(chat_id=uid, text="❌ Test yaratish bekor qilindi.")
    else:
        await tg.send_message(chat_id=uid, text="Bekor qilindi.")


# ------------------------------------------------------------------ callbacks

async def on_callback(bot, callback, session, tg, us, act, arg, num):
    user = callback["from"]
    uid = user["id"]

    if act == "cancel":
        await cancel(bot, session, tg, us, uid)
        await core.set_state(session, us)
        return await core.show_home(tg, None, uid, session, bot)
    if act == "tpl":
        return await tg.send_document(chat_id=uid, document=EXAMPLE.encode("utf-8"), filename="namuna.txt",
                                      caption="📄 Namuna: shu formatda yozib, o‘z faylingizni yuboring.")
    if act == "ai":
        prompt = AI_PROMPT.replace("<", "&lt;")
        return await tg.send_message(chat_id=uid, parse_mode="HTML",
                                     text="🤖 Bu matnni ChatGPT/Claude kabi AI ga yuboring ({mavzu} va {soni} o‘rniga o‘zingiznikini yozing), "
                                          "chiqqan javobni shu yerga yuboring yoki .txt qilib saqlab yuboring:\n\n"
                                          f"<pre>{prompt}</pre>")
    if act == "new":
        problem = await quota_problem(session, bot, uid)
        if problem:
            return await show(tg, callback, uid, f"⚠️ {problem}", Markup([back("qz:home", "🏠 Bosh sahifa")]))
        await core.set_state(session, us, "qz_title", {})
        return await show(tg, callback, uid, "📝 <b>Yangi test</b>\n\nTest <b>nomini</b> yozing (masalan: Ingliz tili — Present Simple).",
                          Markup([[Btn("✖️ Bekor qilish", callback_data="qz:cancel")]]))
    if act == "tm" and num and us.state == "qz_time":
        return await _create_draft(bot, user, session, tg, us, num[0])
    if act == "my":
        return await core.show_tests(
            tg, callback, uid, session, bot, title="🗂 <b>Mening testlarim</b>",
            conds=(QuizTest.bot_id == bot.id, QuizTest.owner_tg_id == uid), order=(QuizTest.id.desc(),), page=num[0] if num else 0,
            nav_prefix="qz:my", empty="Siz hali test yaratmagansiz.",
            extra_rows=[[Btn("➕ Test yaratish", callback_data="qz:new")]])
    if not num:
        return
    test = await managed(session, bot, num[0], uid)
    if test is None:
        return await show(tg, callback, uid, "Test topilmadi yoki sizda ruxsat yo‘q.", Markup([back("qz:home", "🏠 Bosh sahifa")]))

    if act == "m":
        await core.set_state(session, us)
        return await show_manage(tg, callback, uid, session, bot, test)
    if act == "done":
        return await publish(bot, session, tg, us, test, uid, callback)
    if act == "ma":
        await core.set_state(session, us, "qz_q", {"test": test.id})
        return await ask_questions(tg, uid, test)
    if act == "mx":
        questions = await core.questions_of(session, test.id)
        if not questions:
            return await tg.send_message(chat_id=uid, text="Testda savol yo‘q.")
        return await tg.send_document(chat_id=uid, document=format_txt(questions).encode("utf-8"),
                                      filename=f"{_safe(test.title)}.txt", caption=f"📄 {test.title}: {len(questions)} ta savol")
    if act == "mt" and len(arg) > 1:
        flag = {"sq": "shuffle_questions", "so": "shuffle_options", "pub": "is_public"}.get(arg[1])
        if flag:
            setattr(test, flag, not getattr(test, flag))
            await session.commit()
        return await show_manage(tg, callback, uid, session, bot, test)
    if act == "me" and len(arg) > 1:
        prompts = {"title": "✏️ Yangi <b>nomni</b> yozing.", "desc": "📝 Yangi <b>tavsifni</b> yozing (olib tashlash: /skip).",
                   "time": "⏱ Har bir savol uchun <b>soniyani</b> yozing (5 dan 600 gacha).",
                   "pick": "🎯 Har urinishda nechta tasodifiy savol berilsin? Son yozing (hammasi uchun 0)."}
        if arg[1] in prompts:
            await core.set_state(session, us, "qz_e", {"id": test.id, "field": arg[1]})
            return await show(tg, callback, uid, prompts[arg[1]] + "\nBekor qilish: /cancel", Markup([back(f"qz:m:{test.id}", "✖️ Bekor qilish")]))
        return
    if act == "md":
        return await show(tg, callback, uid, f"🗑 <b>{esc(test.title)}</b> o‘chirilsinmi? Savollar va natijalar ham yo‘qoladi.",
                          Markup([[Btn("✅ Ha", callback_data=f"qz:mdy:{test.id}"), Btn("❌ Yo‘q", callback_data=f"qz:m:{test.id}")]]))
    if act == "mdy":
        await delete_test(session, test)
        return await core.show_tests(tg, callback, uid, session, bot, title="🗂 <b>Mening testlarim</b>",
                                     conds=(QuizTest.bot_id == bot.id, QuizTest.owner_tg_id == uid), order=(QuizTest.id.desc(),),
                                     page=0, nav_prefix="qz:my", empty="Test o‘chirildi.")
    if act in ("mq", "mqd"):
        if act == "mqd" and len(num) > 1:
            question = await session.get(QuizQuestion, num[1])
            if question and question.test_id == test.id:
                await session.delete(question)
                await session.commit()
                await recount(session, test)
        page = num[1] if act == "mq" and len(num) > 1 else 0
        return await show_questions(tg, callback, uid, session, test, page)


def _safe(title: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
    return (cleaned or "test")[:40]


async def show_manage(tg, callback, chat_id, session, bot, test):
    on, off = "✅", "⬜"
    lines = [f"⚙️ <b>{esc(test.title)}</b>" + (" — qoralama" if test.is_draft else ""),
             f"❓ {test.questions_count} savol · ⏱ {core.fmt_limit(test.time_limit_sec)} · 👥 {test.plays} marta ishlangan"]
    if test.pick_count:
        lines.append(f"🎯 Har urinishda {test.pick_count} ta tasodifiy savol")
    i = test.id
    rows = []
    if test.is_draft:
        rows.append([Btn("✅ E’lon qilish", callback_data=f"qz:done:{i}")])
    rows += [
        [Btn("✏️ Nomi", callback_data=f"qz:me:{i}:title"), Btn("📝 Tavsifi", callback_data=f"qz:me:{i}:desc")],
        [Btn("⏱ Savol vaqti", callback_data=f"qz:me:{i}:time"), Btn("🎯 Tasodifiy N ta", callback_data=f"qz:me:{i}:pick")],
        [Btn(f"{on if test.shuffle_questions else off} Savollarni aralashtirish", callback_data=f"qz:mt:{i}:sq")],
        [Btn(f"{on if test.shuffle_options else off} Variantlarni aralashtirish", callback_data=f"qz:mt:{i}:so")],
        [Btn(f"{on if test.is_public else off} Katalogda ko‘rinsin", callback_data=f"qz:mt:{i}:pub")],
        [Btn("➕ Savol qo‘shish", callback_data=f"qz:ma:{i}"), Btn("🗂 Savollar", callback_data=f"qz:mq:{i}:0")],
        [Btn("📄 TXT yuklab olish", callback_data=f"qz:mx:{i}"), Btn("🏆 Reyting", callback_data=f"qz:top:{i}")],
        [Btn("🗑 O‘chirish", callback_data=f"qz:md:{i}")],
        back(f"qz:t:{i}", "⬅️ Test sahifasi"),
    ]
    await show(tg, callback, chat_id, "\n".join(lines), Markup(rows))


async def show_questions(tg, callback, chat_id, session, test, page: int):
    questions = await core.questions_of(session, test.id)
    per = 6
    pages = max(1, (len(questions) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    chunk = questions[page * per:(page + 1) * per]
    lines = [f"🗂 <b>{esc(test.title)}</b> — savollar ({len(questions)})", ""]
    rows = []
    for n, q in enumerate(chunk, page * per + 1):
        mark = "☑️" if len(q.correct) > 1 else "✅"
        lines.append(f"<b>{n}.</b> {esc(q.text[:90])}{'…' if len(q.text) > 90 else ''}  {mark}{len(q.options)}")
        rows.append([Btn(f"🗑 {n}-savolni o‘chirish", callback_data=f"qz:mqd:{test.id}:{q.id}")])
    if not chunk:
        lines.append("Savol yo‘q.")
    nav = ([Btn("◀️", callback_data=f"qz:mq:{test.id}:{page - 1}")] if page else []) + \
          ([Btn("▶️", callback_data=f"qz:mq:{test.id}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        rows.append(nav)
    rows.append(back(f"qz:m:{test.id}"))
    await show(tg, callback, chat_id, "\n".join(lines), Markup(rows))


async def publish(bot, session, tg, us, test, uid, callback):
    if test.questions_count < 1:
        return await tg.send_message(chat_id=uid, text="❌ Avval kamida bitta savol yuboring.")
    was_draft = test.is_draft
    test.is_draft = False
    await session.commit()
    await core.set_state(session, us)
    link = core.deep_link(bot, test)
    text = (f"{'🎉 <b>Test tayyor!</b>' if was_draft else '✅ Saqlandi.'}\n\n📝 {esc(test.title)} · ❓ {test.questions_count} savol · "
            f"⏱ {core.fmt_limit(test.time_limit_sec)}" + (f"\n\n🔗 Havola: {link}" if link else ""))
    rows = [[Btn("▶️ Sinab ko‘rish", callback_data=f"qz:go:{test.id}"), Btn("⚙️ Boshqarish", callback_data=f"qz:m:{test.id}")]]
    if link:
        from urllib.parse import quote
        rows.append([Btn("📤 Ulashish", url=f"https://t.me/share/url?url={link}&text={quote(test.title, safe='')}")])
    rows.append(back("qz:home", "🏠 Bosh sahifa"))
    await tg.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=Markup(rows),
                          link_preview_options=LinkPreviewOptions(is_disabled=True))


# ------------------------------------------------------------------ free-text steps

def _time_prompt() -> Markup:
    btns = [Btn(core.fmt_limit(s), callback_data=f"qz:tm:{s}") for s in TIME_CHOICES]
    rows = [btns[i:i + 3] for i in range(0, len(btns), 3)]
    rows.append([Btn("✖️ Bekor qilish", callback_data="qz:cancel")])
    return Markup(rows)


def _parse_seconds(text: str) -> int:
    value = text.strip().lower().replace("s", "").strip()
    if not value.isdigit() or not 5 <= int(value) <= 600:
        raise ValueError("Soniyani 5 dan 600 gacha son bilan yozing (masalan 45).")
    return int(value)


async def _create_draft(bot, user, session, tg, us, seconds: int):
    uid = user["id"]
    data = dict(us.state_data or {})
    test = QuizTest(bot_id=bot.id, owner_tg_id=uid, owner_name=core.display_name(user), title=data.get("title", "Test")[:120],
                    description=data.get("desc"), time_limit_sec=seconds, is_draft=True)
    session.add(test)
    await session.commit()
    await core.set_state(session, us, "qz_q", {"test": test.id})
    await ask_questions(tg, uid, test, intro=f"⏱ Har bir savol uchun {core.fmt_limit(seconds)}.\n\n")


async def on_message(bot, message, session, tg, us) -> bool:
    state, data = us.state or "", dict(us.state_data or {})
    user = message["from"]
    uid = user["id"]
    text = (message.get("text") or "").strip()

    async def fail(error):
        await tg.send_message(chat_id=uid, text=f"❌ {error}", parse_mode="HTML")
        return True

    try:
        if state == "qz_title":
            if not text or text.startswith("/"):
                return await fail("Test nomini matn bilan yozing.")
            data["title"] = text[:120]
            await core.set_state(session, us, "qz_desc", data)
            await tg.send_message(chat_id=uid, parse_mode="HTML", text="📝 Qisqa <b>tavsif</b> yozing (mavzu, daraja...). O‘tkazib yuborish: /skip")
            return True
        if state == "qz_desc":
            data["desc"] = None if text == "/skip" else text[:700]
            await core.set_state(session, us, "qz_time", data)
            await tg.send_message(chat_id=uid, parse_mode="HTML", reply_markup=_time_prompt(),
                                  text="⏱ Har bir savolga <b>necha soniya</b> beriladi? Tugmani bosing yoki soniyani yozing (5–600).")
            return True
        if state == "qz_time":
            return await _create_draft(bot, user, session, tg, us, _parse_seconds(text)) or True
        if state == "qz_e":
            test = await managed(session, bot, data.get("id"), uid)
            if test is None:
                await core.set_state(session, us)
                return await fail("Test topilmadi.")
            field = data["field"]
            if field == "title":
                test.title = text[:120]
            elif field == "desc":
                test.description = None if text == "/skip" else text[:700]
            elif field == "time":
                test.time_limit_sec = _parse_seconds(text)
            else:
                if not text.isdigit():
                    return await fail("Son yozing (hammasi uchun 0).")
                test.pick_count = int(text) or None
            await session.commit()
            await core.set_state(session, us)
            await tg.send_message(chat_id=uid, text="✅ Saqlandi.", reply_markup=Markup([back(f"qz:m:{test.id}", "⚙️ Boshqarish")]))
            return True
        if state == "qz_q":
            return await _receive_questions(bot, message, session, tg, us, data, uid, text)
    except ValueError as exc:
        return await fail(exc)
    await core.set_state(session, us)
    return False


async def _receive_questions(bot, message, session, tg, us, data, uid, text) -> bool:
    test = await managed(session, bot, data.get("test"), uid)
    if test is None:
        await core.set_state(session, us)
        await tg.send_message(chat_id=uid, text="Test topilmadi.")
        return True
    if text.lower() in ("/done", "/tayyor"):
        await publish(bot, session, tg, us, test, uid, None)
        return True
    questions: list[Question] = []
    errors: list[str] = []
    if message.get("document"):
        doc = message["document"]
        name = (doc.get("file_name") or "").lower()
        if not (name.endswith(".txt") or doc.get("mime_type") == "text/plain"):
            await tg.send_message(chat_id=uid, text="❌ Faqat .txt fayl qabul qilinadi.")
            return True
        if (doc.get("file_size") or 0) > MAX_FILE_BYTES:
            await tg.send_message(chat_id=uid, text="❌ Fayl juda katta (1 MB gacha).")
            return True
        file = await tg.get_file(doc["file_id"])
        parsed = parse(decode(bytes(await file.download_as_bytearray())))
        questions, errors = parsed.questions, parsed.errors
    elif message.get("poll"):
        poll = message["poll"]
        if poll.get("type") != "quiz" or poll.get("correct_option_id") is None:
            await tg.send_message(chat_id=uid, text="❌ Faqat <b>Quiz</b> turidagi so‘rov qabul qilinadi, uni shu bot bilan chatda o‘zingiz yarating "
                                                     "(📎 → So‘rov → Quiz va to‘g‘ri javobni belgilang). Boshqa joydan forward qilingan so‘rovda "
                                                     "Telegram to‘g‘ri javobni bermaydi.", parse_mode="HTML")
            return True
        q = Question(text=poll["question"], options=[o["text"] if isinstance(o, dict) else str(o) for o in poll["options"]],
                     correct=[poll["correct_option_id"]], explanation=poll.get("explanation"), line=1)
        problem = validate(q)
        questions, errors = ([q], []) if not problem else ([], [problem])
    elif text:
        if "#" not in text:
            await tg.send_message(chat_id=uid, text="❓ Savol topilmadi. Har savol # bilan boshlanishi kerak.\n\n" + FORMAT_HELP, parse_mode="HTML")
            return True
        parsed = parse(text)
        questions, errors = parsed.questions, parsed.errors
    else:
        await tg.send_message(chat_id=uid, text="Fayl, matn yoki Quiz so‘rovi yuboring.")
        return True
    added, skipped = await add_questions(session, test, questions) if questions else (0, 0)
    lines = [f"✅ <b>{added}</b> ta savol qo‘shildi. Jami: <b>{test.questions_count}</b>."] if added else ["😕 Hech qanday savol qo‘shilmadi."]
    if skipped:
        lines.append(f"⚠️ Testda {MAX_QUESTIONS} tadan ortiq savol bo‘lmaydi: {skipped} tasi qo‘shilmadi.")
    if errors:
        lines.append(f"\n⚠️ <b>{len(errors)} ta muammo:</b>")
        lines += [f"• {esc(e)}" for e in errors[:8]]
        if len(errors) > 8:
            lines.append(f"…va yana {len(errors) - 8} ta")
    lines.append("\nYana yuborishingiz yoki «✅ Tayyor» ni bosishingiz mumkin.")
    await tg.send_message(chat_id=uid, text="\n".join(lines), parse_mode="HTML", reply_markup=questions_markup(test))
    return True
