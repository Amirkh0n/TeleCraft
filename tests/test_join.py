import datetime as dt

import pytest
from sqlalchemy import select
from telegram.error import BadRequest, NetworkError

from engine import join as core, join_logic as logic
from helpers import OWNER, USER, send
from helpers import message as _message
from models.join import JoinChat, JoinLink, JoinRequest

CHAT = -1001


def message(text=None, *, user=USER, **extra):
    return _message(text, user=user, **extra)


def cb(data, user=USER, mid=9):
    return {"update_id": None, "callback_query": {
        "id": "c", "from": {"id": user, "first_name": "Ali"}, "data": data,
        "message": {"message_id": mid, "chat": {"id": user, "type": "private"}},
    }}


def join_req(user=USER, chat_id=CHAT, link=None):
    req = {"chat": {"id": chat_id, "title": "Kanalim", "type": "channel"},
           "from": {"id": user, "first_name": "Ali", "username": "ali"}, "user_chat_id": user, "date": 1}
    if link:
        req["invite_link"] = {"invite_link": link}
    return {"update_id": None, "chat_join_request": req}


def admin_added(chat_id=CHAT, status="administrator"):
    return {"update_id": None, "my_chat_member": {
        "chat": {"id": chat_id, "title": "Kanalim", "type": "channel"}, "from": {"id": OWNER, "first_name": "Owner"},
        "new_chat_member": {"status": status}}}


@pytest.fixture
async def jenv(env):
    env.bot.kind = "join"
    await core.ensure_setup(env.session, env.bot)
    return env


async def setup_chat(env, **fields):
    await send(env, admin_added())
    jc = (await env.session.execute(select(JoinChat))).scalar_one()
    for key, value in fields.items():
        setattr(jc, key, value)
    await env.session.commit()
    env.tg.calls.clear()
    return jc


async def requests(env):
    q = select(JoinRequest).execution_options(populate_existing=True).order_by(JoinRequest.id)
    return list((await env.session.execute(q)).scalars().all())


def datas(call):
    kb = call.get("reply_markup")
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data] if kb else []


# ------------------------------------------------------------------ pure logic

def test_parse_questions():
    assert logic.parse_questions("Ismingiz?\n\n Yoshingiz? ") == ["Ismingiz?", "Yoshingiz?"]
    for bad in ("", "a\nb\nc\nd", "x" * 201):
        with pytest.raises(ValueError):
            logic.parse_questions(bad)


def test_render_and_labels():
    assert logic.render("Salom {name}, {chat} {x}", "Ali", "Kanal") == "Salom Ali, Kanal {x}"
    assert [logic.delay_label(s) for s in (0, 30, 300, 3600)] == ["darhol", "30 soniya", "5 daqiqa", "1 soat"]


# ------------------------------------------------------------------ chats

async def test_bot_made_admin_registers_chat_and_tells_admins(jenv):
    await send(jenv, admin_added())
    jc = (await jenv.session.execute(select(JoinChat))).scalar_one()
    assert (jc.chat_id, jc.title, jc.chat_type, jc.mode) == (CHAT, "Kanalim", "channel", "auto")
    assert any("ulandi" in t for t in jenv.tg.texts(OWNER))
    await send(jenv, admin_added(status="left"))
    await jenv.session.refresh(jc)
    assert jc.is_active is False


async def test_unknown_chat_request_registers_chat(jenv):
    await send(jenv, join_req())
    assert (await jenv.session.execute(select(JoinChat))).scalar_one().chat_id == CHAT


# ------------------------------------------------------------------ modes

async def test_auto_mode_welcomes_and_approves(jenv):
    await setup_chat(jenv)
    await send(jenv, join_req())
    assert jenv.tg.of("approve_chat_join_request") == [{"chat_id": CHAT, "user_id": USER}]
    assert "Salom, Ali" in jenv.tg.texts(USER)[0]
    (r,) = await requests(jenv)
    assert r.status == "approved" and r.decided_by is None


async def test_auto_mode_with_delay_waits_then_approves(jenv):
    await setup_chat(jenv, delay_seconds=300)
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    assert r.status == "scheduled" and not jenv.tg.of("approve_chat_join_request")
    async def client_for(bot):
        return jenv.tg
    assert await core.run_once(jenv.session, client_for=client_for) == 0
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=301)
    assert await core.run_once(jenv.session, now=later, client_for=client_for) == 1
    assert len(jenv.tg.of("approve_chat_join_request")) == 1
    assert (await requests(jenv))[0].status == "approved"


async def test_manual_mode_admin_decides_once(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    assert r.status == "review" and not jenv.tg.of("approve_chat_join_request")
    notice = jenv.tg.of("send_message")[-1]
    assert notice["chat_id"] == OWNER and datas(notice) == [f"ja:ok:{r.id}", f"ja:no:{r.id}"]
    await send(jenv, cb(f"ja:ok:{r.id}", user=OWNER))
    assert len(jenv.tg.of("approve_chat_join_request")) == 1
    assert "Qabul qilindi" in jenv.tg.last("edit_message_text")["text"]
    await send(jenv, cb(f"ja:no:{r.id}", user=OWNER))  # second tap: nothing more happens
    assert not jenv.tg.of("decline_chat_join_request")
    assert "allaqachon" in jenv.tg.last("edit_message_text")["text"]
    assert (await requests(jenv))[0].decided_by == OWNER


async def test_manual_decline(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    await send(jenv, cb(f"ja:no:{r.id}", user=OWNER))
    assert jenv.tg.of("decline_chat_join_request") == [{"chat_id": CHAT, "user_id": USER}]
    assert (await requests(jenv))[0].status == "declined"


async def test_non_admin_cannot_decide(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    await send(jenv, cb(f"ja:ok:{r.id}", user=999))
    assert not jenv.tg.of("approve_chat_join_request")


async def test_captcha_flow(jenv):
    await setup_chat(jenv, mode="captcha")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    assert r.status == "captcha" and datas(jenv.tg.last()) == [f"jn:c:{r.id}"]
    await send(jenv, cb(f"jn:c:{r.id}", user=555))  # someone else's button
    assert not jenv.tg.of("approve_chat_join_request")
    await send(jenv, cb(f"jn:c:{r.id}"))
    assert len(jenv.tg.of("approve_chat_join_request")) == 1
    await send(jenv, cb(f"jn:c:{r.id}"))  # pressing again changes nothing
    assert len(jenv.tg.of("approve_chat_join_request")) == 1


async def test_unanswered_captcha_expires(jenv):
    await setup_chat(jenv, mode="captcha")
    await send(jenv, join_req())
    async def client_for(bot):
        return jenv.tg
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=core.EXPIRE_MINUTES + 1)
    assert await core.run_once(jenv.session, now=later, client_for=client_for) == 1
    assert len(jenv.tg.of("decline_chat_join_request")) == 1
    assert (await requests(jenv))[0].status == "expired"


async def test_questions_then_admin_review_with_answers(jenv):
    await setup_chat(jenv, mode="manual", questions=["Ismingiz?", "Nega qo'shilmoqchisiz?"])
    await send(jenv, join_req())
    assert "Savol 1/2" in jenv.tg.last()["text"]
    await send(jenv, message("Ali"))
    assert "Savol 2/2" in jenv.tg.last()["text"]
    assert not [c for c in jenv.tg.of("send_message") if c["chat_id"] == OWNER]
    await send(jenv, message("O'rganish uchun"))
    notice = [c for c in jenv.tg.of("send_message") if c["chat_id"] == OWNER][-1]
    assert "Ismingiz?" in notice["text"] and "O&#x27;rganish uchun" in notice["text"]
    (r,) = await requests(jenv)
    assert r.status == "review" and r.answers == ["Ali", "O'rganish uchun"]


async def test_questions_in_auto_mode_approve_after_last_answer(jenv):
    await setup_chat(jenv, questions=["Telefon?"])
    await send(jenv, join_req())
    assert not jenv.tg.of("approve_chat_join_request")
    await send(jenv, message("+998901234567"))
    assert len(jenv.tg.of("approve_chat_join_request")) == 1


async def test_unreachable_applicant_goes_to_admins(jenv):
    await setup_chat(jenv, mode="captcha")
    jenv.tg.blocked_chats.add(USER)
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    assert r.status == "review" and r.dm_failed
    assert "bo‘lmadi" in jenv.tg.texts(OWNER)[-1]


async def test_paused_chat_is_ignored(jenv):
    await setup_chat(jenv, is_active=False)
    await send(jenv, join_req())
    assert await requests(jenv) == [] and not jenv.tg.calls


async def test_repeated_request_reuses_the_open_one(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    await send(jenv, join_req())
    assert len(await requests(jenv)) == 1


# ------------------------------------------------------------------ telegram errors

async def test_gone_applicant_marks_expired(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    jenv.tg.join_error = BadRequest("HIDE_REQUESTER_MISSING")
    await send(jenv, cb(f"ja:ok:{r.id}", user=OWNER))
    assert (await requests(jenv))[0].status == "expired"


async def test_network_error_keeps_request_open(jenv):
    await setup_chat(jenv, mode="manual")
    await send(jenv, join_req())
    (r,) = await requests(jenv)
    jenv.tg.join_error = NetworkError("down")
    await send(jenv, cb(f"ja:ok:{r.id}", user=OWNER))
    (r,) = await requests(jenv)
    assert r.status == "review" and r.decided_at is None
    jenv.tg.join_error = None
    await send(jenv, cb(f"ja:ok:{r.id}", user=OWNER))
    assert (await requests(jenv))[0].status == "approved"


# ------------------------------------------------------------------ admin panel

async def test_admin_panel_changes_mode_delay_and_pause(jenv):
    jc = await setup_chat(jenv)
    await send(jenv, message("/admin", user=OWNER))
    assert "ja:chats" in datas(jenv.tg.last())
    await send(jenv, cb(f"ja:m:{jc.id}:manual", user=OWNER))
    await send(jenv, cb(f"ja:d:{jc.id}:300", user=OWNER))
    await send(jenv, cb(f"ja:t:{jc.id}", user=OWNER))
    await jenv.session.refresh(jc)
    assert (jc.mode, jc.delay_seconds, jc.is_active) == ("manual", 300, False)
    await send(jenv, cb(f"ja:m:{jc.id}:bogus", user=OWNER))
    await jenv.session.refresh(jc)
    assert jc.mode == "manual"


async def test_admin_sets_questions(jenv):
    jc = await setup_chat(jenv)
    await send(jenv, cb(f"ja:q:{jc.id}", user=OWNER))
    await send(jenv, message("a\nb\nc\nd", user=OWNER))
    assert "Ko‘pi bilan 3" in jenv.tg.texts(OWNER)[-1]
    await send(jenv, message("Ism?\nYosh?", user=OWNER))
    await jenv.session.refresh(jc)
    assert jc.questions == ["Ism?", "Yosh?"]
    await send(jenv, cb(f"ja:q:{jc.id}", user=OWNER))
    await send(jenv, message("/clear", user=OWNER))
    await jenv.session.refresh(jc)
    assert jc.questions == []


async def test_named_links_and_statistics(jenv):
    jc = await setup_chat(jenv, mode="manual")
    await send(jenv, cb(f"ja:ln:{jc.id}", user=OWNER))
    await send(jenv, message("Instagram", user=OWNER))
    assert jenv.tg.of("create_chat_invite_link") == [{"chat_id": CHAT, "name": "Instagram", "creates_join_request": True}]
    (link,) = (await jenv.session.execute(select(JoinLink))).scalars().all()
    assert link.url == "https://t.me/+link1" and link.name == "Instagram"
    await send(jenv, join_req(link=link.url))
    await send(jenv, join_req(user=888, link="https://t.me/+other"))
    reqs = await requests(jenv)
    assert [r.link_id for r in reqs] == [link.id, None]
    await send(jenv, cb(f"ja:ok:{reqs[0].id}", user=OWNER))
    await send(jenv, cb(f"ja:links:{jc.id}", user=OWNER))
    text = jenv.tg.last("edit_message_text")["text"]
    assert "Instagram" in text and "jami 1" in text and "✅ 1" in text
    await send(jenv, cb("ja:stats", user=OWNER))
    assert "jami 2" in jenv.tg.last("edit_message_text")["text"]
    await send(jenv, cb(f"ja:lr:{link.id}", user=OWNER))
    assert len(jenv.tg.of("revoke_chat_invite_link")) == 1
    await jenv.session.refresh(link)
    assert link.is_revoked


async def test_link_creation_failure_is_reported(jenv):
    jc = await setup_chat(jenv)
    async def boom(**kw):
        raise BadRequest("not enough rights")
    jenv.tg.create_chat_invite_link = boom
    await send(jenv, cb(f"ja:ln:{jc.id}", user=OWNER))
    await send(jenv, message("X", user=OWNER))
    assert "yaratib bo‘lmadi" in jenv.tg.texts(OWNER)[-1]
    assert (await jenv.session.execute(select(JoinLink))).scalars().all() == []


async def test_bulk_approve_and_pending_list(jenv):
    jc = await setup_chat(jenv, mode="manual")
    for uid in (801, 802, 803):
        await send(jenv, join_req(user=uid))
    await send(jenv, cb("ja:pend:0", user=OWNER))
    assert len([d for d in datas(jenv.tg.last("edit_message_text")) if d.startswith("ja:r:")]) == 3
    await send(jenv, cb(f"ja:allok:{jc.id}", user=OWNER))
    assert "3" in jenv.tg.last("edit_message_text")["text"]
    await send(jenv, cb(f"ja:allok2:{jc.id}", user=OWNER))
    assert len(jenv.tg.of("approve_chat_join_request")) == 3
    assert {r.status for r in await requests(jenv)} == {"approved"}


async def test_custom_texts(jenv):
    await setup_chat(jenv)
    await send(jenv, cb("ja:tx:welcome", user=OWNER))
    await send(jenv, message("Xush kelibsiz, {name}! <{chat}>", user=OWNER))
    await send(jenv, join_req())
    assert jenv.tg.texts(USER)[0] == "Xush kelibsiz, Ali! &lt;Kanalim&gt;"
    await send(jenv, cb("ja:tx:welcome", user=OWNER))
    await send(jenv, message("/clear", user=OWNER))
    assert (await core.get_settings(jenv.session, jenv.bot.id)).welcome_text is None


async def test_start_command(jenv):
    await send(jenv, message("/start"))
    assert "/admin" not in jenv.tg.last()["text"]
    await send(jenv, message("/start", user=OWNER))
    assert "/admin" in jenv.tg.last()["text"]


async def test_other_bot_kinds_ignore_join_requests(env):
    await send(env, join_req())
    assert not env.tg.calls
