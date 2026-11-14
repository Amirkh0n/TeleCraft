from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from telegram.error import BadRequest

from engine import quiz_group as qg
from helpers import OWNER, USER, send
from models.admin_links import AdminLink
from models.audience import BotUser
from models.quiz import GAME_FINISHED, GAME_RUNNING, GAME_STOPPED, QuizGame, QuizGameAnswer, QuizQuestion, QuizTest

USER2, USER3 = 888, 999
GROUP = -100500
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def gmsg(text, user=USER, chat=GROUP, ctype="supergroup", name="Ali"):
    return {"update_id": None, "message": {"chat": {"id": chat, "type": ctype, "title": "Guruh"},
                                           "from": {"id": user, "first_name": name}, "text": text}}


def gcb(data, user=USER, chat=GROUP, ctype="supergroup", mid=9):
    return {"update_id": None, "callback_query": {
        "id": "c", "from": {"id": user, "first_name": "Ali"}, "data": data,
        "message": {"message_id": mid, "chat": {"id": chat, "type": ctype}}}}


def vote(poll, options, user=USER, name="Ali"):
    return {"update_id": None, "poll_answer": {"poll_id": poll, "user": {"id": user, "first_name": name}, "option_ids": options}}


class Factory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return False


class Clock:
    now = T0

    def set(self, seconds):
        self.now = T0 + timedelta(seconds=seconds)


async def no_sleep(_):
    return None


async def row(env, model, **where):
    q = select(model).execution_options(populate_existing=True)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return list((await env.session.execute(q)).scalars().all())


def texts(env, chat=GROUP):
    return [kw["text"] for kw in env.tg.of("send_message") if kw["chat_id"] == chat]


def datas(call):
    kb = call.get("reply_markup")
    return [b.callback_data for r in kb.inline_keyboard for b in r if b.callback_data] if kb and hasattr(kb, "inline_keyboard") else []


@pytest.fixture
async def gq(env, monkeypatch):
    env.bot.kind = "quiz"
    env.bot.username = "quizbot"
    await env.session.commit()
    env.scheduled = []
    monkeypatch.setattr(qg, "schedule_game", lambda gid, **kw: env.scheduled.append(gid))
    env.clock = Clock()
    monkeypatch.setattr(qg, "utcnow", lambda: env.clock.now)

    async def client_for(bot):
        return env.tg
    env.cf, env.factory = client_for, Factory(env.session)
    return env


async def make_test(env, n=3, multi_at=None, **kw):
    opts = dict(shuffle_questions=False, shuffle_options=False, time_limit_sec=30, is_public=True, title="Matematika")
    opts.update(kw)
    test = QuizTest(bot_id=env.bot.id, owner_tg_id=USER, owner_name="Muallif", **opts)
    env.session.add(test)
    await env.session.commit()
    for i in range(n):
        multi = multi_at == i
        env.session.add(QuizQuestion(test_id=test.id, position=i, text=f"Savol {i}?", options=["a", "b", "c", "d"] if multi else ["a", "b", "c"],
                                     correct=[0, 2] if multi else [0], explanation="Izoh" if i == 0 else None))
    test.questions_count = n
    await env.session.commit()
    return test


async def start_game(env, test, user=USER):
    await send(env, gcb(f"qg:go:{test.id}", user))
    [game] = await row(env, QuizGame)
    return game


async def ask(env, game):
    return await qg._send_next(game.id, env.factory, env.cf)


async def close(env, game):
    return await qg._close_question(game.id, env.factory, env.cf)


def poll_no(env):
    return f"poll{len(env.tg.of('send_poll'))}"


# ------------------------------------------------------------------ choosing

async def test_list_shows_only_public_active_ready_tests(gq):
    await make_test(gq, title="Ochiq")
    await make_test(gq, title="Yopiq", is_public=False)
    await make_test(gq, title="Yashirin", is_active=False)
    await make_test(gq, title="Qoralama", is_draft=True)
    await send(gq, gmsg("/test"))
    call = gq.tg.of("send_message")[-1]
    buttons = str(call["reply_markup"])
    assert "Ochiq" in buttons and "Yopiq" not in buttons and "Yashirin" not in buttons and "Qoralama" not in buttons
    assert not await row(gq, BotUser)  # group members are not bot users


async def test_command_addressed_to_other_bot_is_ignored(gq):
    await make_test(gq)
    await send(gq, gmsg("/test@otherbot"))
    assert not gq.tg.calls
    await send(gq, gmsg("/test@QuizBot"))
    assert gq.tg.of("send_message")


async def test_test_by_number_search_and_missing(gq):
    t = await make_test(gq, title="Tarix")
    await send(gq, gmsg(f"/test {t.id}"))
    assert "Tarix" in gq.tg.of("send_message")[-1]["text"] and f"qg:go:{t.id}" in datas(gq.tg.of("send_message")[-1])
    await send(gq, gmsg("/test tar"))
    assert f"qg:t:{t.id}" in datas(gq.tg.of("send_message")[-1])
    await send(gq, gmsg("/test 99999"))
    assert "topilmadi" in texts(gq)[-1]


async def test_private_test_only_for_its_owner_or_admin(gq):
    t = await make_test(gq, is_public=False)
    await send(gq, gmsg(f"/test {t.id}", user=USER2))
    assert "topilmadi" in texts(gq)[-1]
    await send(gq, gmsg(f"/test {t.id}", user=USER))  # owner
    assert "Matematika" in gq.tg.of("send_message")[-1]["text"]


async def test_help_in_group(gq):
    await send(gq, gmsg("/start@quizbot"))
    assert "/stoptest" in texts(gq)[-1] and "test@quizbot" in texts(gq)[-1]


async def test_callbacks_in_private_chat_are_ignored(gq):
    t = await make_test(gq)
    await send(gq, gcb(f"qg:go:{t.id}", chat=USER, ctype="private"))
    assert not await row(gq, QuizGame)


# ------------------------------------------------------------------ starting

async def test_go_creates_one_game_and_schedules_runner(gq):
    t = await make_test(gq, n=4, pick_count=2)
    game = await start_game(gq, t)
    assert (game.total, game.status, game.starter_id, game.limit_sec, game.chat_id) == (2, GAME_RUNNING, USER, 30, GROUP)
    assert gq.scheduled == [game.id]
    assert "qg:stop" in datas(gq.tg.of("edit_message_text")[-1]) or "qg:stop" in datas(gq.tg.calls[-1][1])
    await send(gq, gcb(f"qg:go:{t.id}", USER2))
    assert len(await row(gq, QuizGame)) == 1 and "allaqachon" in texts(gq)[-1]
    await send(gq, gmsg("/test"))
    assert "Hozir" in texts(gq)[-1]


async def test_other_chat_can_play_at_the_same_time(gq):
    t = await make_test(gq)
    await send(gq, gcb(f"qg:go:{t.id}", chat=GROUP))
    await send(gq, gcb(f"qg:go:{t.id}", chat=-777))
    assert len(await row(gq, QuizGame)) == 2


# ------------------------------------------------------------------ playing

async def test_scoring_speed_ranking_and_final_board(gq):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)
    gq.clock.set(0)
    state, deadline = await ask(gq, game)
    assert state == "open"
    poll = gq.tg.of("send_poll")[-1]
    assert poll["chat_id"] == GROUP and poll["is_anonymous"] is False and poll["type"] == "quiz" and poll["open_period"] == 30
    assert poll["question"].startswith("1/2.")
    gq.clock.set(3)
    await send(gq, vote(poll_no(gq), [poll["correct_option_id"]], USER, "Ali"))
    gq.clock.set(10)
    await send(gq, vote(poll_no(gq), [poll["correct_option_id"]], USER2, "Vali"))
    gq.clock.set(12)
    wrong = (poll["correct_option_id"] + 1) % 3
    await send(gq, vote(poll_no(gq), [wrong], USER3, "Soli"))
    gq.clock.set(31)
    assert await close(gq, game) == "continue"
    summary = texts(gq)[-1]
    assert "To‘g‘ri javob" in summary and "Izoh" in summary and "Javob berdi: 3 · to‘g‘ri: 2" in summary
    assert summary.index("Ali") < summary.index("Vali")
    pts = {a.tg_user_id: a.points for a in await row(gq, QuizGameAnswer)}
    assert pts == {USER: 1450, USER2: 1333, USER3: 0}
    # question 2: only Vali answers
    gq.clock.set(40)
    await ask(gq, game)
    poll2 = gq.tg.of("send_poll")[-1]
    gq.clock.set(41)
    await send(gq, vote(poll_no(gq), [poll2["correct_option_id"]], USER2, "Vali"))
    gq.clock.set(71)
    await close(gq, game)
    gq.clock.set(80)
    assert (await ask(gq, game))[0] == "finished"
    final = texts(gq)[-1]
    assert "yakuniy" in final and final.index("Vali") < final.index("Ali") < final.index("Soli")
    assert "🥇 Vali" in final and "Qatnashchilar: 3" in final
    game = (await row(gq, QuizGame))[0]
    assert game.status == GAME_FINISHED and (await row(gq, QuizTest))[0].plays == 1


async def test_one_answer_per_question_and_retract_ignored(gq):
    t = await make_test(gq, n=1)
    game = await start_game(gq, t)
    await ask(gq, game)
    right = gq.tg.of("send_poll")[-1]["correct_option_id"]
    wrong = (right + 1) % 3
    await send(gq, vote(poll_no(gq), [], USER))  # retracted
    assert not await row(gq, QuizGameAnswer)
    await send(gq, vote(poll_no(gq), [wrong], USER))
    await send(gq, vote(poll_no(gq), [right], USER))  # changing the vote does not help
    [a] = await row(gq, QuizGameAnswer)
    assert a.ok is False and a.points == 0


async def test_late_votes_are_ignored(gq):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)
    gq.clock.set(0)
    await ask(gq, game)
    right = gq.tg.of("send_poll")[-1]["correct_option_id"]
    gq.clock.set(30 + qg.ANSWER_GRACE + 1)
    await send(gq, vote(poll_no(gq), [right], USER))  # after the deadline
    assert not await row(gq, QuizGameAnswer)
    await close(gq, game)
    await send(gq, vote("poll1", [right], USER2))  # after the question was closed
    assert not await row(gq, QuizGameAnswer)


async def test_multi_answer_question_is_all_or_nothing(gq):
    t = await make_test(gq, n=1, multi_at=0)
    game = await start_game(gq, t)
    await ask(gq, game)
    poll = gq.tg.of("send_poll")[-1]
    assert poll["type"] == "regular" and poll["allows_multiple_answers"] is True
    await send(gq, vote(poll_no(gq), [0, 2], USER))
    await send(gq, vote(poll_no(gq), [0], USER2))
    by_user = {a.tg_user_id: a.ok for a in await row(gq, QuizGameAnswer)}
    assert by_user == {USER: True, USER2: False}


async def test_shuffled_options_are_graded_by_original_index(gq):
    t = await make_test(gq, n=1, shuffle_options=True)
    game = await start_game(gq, t)
    for _ in range(1):
        await ask(gq, game)
    poll = gq.tg.of("send_poll")[-1]
    await send(gq, vote(poll_no(gq), [poll["correct_option_id"]], USER))
    assert (await row(gq, QuizGameAnswer))[0].ok is True


async def test_nobody_answers_stops_after_three_questions(gq):
    t = await make_test(gq, n=6)
    game = await start_game(gq, t)
    clock = gq.clock

    async def sleep(delay):
        clock.now += timedelta(seconds=delay)
    await qg.run_game(game.id, session_factory=gq.factory, client_for=gq.cf, sleep=sleep)
    game = (await row(gq, QuizGame))[0]
    assert game.status == GAME_STOPPED and len(gq.tg.of("send_poll")) == 3
    assert "ketma-ket javobsiz" in texts(gq)[-1]


async def test_run_game_plays_to_the_end(gq):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)
    clock = gq.clock

    async def sleep(delay):
        if gq.tg.of("send_poll") and len(await row(gq, QuizGameAnswer)) < len(gq.tg.of("send_poll")):
            poll = gq.tg.of("send_poll")[-1]
            await send(gq, vote(poll_no(gq), [poll["correct_option_id"]], USER, "Ali"))
        clock.now += timedelta(seconds=delay)
    await qg.run_game(game.id, session_factory=gq.factory, client_for=gq.cf, sleep=sleep)
    game = (await row(gq, QuizGame))[0]
    assert game.status == GAME_FINISHED and len(gq.tg.of("send_poll")) == 2
    assert "yakuniy" in texts(gq)[-1] and "Ali" in texts(gq)[-1]


async def test_nobody_played_message(gq):
    t = await make_test(gq, n=1)
    game = await start_game(gq, t)
    await ask(gq, game)
    gq.clock.set(40)
    await close(gq, game)
    await ask(gq, game)
    assert "Hech kim qatnashmadi" in texts(gq)[-1]


async def test_poll_failure_stops_game_quietly(gq, monkeypatch):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)

    async def boom(**kw):
        raise BadRequest("not enough rights to send polls")
    monkeypatch.setattr(gq.tg, "send_poll", boom, raising=False)
    assert (await ask(gq, game))[0] == "error"
    assert (await row(gq, QuizGame))[0].status == GAME_STOPPED


async def test_deleted_question_is_skipped(gq):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)
    q0 = (await row(gq, QuizQuestion, test_id=t.id))
    first = game.order[0]
    await gq.session.delete(await gq.session.get(QuizQuestion, first))
    await gq.session.commit()
    await ask(gq, game)
    assert gq.tg.of("send_poll")[-1]["question"].startswith("2/2.")


# ------------------------------------------------------------------ stopping & resuming

async def test_stop_permissions(gq):
    t = await make_test(gq, n=2)
    game = await start_game(gq, t)
    await ask(gq, game)
    await send(gq, gmsg("/stoptest", user=USER2))
    assert "faqat" in texts(gq)[-1] and (await row(gq, QuizGame))[0].status == GAME_RUNNING
    await send(gq, gcb("qg:stop", USER2))
    assert (await row(gq, QuizGame))[0].status == GAME_RUNNING
    gq.tg.chat_admins = {USER3}
    await send(gq, gmsg("/stoptest", user=USER3))  # group admin
    game = (await row(gq, QuizGame))[0]
    assert game.status == GAME_STOPPED and "to‘xtatildi" in texts(gq)[-1]
    assert gq.tg.of("stop_poll")


async def test_starter_and_bot_admin_can_stop(gq):
    t = await make_test(gq)
    await start_game(gq, t, USER2)
    await send(gq, gmsg("/stoptest", user=USER2))
    assert (await row(gq, QuizGame))[0].status == GAME_STOPPED
    await send(gq, gcb(f"qg:go:{t.id}", USER2))
    await send(gq, gcb("qg:stop", OWNER))
    assert [g.status for g in await row(gq, QuizGame)] == [GAME_STOPPED, GAME_STOPPED]


async def test_stopped_game_runner_exits_without_posting(gq):
    t = await make_test(gq, n=3)
    game = await start_game(gq, t)
    await ask(gq, game)
    await send(gq, gmsg("/stoptest", user=USER))
    before = len(gq.tg.calls)
    assert await close(gq, game) == "stopped"
    assert (await ask(gq, game))[0] == "stopped"
    assert len(gq.tg.calls) == before


async def test_top_command(gq):
    t = await make_test(gq, n=1)
    await send(gq, gmsg("/top"))
    assert "Hozircha reyting yo‘q" in texts(gq)[-1]
    game = await start_game(gq, t)
    await ask(gq, game)
    await send(gq, vote(poll_no(gq), [gq.tg.of("send_poll")[-1]["correct_option_id"]], USER, "Ali"))
    await send(gq, gmsg("/top"))
    assert "Ali" in texts(gq)[-1]


async def test_resume_fresh_games_and_close_stale(gq):
    t = await make_test(gq)
    fresh = QuizGame(bot_id=gq.bot.id, test_id=t.id, chat_id=-1, starter_id=USER, order=[1], total=1, created_at=utcnow_naive())
    stale = QuizGame(bot_id=gq.bot.id, test_id=t.id, chat_id=-2, starter_id=USER, order=[1], total=1,
                     created_at=utcnow_naive() - timedelta(hours=2))
    gq.session.add_all([fresh, stale])
    await gq.session.commit()
    # resume_games uses the real clock for "now"; both rows are compared against it
    qg_now = datetime.now(timezone.utc)
    gq.clock.now = qg_now
    count = await qg.resume_games(session_factory=gq.factory, client_for=gq.cf, sleep=no_sleep)
    assert count == 1 and gq.scheduled == [fresh.id]
    by_id = {g.id: g.status for g in await row(gq, QuizGame)}
    assert by_id[fresh.id] == GAME_RUNNING and by_id[stale.id] == GAME_STOPPED


def utcnow_naive():
    return datetime.now(timezone.utc)


async def test_personal_quiz_still_works_next_to_group_games(gq):
    from engine import quiz as personal
    t = await make_test(gq, n=1)
    await start_game(gq, t)
    # a vote for an unknown poll must not crash and must not create group answers
    await send(gq, vote("nonexistent", [0], USER))
    assert not await row(gq, QuizGameAnswer)
    # private chat messages are still handled by the personal quiz flow
    await personal.ensure_setup(gq.session, gq.bot)
    await send(gq, {"update_id": None, "message": {"chat": {"id": USER, "type": "private"}, "from": {"id": USER, "first_name": "Ali"}, "text": "/start"}})
    assert any("Test botiga" in kw["text"] for kw in gq.tg.of("send_message") if kw["chat_id"] == USER)
