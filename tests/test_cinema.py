import pytest
from sqlalchemy import select

from helpers import OWNER, USER, send
from helpers import message as _message
from models.admin_links import AdminLink
from models.movies import Movie
from models.user_sessions import UserSession

ADMIN2 = 55


def message(text=None, *, user=OWNER, **extra):
    return _message(text, user=user, **extra)


def cb(data, user=OWNER, mid=9):
    return {"update_id": None, "callback_query": {
        "id": "c", "from": {"id": user, "first_name": "A"}, "data": data,
        "message": {"message_id": mid, "chat": {"id": user, "type": "private"}},
    }}


def video(file_id="VID1", user=OWNER, kind="video"):
    return message(user=user, **{kind: {"file_id": file_id}})


async def movies(env):
    q = select(Movie).order_by(Movie.id).execution_options(populate_existing=True)
    return list((await env.session.execute(q)).scalars().all())


@pytest.fixture
async def cinema(env):
    env.bot.kind = "cinema"
    await env.session.commit()
    return env


async def add_movie(env, code="101", title="Titanik", file_id="F1", desc=None, user=OWNER):
    await send(env, message("/admin", user=user))
    await send(env, cb("cm:add", user=user))
    await send(env, video(file_id, user=user))
    await send(env, message("/skip", user=user))
    await send(env, message(code, user=user))
    await send(env, message(title, user=user))
    await send(env, message(desc or "/skip", user=user))


async def test_admin_adds_movie_by_file_id(cinema):
    await add_movie(cinema, desc="Drama, 1997")
    [m] = await movies(cinema)
    assert (m.code, m.title, m.file_id, m.file_type, m.description, m.added_by) == (
        "101", "Titanik", "F1", "video", "Drama, 1997", OWNER)
    assert "Saqlandi" in cinema.tg.last()["text"]


async def test_viewer_gets_movie_by_code_and_views_count(cinema):
    await add_movie(cinema)
    await send(cinema, message("101", user=USER))
    call = cinema.tg.last("send_video")
    assert call["video"] == "F1" and call["chat_id"] == USER and "Titanik" in call["caption"]
    await send(cinema, message("  101 ", user=USER))
    assert (await movies(cinema))[0].views == 2


async def test_search_by_title_then_tap(cinema):
    await add_movie(cinema, "101", "Titanik", "F1")
    await add_movie(cinema, "102", "Titan A.E.", "F2")
    await send(cinema, message("titan", user=USER))
    markup = cinema.tg.last()["reply_markup"]
    ids = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert len(ids) == 2
    await send(cinema, cb(ids[0], user=USER))
    assert cinema.tg.last("send_video")["chat_id"] == USER


async def test_not_found(cinema):
    await send(cinema, message("zzz", user=USER))
    assert "topilmadi" in cinema.tg.last()["text"]


async def test_non_admin_cannot_use_admin_panel(cinema):
    await send(cinema, message("/admin", user=USER))
    assert not any("Admin panel" in t for t in cinema.tg.texts(USER))
    await send(cinema, cb("cm:add", user=USER))
    assert await movies(cinema) == []
    n = len(cinema.tg.calls)
    await send(cinema, video(user=USER))
    assert len(cinema.tg.calls) == n  # ignored, nothing sent


async def test_start_shows_admin_hint_only_to_admins(cinema):
    await send(cinema, message("/start", user=USER))
    assert "/admin" not in cinema.tg.last()["text"]
    await send(cinema, message("/start", user=OWNER))
    assert "/admin" in cinema.tg.last()["text"]


async def test_duplicate_code_rejected_and_auto_code(cinema):
    await add_movie(cinema, "101")
    await send(cinema, cb("cm:add"))
    await send(cinema, video("F9"))
    await send(cinema, message("/skip"))
    await send(cinema, message("101"))
    assert "band" in cinema.tg.last()["text"]
    await send(cinema, message("/auto"))
    await send(cinema, message("Yangi"))
    await send(cinema, message("/skip"))
    assert [m.code for m in await movies(cinema)] == ["101", "102"]


async def test_invalid_code_and_text_instead_of_video(cinema):
    await send(cinema, cb("cm:add"))
    await send(cinema, message("salom"))
    assert "Video" in cinema.tg.last()["text"]
    await send(cinema, video())
    await send(cinema, message("/skip"))
    await send(cinema, message("bad code!"))
    assert "faqat" in cinema.tg.last()["text"]


async def test_cancel_clears_state(cinema):
    await send(cinema, cb("cm:add"))
    await send(cinema, message("/cancel"))
    us = (await cinema.session.execute(select(UserSession))).scalar_one()
    assert us.state is None
    await send(cinema, video())
    assert await movies(cinema) == []


async def test_edit_title_code_desc_and_file(cinema):
    await add_movie(cinema)
    mid = (await movies(cinema))[0].id
    for field, value, attr in (("title", "Yangi nom", "title"), ("code", "500", "code"), ("desc", "Tavsif", "description")):
        await send(cinema, cb(f"cm:edit:{mid}:{field}"))
        await send(cinema, message(value))
        assert getattr((await movies(cinema))[0], attr) == value
    await send(cinema, cb(f"cm:edit:{mid}:file"))
    await send(cinema, video("NEWFILE", kind="document"))
    m = (await movies(cinema))[0]
    assert (m.file_id, m.file_type) == ("NEWFILE", "document")
    await send(cinema, message("500", user=USER))
    assert cinema.tg.last("send_document")["document"] == "NEWFILE"


async def test_delete_movie(cinema):
    await add_movie(cinema)
    mid = (await movies(cinema))[0].id
    await send(cinema, cb(f"cm:del:{mid}"))
    assert len(await movies(cinema)) == 1  # needs confirmation
    await send(cinema, cb(f"cm:delok:{mid}"))
    assert await movies(cinema) == []


async def test_list_pagination_and_stats(cinema):
    for n in range(10):
        cinema.session.add(Movie(bot_id=cinema.bot.id, code=str(200 + n), title=f"Film {n}", file_id=f"f{n}", views=n))
    await cinema.session.commit()
    await send(cinema, cb("cm:list:0"))
    assert "1/2" in cinema.tg.last("edit_message_text")["text"]
    await send(cinema, cb("cm:list:1"))
    assert "2/2" in cinema.tg.last("edit_message_text")["text"]
    await send(cinema, cb("cm:stats"))
    text = cinema.tg.last("edit_message_text")["text"]
    assert "Kinolar: 10" in text and "Jami ko‘rishlar: 45" in text and "Film 9" in text


async def test_linked_admin_can_manage_but_other_bot_movie_is_isolated(cinema):
    cinema.session.add(AdminLink(bot_id=cinema.bot.id, admin_tg_id=ADMIN2))
    await cinema.session.commit()
    await add_movie(cinema, "7", "Admin2 kino", "FX", user=ADMIN2)
    [m] = await movies(cinema)
    assert m.added_by == ADMIN2
    await send(cinema, cb("cm:open:99999"))
    assert "topilmadi" in cinema.tg.last("edit_message_text")["text"]


async def test_standard_bot_unaffected(env):
    await send(env, message("101", user=USER))
    assert not env.tg.of("send_video")


async def test_bad_file_id_reports_error(cinema):
    from telegram.error import BadRequest
    await add_movie(cinema)

    async def boom(**kw):
        raise BadRequest("wrong file identifier")
    cinema.tg.send_video = boom
    await send(cinema, message("101", user=USER))
    assert "yuborib bo‘lmadi" in cinema.tg.last()["text"]
    assert (await movies(cinema))[0].views == 0


# ---------------------------------------------------------------- deep link, channel, protect, audience

async def set_channel(env, chat_id=-1001, username="kinobot"):
    env.bot.movie_channel_id = chat_id
    env.bot.username = username
    await env.session.commit()


async def test_deep_link_sends_movie_and_records_source(cinema):
    await add_movie(cinema)
    await send(cinema, message("/start 101", user=USER))
    assert cinema.tg.last("send_video")["video"] == "F1"
    from models.audience import BotUser
    bu = (await cinema.session.execute(select(BotUser).where(BotUser.tg_user_id == USER))).scalar_one()
    assert bu.source == "101"


async def test_deep_link_unknown_code_falls_back_to_welcome(cinema):
    await send(cinema, message("/start nope", user=USER))
    texts = cinema.tg.texts(USER)
    assert "topilmadi" in texts[-2] and "xush kelibsiz" in texts[-1]
    assert not cinema.tg.of("send_video")


async def test_video_is_protected(cinema):
    await add_movie(cinema)
    await send(cinema, message("101", user=USER))
    assert cinema.tg.last("send_video")["protect_content"] is True


async def test_new_movie_is_announced_in_channel_with_poster_and_deep_link(cinema):
    await set_channel(cinema)
    await send(cinema, message("/admin"))
    await send(cinema, cb("cm:add"))
    await send(cinema, video("V1"))
    await send(cinema, message(photo=[{"file_id": "small"}, {"file_id": "BIG"}]))
    await send(cinema, message("7"))
    await send(cinema, message("Rasmli kino"))
    await send(cinema, message("Komediya"))
    post = cinema.tg.last("send_photo")
    assert post["chat_id"] == -1001 and post["photo"] == "BIG"
    assert "Rasmli kino" in post["caption"] and "Komediya" in post["caption"] and "<code>7</code>" in post["caption"]
    button = post["reply_markup"].inline_keyboard[0][0]
    assert button.url == "https://t.me/kinobot?start=7"
    assert not [c for c in cinema.tg.of("send_video") if c["chat_id"] == -1001]
    assert "Kanalga yuborildi" in cinema.tg.last()["text"]


async def test_announcement_without_poster_is_text_and_failure_does_not_lose_movie(cinema):
    await set_channel(cinema)
    await add_movie(cinema)
    assert cinema.tg.last("send_message", ) and [c for c in cinema.tg.of("send_message") if c["chat_id"] == -1001]
    from telegram.error import Forbidden

    async def boom(**kw):
        raise Forbidden("not enough rights")
    cinema.tg.send_message_orig = cinema.tg.send_message
    real = cinema.tg.send_message

    async def selective(**kw):
        if kw.get("chat_id") == -1001:
            raise Forbidden("not enough rights")
        return await real(**kw)
    cinema.tg.send_message = selective
    await add_movie(cinema, "102", "Ikkinchi", "F2")
    assert len(await movies(cinema)) == 2
    assert "administrator" in cinema.tg.last()["text"]


async def test_manual_repost_and_poster_edit(cinema):
    await set_channel(cinema)
    await add_movie(cinema)
    mid = (await movies(cinema))[0].id
    await send(cinema, cb(f"cm:edit:{mid}:poster"))
    await send(cinema, message(photo=[{"file_id": "P2"}]))
    assert (await movies(cinema))[0].poster_file_id == "P2"
    await send(cinema, cb(f"cm:post:{mid}"))
    assert cinema.tg.last("send_photo")["photo"] == "P2"


async def test_cinema_users_are_recorded_so_broadcast_reaches_them(cinema):
    from engine import broadcast
    await add_movie(cinema)
    await send(cinema, message("hello", user=USER))
    await send(cinema, cb("mv:1", user=888))
    from models.audience import BotUser
    ids = {b.tg_user_id for b in (await cinema.session.execute(select(BotUser))).scalars().all()}
    assert {USER, 888} <= ids
    from test_broadcast import run
    draft = await broadcast.create_draft(cinema.session, cinema.bot.id, OWNER, text="Yangi kinolar!")
    assert await broadcast.start(cinema.session, draft.id, spawn=False) == "started"
    await run(cinema, draft)
    got = {c["chat_id"] for c in cinema.tg.of("send_message") if c["text"] == "Yangi kinolar!"}
    assert {USER, 888} <= got


async def test_forced_subscription_gates_cinema_viewers_but_not_admins(cinema):
    from models.audience import RequiredChannel

    class Member:
        status = "left"

    async def get_chat_member(**kw):
        return Member()
    cinema.tg.get_chat_member = get_chat_member
    cinema.session.add(RequiredChannel(bot_id=cinema.bot.id, chat_id=-5, title="Kanal", username="kan"))
    await cinema.session.commit()
    await add_movie(cinema)
    await send(cinema, message("101", user=USER))
    assert not cinema.tg.of("send_video") and "obuna" in cinema.tg.last()["text"]
    await send(cinema, message("/start 101", user=USER))
    assert not cinema.tg.of("send_video")
    await send(cinema, message("101", user=OWNER))
    assert cinema.tg.last("send_video")["chat_id"] == OWNER
