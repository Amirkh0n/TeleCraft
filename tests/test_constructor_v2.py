"""Builder helpers: media extraction/re-upload, form options, CSV export, ownership checks."""
import csv
import io
from datetime import datetime
from types import SimpleNamespace as NS

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telegram.error import TelegramError

from constructor.flows.forms import build_csv, owned_form, parse_options
from constructor.flows.screens import extract_media, media_from_sent, owned_menu, reupload
from core.migrations import upgrade_database
from models.bots import Bot
from models.forms import Form
from models.menus import Menu
from models.users import User


def msg(**kw):
    base = dict(animation=None, photo=None, video=None, audio=None, voice=None, document=None)
    base.update(kw)
    return NS(**base)


def test_extract_media_picks_largest_photo():
    m = msg(photo=[NS(file_id="s", file_size=1), NS(file_id="b", file_size=9)])
    assert extract_media(m) == ("photo", "b", 9, None)


def test_animation_wins_over_document():
    gif = NS(file_id="g", file_size=5, file_name="a.mp4")
    assert extract_media(msg(animation=gif, document=gif))[0] == "animation"


def test_extract_media_document_and_none():
    assert extract_media(msg(document=NS(file_id="d", file_size=3, file_name="x.pdf"))) == ("document", "d", 3, "x.pdf")
    assert extract_media(msg()) is None


class Child:
    def __init__(self, sent, delete_fails=False):
        self.sent, self.delete_fails, self.calls, self.deleted = sent, delete_fails, [], []

    async def send_photo(self, **kw):
        self.calls.append(("photo", kw))
        return self.sent

    async def send_document(self, **kw):
        self.calls.append(("document", kw))
        return self.sent

    async def delete_message(self, **kw):
        if self.delete_fails:
            raise TelegramError("cannot delete")
        self.deleted.append(kw["message_id"])


async def test_reupload_returns_child_file_id_and_cleans_up():
    child = Child(NS(message_id=7, photo=[NS(file_id="x"), NS(file_id="child-id")]))
    assert await reupload(child, 5, "photo", b"data", None) == "child-id"
    assert child.calls[0][1] == {"chat_id": 5, "photo": b"data"} and child.deleted == [7]


async def test_reupload_passes_filename_and_survives_delete_failure():
    child = Child(NS(message_id=1, document=NS(file_id="doc-id")), delete_fails=True)
    assert await reupload(child, 5, "document", b"d", "a.pdf") == "doc-id"
    assert child.calls[0][1]["filename"] == "a.pdf"


async def test_reupload_rejects_unknown_kind_and_missing_id():
    with pytest.raises(ValueError):
        await reupload(Child(None), 1, "sticker", b"", None)
    with pytest.raises(ValueError):
        await reupload(Child(NS(message_id=1, photo=[])), 1, "photo", b"", None)
    assert media_from_sent("video", NS(video=None)) is None


def test_parse_options():
    assert parse_options("A\nB, C\nA") == ["A", "B", "C"]
    for bad in ("A", "", "\n".join(str(i) for i in range(13)), "A\n" + "x" * 61):
        with pytest.raises(ValueError):
            parse_options(bad)


def test_csv_has_one_column_per_question_and_blocks_formulas():
    fields = [NS(label="Ism"), NS(label="Yosh")]
    sub = NS(created_at=datetime(2026, 1, 2, 3, 4), tg_user_id=9, username="=cmd", full_name="Ali",
             answers=[{"label": "Ism", "value": "+998"}, {"label": "Yosh", "value": None}])
    raw = build_csv(fields, [sub])
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["Sana", "Telegram ID", "Username", "Ism", "Ism", "Yosh"]
    assert rows[1] == ["2026-01-02 03:04", "9", "'=cmd", "Ali", "'+998", ""]


async def test_builder_only_reaches_own_menus_and_forms(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    await upgrade_database(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        mine, other = User(tg_id=1, full_name="me"), User(tg_id=2, full_name="other")
        s.add_all([mine, other])
        await s.flush()
        bot = Bot(owner_id=other.id, name="B", token="123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789")
        s.add(bot)
        await s.flush()
        menu, form = Menu(bot_id=bot.id, title="m", is_start=True), Form(bot_id=bot.id, title="f")
        s.add_all([menu, form])
        await s.commit()

        assert (await owned_menu(s, 1, menu.id)) == (None, None)
        assert (await owned_form(s, 1, form.id)) == (None, None)
        assert (await owned_menu(s, 2, menu.id))[0].id == menu.id
        assert (await owned_form(s, 2, form.id))[0].id == form.id
    await engine.dispose()


def test_link_action_url_validation_is_callable_the_way_the_builder_calls_it():
    """Regression: the builder called validate_url without its field name, so no link could ever be saved."""
    from core.validators import validate_url
    assert validate_url("https://example.com", "URL") == "https://example.com"
    with pytest.raises(Exception):
        validate_url("example.com", "URL")
