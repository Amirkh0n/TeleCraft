"""Builder side of cinema bots: mode switch and admin management."""
import pytest
from sqlalchemy import select
from telegram.ext import CallbackQueryHandler

from constructor.bot import build_constructor_application
from constructor.flows.cinema import add_admin, list_admins, parse_tg_id, remove_admin, set_kind
from engine import cinema
from helpers import OWNER, USER, message, send
from models.menus import Menu
from models.movies import KIND_CINEMA, KIND_STANDARD


@pytest.mark.parametrize("text, expected", [("123456789", 123456789), (" 55555 ", 55555)])
def test_parse_tg_id_ok(text, expected):
    assert parse_tg_id(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "12", "-100123456", "@user", "1234567890123456", "12 345 678"])
def test_parse_tg_id_rejects(text):
    with pytest.raises(ValueError):
        parse_tg_id(text)


async def test_enable_cinema_creates_start_menu_and_switches_router(env):
    assert (await env.session.execute(select(Menu))).first() is None
    await set_kind(env.session, env.bot, KIND_CINEMA)
    menu = (await env.session.execute(select(Menu))).scalar_one()
    assert menu.is_start and "Kino" in menu.message_text
    env.session.add(cinema.Movie(bot_id=env.bot.id, code="1", title="Bir", file_id="F"))
    await env.session.commit()
    await send(env, message("1", user=USER))
    assert env.tg.last("send_video")["video"] == "F"


async def test_disable_cinema_keeps_movies_and_restores_menus(env):
    await set_kind(env.session, env.bot, KIND_CINEMA)
    env.session.add(cinema.Movie(bot_id=env.bot.id, code="1", title="Bir", file_id="F"))
    await env.session.commit()
    await set_kind(env.session, env.bot, KIND_STANDARD)
    await send(env, message("1", user=USER))
    assert not env.tg.of("send_video")
    count = (await env.session.execute(select(cinema.Movie))).scalars().all()
    assert len(count) == 1


async def test_existing_start_menu_is_reused(env):
    existing = Menu(bot_id=env.bot.id, title="Asosiy", message_text="Salom", is_start=True)
    env.session.add(existing)
    await env.session.commit()
    await set_kind(env.session, env.bot, KIND_CINEMA)
    assert len((await env.session.execute(select(Menu))).scalars().all()) == 1


async def test_add_list_remove_admin_and_limits(env):
    assert await add_admin(env.session, env.bot, 42424, OWNER) is None
    assert await list_admins(env.session, env.bot) == [42424]
    assert "allaqachon" in await add_admin(env.session, env.bot, 42424, OWNER)
    assert "egasi" in await add_admin(env.session, env.bot, OWNER, OWNER)
    assert await remove_admin(env.session, env.bot, 42424) is True
    assert await remove_admin(env.session, env.bot, 42424) is False
    for n in range(20):
        assert await add_admin(env.session, env.bot, 10000 + n, OWNER) is None
    assert "oshmasligi" in await add_admin(env.session, env.bot, 99999, OWNER)


async def test_admin_added_in_builder_can_manage_cinema_in_child_bot(env):
    await set_kind(env.session, env.bot, KIND_CINEMA)
    await add_admin(env.session, env.bot, 4242, OWNER)
    await send(env, message(user=4242, video={"file_id": "V"}))  # idle: ignored
    assert (await env.session.execute(select(cinema.Movie))).first() is None
    await send(env, message("/admin", user=4242))
    assert "Admin panel" in env.tg.last()["text"]
    # a removed admin loses access immediately
    await remove_admin(env.session, env.bot, 4242)
    n = len(env.tg.calls)
    await send(env, message("/admin", user=4242))
    assert "Admin panel" not in env.tg.calls[n][1]["text"]


def test_cinema_callbacks_are_anchored_and_registered_before_legacy_ones():
    app = build_constructor_application("123:ABC")
    handlers = [h for h in app.handlers[0] if isinstance(h, CallbackQueryHandler) and h.pattern]
    patterns = [h.pattern.pattern for h in handlers]

    def first_match(data):
        return next(p for h, p in zip(handlers, patterns) if h.pattern.search(data))

    for data in ("cin:home", "cin:on", "cin:off", "adm:home", "adm:add", "adm:del:123456"):
        assert first_match(data).startswith("^")


async def test_channel_crud_helpers(env):
    from constructor.flows.cinema import clear_channel, save_channel
    await save_channel(env.session, env.bot, -1001234, "Kino <kanal>")
    assert (env.bot.movie_channel_id, env.bot.movie_channel_title) == (-1001234, "Kino <kanal>")
    await save_channel(env.session, env.bot, -1005678, "Yangi")
    assert env.bot.movie_channel_id == -1005678
    await clear_channel(env.session, env.bot)
    assert env.bot.movie_channel_id is None and env.bot.movie_channel_title is None


def test_channel_callbacks_registered_and_anchored():
    app = build_constructor_application("123:ABC")
    patterns = [h.pattern.pattern for h in app.handlers[0] if isinstance(h, CallbackQueryHandler) and h.pattern]
    for data in ("cin:ch", "cin:chdel"):
        first = next(p for h, p in zip([h for h in app.handlers[0] if isinstance(h, CallbackQueryHandler) and h.pattern], patterns)
                     if h.pattern.search(data))
        assert first.startswith("^")
