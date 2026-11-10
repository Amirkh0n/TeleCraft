"""Forced subscription gate."""
from types import SimpleNamespace

from telegram.error import BadRequest

from engine import subscription
from helpers import USER, add_button, add_menu, message, send, tap
from models.audience import RequiredChannel
from models.button_actions import ActionType


def member(status, is_member=None):
    return SimpleNamespace(status=status, is_member=is_member)


async def add_channel(env, chat_id=-100, title="Yangiliklar", username="news", invite_link=None):
    env.session.add(RequiredChannel(bot_id=env.bot.id, chat_id=chat_id, title=title,
                                    username=username, invite_link=invite_link))
    await env.session.commit()


def set_members(env, statuses):
    """statuses: chat_id -> status string / exception."""
    async def get_chat_member(**kw):
        result = statuses[kw["chat_id"]]
        if isinstance(result, Exception):
            raise result
        return member(result)
    env.tg.get_chat_member = get_chat_member


async def test_no_channels_means_no_gate(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start"))
    assert env.tg.texts() == ["Salom"]


async def test_unsubscribed_user_sees_prompt_with_channel_buttons(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    await add_channel(env, chat_id=-200, title="Chat", username=None, invite_link="https://t.me/+abc")
    set_members(env, {-100: "left", -200: "kicked"})
    await send(env, message("/start"))

    sent = env.tg.last()
    assert "obuna bo‘ling" in sent["text"] and "Salom" not in env.tg.texts()
    rows = sent["reply_markup"].inline_keyboard
    assert [r[0].url for r in rows[:-1]] == ["https://t.me/news", "https://t.me/+abc"]
    assert rows[-1][0].callback_data == subscription.CHECK_CALLBACK


async def test_subscribed_user_passes(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    set_members(env, {-100: "member"})
    await send(env, message("/start"))
    assert env.tg.texts() == ["Salom"]


async def test_check_button_lets_user_in_after_joining(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    set_members(env, {-100: "left"})
    await send(env, message("/start"))
    set_members(env, {-100: "member"})
    update = {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "chk"}}
    await send(env, update)
    assert env.tg.texts()[-1] == "Salom"


async def test_check_button_still_blocks_if_not_joined(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    set_members(env, {-100: "left"})
    update = {"update_id": None, "callback_query": {"id": "c", "from": {"id": USER, "first_name": "Ali"}, "data": "chk"}}
    await send(env, update)
    assert "Salom" not in env.tg.texts() and "obuna" in env.tg.texts()[-1]


async def test_buttons_and_texts_are_gated_too(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "Ha", ActionType.text, "SECRET")
    await add_channel(env)
    set_members(env, {-100: "left"})
    await send(env, tap(button))
    await send(env, message("istalgan matn"))
    assert "SECRET" not in env.tg.texts()


async def test_broken_channel_never_locks_users_out(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    set_members(env, {-100: BadRequest("Chat not found")})
    await send(env, message("/start"))
    assert env.tg.texts() == ["Salom"]


async def test_membership_result_is_cached_briefly(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await add_channel(env)
    calls = []

    async def get_chat_member(**kw):
        calls.append(1)
        return member("member")

    env.tg.get_chat_member = get_chat_member
    subscription._ok_cache.clear()
    await send(env, message("/start"))
    await send(env, message("/start"))
    assert len(calls) == 1


def test_is_joined_rules():
    assert subscription.is_joined(member("creator"))
    assert subscription.is_joined(member("restricted", is_member=True))
    assert not subscription.is_joined(member("restricted", is_member=False))
    assert not subscription.is_joined(member("left"))


async def test_describe_channel_checks_bot_is_admin():
    class TG:
        def __init__(self, status, chat_type="channel"):
            self.status, self.chat_type = status, chat_type

        async def get_chat(self, chat_id):
            return SimpleNamespace(id=-100, type=self.chat_type, title="T", username="t")

        async def get_me(self):
            return SimpleNamespace(id=1)

        async def get_chat_member(self, chat_id, user_id):
            return member(self.status)

    ok = await subscription.describe_channel(TG("administrator"), "@t")
    assert ok == (-100, "T", "t", None)
    assert (await subscription.describe_channel(TG("member"), "@t"))[3] is not None
    assert (await subscription.describe_channel(TG("administrator", "private"), "@t"))[3] == "Bu kanal yoki guruh emas."
