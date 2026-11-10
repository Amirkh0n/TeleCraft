"""Broadcast engine: delivery outcomes, resume, cancel, limits."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter

from engine import broadcast as bc
from models.audience import BROADCAST_CANCELLED, BROADCAST_DONE, BROADCAST_SENDING, BotUser, Broadcast


async def no_sleep(_):
    pass


async def add_users(env, count, blocked=()):
    for i in range(1, count + 1):
        env.session.add(BotUser(bot_id=env.bot.id, tg_user_id=1000 + i, is_blocked=i in blocked))
    await env.session.commit()


async def draft(env, **content):
    content.setdefault("text", "Aksiya!")
    return await bc.create_draft(env.session, env.bot.id, 1, **content)


async def run(env, b, **kw):
    await bc.run(b.id, client=env.tg, session_factory=lambda: _Ctx(env.session), sleep=no_sleep, rate=0, **kw)
    await env.session.refresh(b)


class _Ctx:
    """session_factory stand-in that reuses the test session."""
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


async def test_sends_to_everyone_not_blocked_and_finishes(env):
    await add_users(env, 25, blocked={3})
    b = await draft(env)
    assert await bc.start(env.session, b.id, spawn=False) == "started"
    assert b.total == 24
    await run(env, b)
    assert (b.status, b.sent, b.failed, b.blocked) == (BROADCAST_DONE, 24, 0, 0)
    assert len(env.tg.of("send_message")) == 24 and b.finished_at is not None
    assert 1003 not in {kw["chat_id"] for kw in env.tg.of("send_message")}


async def test_blocked_users_are_marked_and_counted(env):
    await add_users(env, 3)
    env.tg.blocked_chats.add(1002)
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert (b.sent, b.blocked) == (2, 1)
    row = (await env.session.execute(select(BotUser).where(BotUser.tg_user_id == 1002))).scalar_one()
    assert row.is_blocked


async def test_retry_after_waits_then_succeeds(env):
    await add_users(env, 1)
    original = env.tg.send_message
    calls = []
    waits = []

    async def flaky(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise RetryAfter(timedelta(seconds=3))
        return await original(**kw)

    env.tg.send_message = flaky
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)

    async def record(seconds):
        waits.append(seconds)

    await bc.run(b.id, client=env.tg, session_factory=lambda: _Ctx(env.session), sleep=record, rate=0)
    await env.session.refresh(b)
    assert b.sent == 1 and waits == [4.0] and len(calls) == 2


async def test_network_errors_fail_after_retries_without_stopping(env):
    await add_users(env, 2)
    original = env.tg.send_message

    async def broken(**kw):
        if kw["chat_id"] == 1001:
            raise NetworkError("boom")
        return await original(**kw)

    env.tg.send_message = broken
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert (b.sent, b.failed, b.status) == (1, 1, BROADCAST_DONE)


async def test_chat_not_found_counts_as_blocked_other_bad_request_as_failed(env):
    await add_users(env, 2)
    original = env.tg.send_message

    async def picky(**kw):
        if kw["chat_id"] == 1001:
            raise BadRequest("Chat not found")
        if kw["chat_id"] == 1002:
            raise BadRequest("Message is too long")
        return await original(**kw)

    env.tg.send_message = picky
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert (b.blocked, b.failed, b.sent) == (1, 1, 0)


async def test_resume_continues_after_cursor_without_duplicates(env):
    await add_users(env, 5)
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    first_two = (await env.session.execute(select(BotUser).order_by(BotUser.id).limit(2))).scalars().all()
    b.cursor, b.sent = first_two[-1].id, 2
    await env.session.commit()

    await run(env, b)
    chats = [kw["chat_id"] for kw in env.tg.of("send_message")]
    assert chats == [1003, 1004, 1005] and b.sent == 5 and b.status == BROADCAST_DONE


async def test_cancel_stops_between_batches(env):
    await add_users(env, 30)
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    original = env.tg.send_message
    count = []

    async def cancel_midway(**kw):
        count.append(1)
        if len(count) == 5:
            await bc.cancel(env.session, b.id)
        return await original(**kw)

    env.tg.send_message = cancel_midway
    await run(env, b)
    assert b.status == BROADCAST_CANCELLED and 5 <= b.sent < 30


async def test_only_one_active_broadcast_per_bot_and_drafts_only(env):
    await add_users(env, 1)
    first, second = await draft(env), await draft(env, text="boshqa")
    assert await bc.start(env.session, first.id, spawn=False) == "started"
    assert await bc.start(env.session, second.id, spawn=False) == "busy"
    assert await bc.start(env.session, first.id, spawn=False) == "invalid"  # already started
    assert await bc.start(env.session, 9999, spawn=False) == "invalid"


async def test_empty_draft_cannot_start(env):
    b = await bc.create_draft(env.session, env.bot.id, 1)
    assert await bc.start(env.session, b.id, spawn=False) == "invalid"


async def test_media_with_long_text_is_split_and_button_attached(env):
    await add_users(env, 1)
    b = await draft(env, text="x" * 1500, media_type="photo", media_file_id="AgAC",
                    button_text="Ochish", button_url="https://example.com")
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert env.tg.last("send_photo")["photo"] == "AgAC" and "caption" not in env.tg.last("send_photo")
    markup = env.tg.last()["reply_markup"]
    assert markup.inline_keyboard[0][0].url == "https://example.com"


async def test_media_with_short_text_uses_caption(env):
    await add_users(env, 1)
    b = await draft(env, media_type="video", media_file_id="BAAD")
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert env.tg.last("send_video")["caption"] == "Aksiya!" and b.sent == 1


async def test_run_ignores_unknown_or_finished_broadcast(env):
    await bc.run(12345, client=env.tg, session_factory=lambda: _Ctx(env.session), sleep=no_sleep)
    b = await draft(env)
    await run(env, b)  # still a draft: must not send
    assert env.tg.calls == [] and b.status != BROADCAST_SENDING


def test_summary_mentions_all_counters():
    text = bc.summary(SimpleNamespace(status=BROADCAST_DONE, sent=7, failed=1, blocked=2, total=10))
    assert "Yuborildi: 7" in text and "Bloklaganlar: 2" in text and "10/10" in text


async def test_forbidden_is_not_retried(env):
    await add_users(env, 1)
    attempts = []

    async def deny(**kw):
        attempts.append(1)
        raise Forbidden("bot was blocked by the user")

    env.tg.send_message = deny
    b = await draft(env)
    await bc.start(env.session, b.id, spawn=False)
    await run(env, b)
    assert attempts == [1] and b.blocked == 1


async def test_spawn_task_runs_once(env, monkeypatch):
    started = []

    async def fake_run(broadcast_id):
        started.append(broadcast_id)
        await asyncio.sleep(0)

    monkeypatch.setattr(bc, "run", fake_run)
    bc.spawn_task(7)
    bc.spawn_task(7)
    await asyncio.sleep(0.01)
    assert started == [7]
    assert isinstance(Broadcast, type)
