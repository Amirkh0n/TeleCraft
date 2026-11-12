import pytest
from sqlalchemy import select

from engine import quiz as core
from helpers import OWNER, USER, send
from helpers import message as _message
from models.admin_links import AdminLink
from models.quiz import QuizAttempt, QuizPoll, QuizQuestion, QuizSettings, QuizTest

USER2 = 888


def message(text=None, *, user=USER, **extra):
    return _message(text, user=user, **extra)


def cb(data, user=USER, mid=9):
    return {"update_id": None, "callback_query": {
        "id": "c", "from": {"id": user, "first_name": "Ali"}, "data": data,
        "message": {"message_id": mid, "chat": {"id": user, "type": "private"}},
    }}


def vote(poll_id, option_ids, user=USER):
    return {"update_id": None, "poll_answer": {"poll_id": poll_id, "user": {"id": user, "first_name": "Ali"}, "option_ids": option_ids}}


class Factory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return False


async def no_sleep(_):
    return None


def screen(env):
    return env.tg.calls[-1][1]


def datas(env):
    kb = screen(env).get("reply_markup")
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data] if kb and hasattr(kb, "inline_keyboard") else []


async def press(env, data, user=USER):
    await send(env, cb(data, user))


def polls(env):
    return env.tg.of("send_poll")


def poll_id(env):
    return f"poll{len(polls(env))}"


async def answer(env, options, user=USER):
    await send(env, vote(poll_id(env), options, user))


async def correct(env, user=USER):
    """Answer the newest quiz poll correctly (uses the shuffled position the bot reports)."""
    await answer(env, [polls(env)[-1]["correct_option_id"]], user)


async def row(env, model, **where):
    q = select(model).execution_options(populate_existing=True)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return list((await env.session.execute(q)).scalars().all())


@pytest.fixture
async def qz(env, monkeypatch):
    env.scheduled = []
    monkeypatch.setattr(core, "schedule_expiry", lambda pid, delay: env.scheduled.append((pid, delay)))
    env.bot.kind = "quiz"
    env.bot.username = "quizbot"
    await env.session.commit()
    await core.ensure_setup(env.session, env.bot)
    return env


async def make_test(env, owner=USER, n=3, multi_at=None, **kw):
    opts = dict(shuffle_questions=False, shuffle_options=False, time_limit_sec=30)
    opts.update(kw)
    test = QuizTest(bot_id=env.bot.id, owner_tg_id=owner, owner_name="Muallif", title=kw.pop("title", "Matematika"), **{k: v for k, v in opts.items() if k != "title"})
    env.session.add(test)
    await env.session.commit()
    for i in range(n):
        multi = multi_at == i
        env.session.add(QuizQuestion(test_id=test.id, position=i, text=f"Savol {i}?", options=["a", "b", "c"] if not multi else ["a", "b", "c", "d"],
                                     correct=[0] if not multi else [0, 2], explanation=f"Izoh {i}" if i == 0 else None))
    test.questions_count = n
    await env.session.commit()
    return test


# ---------------------------------------------------------------- creating tests

async def create_via_bot(env, user=USER, text="#Q1\n+a\n-b\n\n#Q2\n-x\n+y\n-z"):
    await send(env, message("/start", user=user))
    await press(env, "qz:new", user)
    await send(env, message("Mening testim", user=user))
    await send(env, message("Tavsif bor", user=user))
    await press(env, "qz:tm:45", user)
    await send(env, message(text, user=user))


async def test_any_user_creates_test_from_pasted_text(qz):
    await create_via_bot(qz)
    [test] = await row(qz, QuizTest)
    assert (test.owner_tg_id, test.title, test.description, test.time_limit_sec, test.is_draft, test.questions_count) == (USER, "Mening testim", "Tavsif bor", 45, True, 2)
    assert "2</b> ta savol qo‘shildi" in screen(qz)["text"]
    test_id = test.id
    await press(qz, f"qz:done:{test_id}")
    test = (await row(qz, QuizTest))[0]
    assert test.is_draft is False and "t" + str(test_id) in screen(qz)["text"]
    qs = await row(qz, QuizQuestion, test_id=test_id)
    assert [q.correct for q in qs] == [[0], [1]]


async def test_questions_from_txt_file_and_reports_problems(qz):
    qz.tg.files = {"f1": "﻿#Yaxshi\n+a\n-b\n\n#Yomon\n+a\n\n#Yana\n-a\n+b\n".encode("utf-8")}
    await create_via_bot(qz, text="#Birinchi\n+a\n-b")
    await send(qz, message(document={"file_id": "f1", "file_name": "savollar.txt", "file_size": 100}))
    text = screen(qz)["text"]
    assert "2</b> ta savol qo‘shildi" in text and "1 ta muammo" in text and "kamida 2" in text and "Jami: <b>3</b>" in text
    await send(qz, message(document={"file_id": "f2", "file_name": "rasm.png"}))
    assert ".txt" in screen(qz)["text"]
    await send(qz, message(document={"file_id": "f3", "file_name": "big.txt", "file_size": 5_000_000}))
    assert "katta" in screen(qz)["text"]


async def test_quiz_poll_becomes_a_question_and_regular_poll_is_rejected(qz):
    await create_via_bot(qz, text="#Birinchi\n+a\n-b")
    poll = {"type": "quiz", "question": "2+2?", "options": [{"text": "3"}, {"text": "4"}], "correct_option_id": 1, "explanation": "oddiy"}
    await send(qz, message(poll=poll))
    q = (await row(qz, QuizQuestion))[-1]
    assert (q.text, q.options, q.correct, q.explanation) == ("2+2?", ["3", "4"], [1], "oddiy")
    await send(qz, message(poll={"type": "regular", "question": "x", "options": [{"text": "a"}, {"text": "b"}]}))
    assert "Quiz" in screen(qz)["text"] and len(await row(qz, QuizQuestion)) == 2


async def test_creation_cannot_finish_empty_and_cancel_deletes_draft(qz):
    await send(qz, message("/start"))
    await press(qz, "qz:new")
    await send(qz, message("Bo'sh"))
    await send(qz, message("/skip"))
    await send(qz, message("abc"))
    assert "Soniyani" in screen(qz)["text"]
    await send(qz, message("20"))
    [t] = await row(qz, QuizTest)
    await press(qz, f"qz:done:{t.id}")
    assert "kamida bitta" in screen(qz)["text"]
    await press(qz, "qz:cancel")
    assert await row(qz, QuizTest) == []


async def test_text_without_questions_gets_format_help(qz):
    await create_via_bot(qz, text="#Bitta\n+a\n-b")
    await send(qz, message("salom"))
    assert "# bilan" in screen(qz)["text"]


async def test_template_and_ai_prompt_are_sent(qz):
    await create_via_bot(qz, text="#Bitta\n+a\n-b")
    await press(qz, "qz:tpl")
    doc = qz.tg.of("send_document")[-1]
    assert doc["filename"] == "namuna.txt" and b"#Poytaxt" in doc["document"]
    await press(qz, "qz:ai")
    assert "{mavzu}" in screen(qz)["text"]


async def test_creation_policy_and_quota(qz):
    st = await core.get_settings(qz.session, qz.bot.id)
    st.who_can_create = "admins"
    await qz.session.commit()
    await send(qz, message("/start"))
    assert "qz:new" not in datas(qz)  # button hidden
    await press(qz, "qz:new")
    assert "faqat adminlarga" in screen(qz)["text"]
    await press(qz, "qz:new", OWNER)  # owner is an admin
    assert "Yangi test" in screen(qz)["text"]
    st.who_can_create, st.max_tests_per_user = "everyone", 1
    await qz.session.commit()
    await make_test(qz)
    await press(qz, "qz:new")
    assert "1 tagacha" in screen(qz)["text"]


# ---------------------------------------------------------------- playing

async def test_full_attempt_scoring_feedback_and_result(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    first = polls(qz)[0]
    assert first["type"] == "quiz" and first["open_period"] == 30 and first["is_anonymous"] is False
    assert first["question"].startswith("1/3. Savol 0?") and first["explanation"] == "Izoh 0"
    assert qz.scheduled[-1] == ("poll1", 32)
    await correct(qz)
    await answer(qz, [1])  # wrong on the 2nd question
    assert len(polls(qz)) == 3
    await correct(qz)
    final = screen(qz)
    assert "2/3" in final["text"] and "67%" in final["text"] and "1-o‘rin" in final["text"]
    [a] = await row(qz, QuizAttempt)
    assert (a.status, a.score, a.total, [x["ok"] for x in a.answers]) == ("finished", 2, 3, [True, False, True])
    assert (await row(qz, QuizTest))[0].plays == 1
    assert any(d.startswith("qz:rev:") for d in datas(qz))
    await press(qz, f"qz:rev:{a.id}")
    review = qz.tg.of("send_message")[-1]["text"]
    assert "Savol 1?" in review and "Sizniki: <b>" not in review and "✅ To‘g‘ri: <b>a</b>" in review and "Savol 0?" not in review


async def test_shuffled_options_are_graded_by_original_meaning(qz):
    test = await make_test(qz, n=1, shuffle_options=True)
    for _ in range(5):  # shuffling is random: every layout must grade the same way
        await press(qz, f"qz:go:{test.id}")
        sent = polls(qz)[-1]
        assert sorted(sent["options"]) == ["a", "b", "c"] and sent["options"][sent["correct_option_id"]] == "a"
        await correct(qz)
        assert (await row(qz, QuizAttempt))[-1].score == 1


async def test_multi_answer_question_is_a_regular_poll_with_feedback(qz):
    test = await make_test(qz, n=2, multi_at=0)
    await press(qz, f"qz:go:{test.id}")
    first = polls(qz)[0]
    assert first["type"] == "regular" and first["allows_multiple_answers"] is True and "correct_option_id" not in first
    await answer(qz, [0, 2])
    assert "✅ To‘g‘ri" in qz.tg.of("send_message")[-1]["text"]
    assert qz.tg.of("stop_poll")
    await send(qz, vote("poll2", [1]))
    [a] = await row(qz, QuizAttempt)
    assert a.score == 1 and a.answers[0]["ok"] is True
    await press(qz, f"qz:go:{test.id}")
    await answer(qz, [0])  # partial selection is wrong
    assert "Noto‘g‘ri" in qz.tg.of("send_message")[-1]["text"] and "<b>a, c</b>" in qz.tg.of("send_message")[-1]["text"]


async def test_stale_foreign_and_retracted_votes_are_ignored(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    pid = poll_id(qz)
    await send(qz, vote(pid, [], USER))  # retracted
    await send(qz, vote(pid, [0], USER2))  # someone else's poll
    await send(qz, vote("nope", [0]))
    assert len(polls(qz)) == 1
    await send(qz, vote(pid, [0]))
    await send(qz, vote(pid, [0]))  # duplicate delivery
    assert len(polls(qz)) == 2 and (await row(qz, QuizAttempt))[0].score == 1


async def test_timeout_marks_missed_and_moves_on(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    await core.expire_poll("poll1", session_factory=Factory(qz.session), client_for=lambda b: _ret(qz.tg), sleep=no_sleep)
    assert len(polls(qz)) == 2
    [a] = await row(qz, QuizAttempt)
    assert a.answers[0]["ok"] is None and a.missed_streak == 1 and a.current == 1
    await core.expire_poll("poll1", session_factory=Factory(qz.session), client_for=lambda b: _ret(qz.tg), sleep=no_sleep)  # again: no-op
    assert len(polls(qz)) == 2


async def _ret(value):
    return value


async def expire(env, pid):
    await core.expire_poll(pid, session_factory=Factory(env.session), client_for=lambda b: _ret(env.tg), sleep=no_sleep)


async def test_answer_after_timeout_is_ignored(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    await expire(qz, "poll1")
    await send(qz, vote("poll1", [0]))
    assert (await row(qz, QuizAttempt))[0].score == 0 and len(polls(qz)) == 2


async def test_two_missed_in_a_row_pause_the_test_and_it_can_resume(qz):
    test = await make_test(qz, n=4)
    await press(qz, f"qz:go:{test.id}")
    await expire(qz, "poll1")
    await expire(qz, "poll2")
    [a] = await row(qz, QuizAttempt)
    assert a.status == "abandoned" and len(polls(qz)) == 2 and f"qz:resume:{a.id}" in datas(qz)
    await press(qz, f"qz:resume:{a.id}")
    assert len(polls(qz)) == 3 and (await row(qz, QuizAttempt))[0].status == "active"
    await correct(qz)
    await expire(qz, "poll4")
    assert (await row(qz, QuizAttempt))[0].status == "finished"  # last question timed out: finished normally
    assert "1/4" in screen(qz)["text"]


async def test_answering_resets_the_missed_streak(qz):
    test = await make_test(qz, n=4)
    await press(qz, f"qz:go:{test.id}")
    await expire(qz, "poll1")
    await correct(qz)
    await expire(qz, "poll3")
    assert (await row(qz, QuizAttempt))[0].status == "active"


async def test_new_attempt_replaces_a_running_one(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    await press(qz, f"qz:go:{test.id}")
    statuses = sorted(a.status for a in await row(qz, QuizAttempt))
    assert statuses == ["abandoned", "active"]
    await send(qz, vote("poll1", [0]))  # the old poll no longer counts
    assert (await row(qz, QuizAttempt))[0].score == 0


async def test_stop_command(qz):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    await send(qz, message("/stop"))
    assert (await row(qz, QuizAttempt))[0].status == "abandoned" and "to‘xtatildi" in screen(qz)["text"]
    await send(qz, message("/stop"))
    assert "yo‘q" in screen(qz)["text"]


async def test_long_question_and_options_use_letters(qz):
    test = await make_test(qz, n=1)
    q = (await row(qz, QuizQuestion))[0]
    q.text, q.options, q.correct = "x" * 350, ["to‘g‘ri " * 20, "<b>b</b>"], [1]
    await qz.session.commit()
    await press(qz, f"qz:go:{test.id}")
    poll = polls(qz)[0]
    assert poll["options"] == ["A", "B"] and poll["question"] == "Javobni tanlang"
    pre = qz.tg.of("send_message")[-1]
    assert "&lt;b&gt;b&lt;/b&gt;" in pre["text"] and pre["parse_mode"] == "HTML"


async def test_pick_count_gives_a_random_subset(qz):
    test = await make_test(qz, n=6, pick_count=2)
    await press(qz, f"qz:go:{test.id}")
    [a] = await row(qz, QuizAttempt)
    assert a.total == 2 and len(set(a.order)) == 2


async def test_leaderboard_is_best_per_user_by_score_then_time(qz):
    test = await make_test(qz)
    for uid, name, score, secs in ((USER, "Ali", 2, 50), (USER, "Ali", 3, 90), (USER2, "Vali", 3, 40), (999, "Gani", 1, 10)):
        qz.session.add(QuizAttempt(bot_id=qz.bot.id, test_id=test.id, tg_user_id=uid, user_name=name, status="finished",
                                   order=[], total=3, score=score, time_spent_sec=secs, answers=[]))
    await qz.session.commit()
    board = await core.leaderboard(qz.session, test.id)
    assert [(r.user_name, r.score, r.time_spent_sec) for r in board] == [("Vali", 3, 40), ("Ali", 3, 90), ("Gani", 1, 10)]
    await press(qz, f"qz:top:{test.id}")
    text = screen(qz)["text"]
    assert text.index("Vali") < text.index("Ali") < text.index("Gani") and "🥇" in text


async def test_resume_pending_rearms_open_polls_only(qz, monkeypatch):
    test = await make_test(qz)
    await press(qz, f"qz:go:{test.id}")
    qz.scheduled.clear()
    assert await core.resume_pending(session_factory=Factory(qz.session)) == 1
    pid, delay = qz.scheduled[0]
    assert pid == "poll1" and 0 < delay <= 32
    await correct(qz)
    qz.scheduled.clear()
    # the answered poll is closed; the new one is open
    assert await core.resume_pending(session_factory=Factory(qz.session)) == 1 and qz.scheduled[0][0] == "poll2"


# ---------------------------------------------------------------- catalog, links, management

async def test_catalog_lists_only_public_active_published_tests_and_searches(qz):
    shown = await make_test(qz, title="Algebra")
    await make_test(qz, title="Yashirin", is_public=False)
    await make_test(qz, title="Qoralama", is_draft=True)
    await make_test(qz, title="Bloklangan", is_active=False)
    await make_test(qz, title="Bo'sh", n=0)
    await press(qz, "qz:cat:p:0")
    assert datas(qz).count(f"qz:t:{shown.id}") == 1 and len([d for d in datas(qz) if d.startswith("qz:t:")]) == 1
    await send(qz, message("alge"))  # typing anywhere searches
    assert f"qz:t:{shown.id}" in datas(qz)
    await send(qz, message("zzzz"))
    assert "topilmadi" in screen(qz)["text"]
    await press(qz, "qz:find")
    await send(qz, message("algebra"))
    assert f"qz:t:{shown.id}" in datas(qz)


async def test_deep_link_opens_test_card_and_hides_drafts_from_strangers(qz):
    test = await make_test(qz)
    draft = await make_test(qz, is_draft=True)
    await send(qz, message(f"/start t{test.id}", user=USER2))
    assert "Matematika" in screen(qz)["text"] and f"qz:go:{test.id}" in datas(qz)
    await send(qz, message(f"/start t{draft.id}", user=USER2))
    assert "Test botiga xush kelibsiz" in screen(qz)["text"]
    await send(qz, message(f"/start t{draft.id}", user=USER))  # the owner sees it
    assert "qoralama" in screen(qz)["text"]


async def test_owner_manages_test_and_strangers_cannot(qz):
    test = await make_test(qz)
    tid = test.id
    await press(qz, f"qz:m:{tid}", USER2)
    assert "ruxsat yo‘q" in screen(qz)["text"]
    for field, value, attr, expected in (("title", "Yangi nom", "title", "Yangi nom"), ("time", "90", "time_limit_sec", 90),
                                         ("pick", "2", "pick_count", 2), ("desc", "Yangi tavsif", "description", "Yangi tavsif")):
        await press(qz, f"qz:me:{tid}:{field}")
        await send(qz, message(value))
        assert getattr((await row(qz, QuizTest))[0], attr) == expected
    await press(qz, f"qz:me:{tid}:time")
    await send(qz, message("2"))
    assert "Soniyani" in screen(qz)["text"] and (await row(qz, QuizTest))[0].time_limit_sec == 90
    await press(qz, f"qz:mt:{tid}:sq")
    await press(qz, f"qz:mt:{tid}:pub")
    t = (await row(qz, QuizTest))[0]
    assert t.shuffle_questions is True and t.is_public is False


async def test_delete_question_export_and_add_more(qz):
    test = await make_test(qz)
    tid = test.id
    qs = await row(qz, QuizQuestion, test_id=tid)
    await press(qz, f"qz:mqd:{tid}:{qs[0].id}")
    assert (await row(qz, QuizTest))[0].questions_count == 2
    await press(qz, f"qz:mx:{tid}")
    doc = qz.tg.of("send_document")[-1]
    assert doc["filename"].endswith(".txt") and doc["document"].decode().startswith("#Savol 1?")
    await press(qz, f"qz:ma:{tid}")
    await send(qz, message("#Yangi savol\n+ha\n-yo'q"))
    assert (await row(qz, QuizTest))[0].questions_count == 3


async def test_delete_test_removes_everything(qz):
    test = await make_test(qz)
    tid = test.id
    await press(qz, f"qz:go:{tid}")
    await correct(qz)
    await press(qz, f"qz:md:{tid}")
    assert await row(qz, QuizTest)  # asks for confirmation first
    await press(qz, f"qz:mdy:{tid}")
    assert not await row(qz, QuizTest) and not await row(qz, QuizQuestion) and not await row(qz, QuizAttempt) and not await row(qz, QuizPoll)


async def test_my_tests_and_results_screens(qz):
    mine = await make_test(qz, title="Meniki")
    await make_test(qz, owner=USER2, title="Boshqaniki")
    await press(qz, "qz:my:0")
    assert datas(qz).count(f"qz:t:{mine.id}") == 1 and len([d for d in datas(qz) if d.startswith("qz:t:")]) == 1
    await press(qz, "qz:res")
    assert "Hali birorta" in screen(qz)["text"]
    await press(qz, f"qz:go:{mine.id}")
    for _ in range(3):
        await correct(qz)
    await press(qz, "qz:res")
    assert "Meniki" in screen(qz)["text"] and "3/3" in screen(qz)["text"]


# ---------------------------------------------------------------- admin

async def test_admin_hides_tests_and_sees_stats(qz):
    test = await make_test(qz)
    tid = test.id
    qz.session.add(AdminLink(bot_id=qz.bot.id, admin_tg_id=55))
    await qz.session.commit()
    await send(qz, message("/admin", user=55))
    assert "admin paneli" in screen(qz)["text"]
    await press(qz, f"qa:tog:{tid}:0:0", 55)
    assert (await row(qz, QuizTest))[0].is_active is False
    await press(qz, "qz:cat:p:0", USER2)
    assert f"qz:t:{tid}" not in datas(qz)
    await press(qz, f"qa:tog:{tid}:1:0", 55)
    assert (await row(qz, QuizTest))[0].is_active is True
    await press(qz, f"qz:go:{tid}", USER2)
    await press(qz, "qa:stats", 55)
    assert "Statistika" in screen(qz)["text"] and "Matematika" in screen(qz)["text"]
    await press(qz, f"qz:m:{tid}", 55)  # admins manage any test
    assert "Matematika" in screen(qz)["text"] and "qz:md:" + str(tid) in datas(qz)


async def test_admin_settings_toggle_and_non_admin_is_blocked(qz):
    await press(qz, "qa:who")  # a regular user cannot
    assert (await core.get_settings(qz.session, qz.bot.id)).who_can_create == "everyone"
    await send(qz, message("/admin"))
    assert not any("admin paneli" in (c[1].get("text") or "") for c in qz.tg.calls)
    await press(qz, "qa:who", OWNER)
    await press(qz, "qa:lim", OWNER)
    st = (await row(qz, QuizSettings))[0]
    assert st.who_can_create == "admins" and st.max_tests_per_user == 100


async def test_callbacks_are_acknowledged_for_every_bot_kind(env):
    env.bot.kind = "cinema"
    await env.session.commit()
    await send(env, cb("cm:home", OWNER))
    assert env.tg.of("answer_callback_query")
