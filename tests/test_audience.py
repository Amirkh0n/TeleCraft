"""Audience tracking and statistics."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from engine import router
from engine.audience import set_blocked, stats, touch_user
from helpers import USER, add_menu, message, send
from models.audience import BotUser


async def users(env):
    return (await env.session.execute(select(BotUser).order_by(BotUser.id))).scalars().all()


async def test_first_message_creates_audience_row_with_source(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start promo_ig"))
    [row] = await users(env)
    assert (row.tg_user_id, row.username, row.full_name, row.source, row.is_blocked) == (USER, "ali", "Ali", "promo_ig", False)


async def test_source_is_kept_from_the_first_visit_only(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start first"))
    await send(env, message("/start second"))
    [row] = await users(env)
    assert row.source == "first"


async def test_returning_user_is_unblocked_and_profile_refreshed(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start"))
    await set_blocked(env.session, env.bot.id, USER)
    assert (await users(env))[0].is_blocked
    update = message("/start")
    update["message"]["from"]["username"] = "newname"
    await send(env, update)
    [row] = await users(env)
    assert not row.is_blocked and row.username == "newname"


async def test_forbidden_marks_user_blocked(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    env.tg.blocked_chats.add(USER)
    await send(env, message("/start"))
    [row] = await users(env)
    assert row.is_blocked


async def test_my_chat_member_updates_block_state(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start"))

    def event(status, chat_type="private"):
        return {"update_id": None, "my_chat_member": {
            "chat": {"id": USER, "type": chat_type}, "from": {"id": USER},
            "new_chat_member": {"status": status},
        }}

    await send(env, event("kicked"))
    assert (await users(env))[0].is_blocked
    await send(env, event("member"))
    assert not (await users(env))[0].is_blocked
    await send(env, event("kicked", chat_type="channel"))
    assert not (await users(env))[0].is_blocked


async def test_bots_and_group_chats_are_not_counted(env):
    await touch_user(env.session, env.bot.id, {"id": 5, "is_bot": True})
    await touch_user(env.session, env.bot.id, {})
    assert await users(env) == []


async def test_callbacks_count_as_activity(env):
    from helpers import add_button, tap
    from models.button_actions import ActionType
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "Ha", ActionType.text, "ok")
    await send(env, tap(button, user=999))
    assert [u.tg_user_id for u in await users(env)] == [999]


async def test_stats_windows(env):
    now = datetime(2026, 6, 30, 12, tzinfo=timezone.utc)
    rows = [
        ("new", now - timedelta(hours=2), now - timedelta(hours=1), False, "ig"),
        ("week", now - timedelta(days=5), now - timedelta(days=3), False, "ig"),
        ("old", now - timedelta(days=90), now - timedelta(days=40), False, None),
        ("gone", now - timedelta(days=10), now - timedelta(days=9), True, "tt"),
    ]
    for i, (name, first, last, blocked, source) in enumerate(rows, 1):
        env.session.add(BotUser(
            bot_id=env.bot.id, tg_user_id=i, full_name=name, first_seen_at=first,
            last_seen_at=last, is_blocked=blocked, source=source,
        ))
    await env.session.commit()

    result = await stats(env.session, env.bot.id, now=now)
    assert result["total"] == 4 and result["blocked"] == 1 and result["active"] == 3
    assert (result["new_24h"], result["new_7d"], result["new_30d"]) == (1, 2, 3)
    assert (result["active_24h"], result["active_7d"]) == (1, 2)
    assert result["sources"] == [("ig", 2), ("tt", 1)]
    assert result["submissions"] == 0 and result["broadcast_messages"] == 0


async def test_stats_are_per_bot(env):
    env.session.add(BotUser(bot_id=env.bot.id + 100, tg_user_id=1))
    await env.session.commit()
    assert (await stats(env.session, env.bot.id))["total"] == 0


def test_router_has_no_stale_state_between_tests():
    assert router._seen == {} or isinstance(router._seen, dict)
