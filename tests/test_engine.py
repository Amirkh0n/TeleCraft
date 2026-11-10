"""Child-bot runtime tests with a fake Telegram client (no network)."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import BadRequest

from engine import router
from engine.forms import CANCEL_LABEL, SKIP_LABEL, format_submission, parse_answer
from helpers import (
    OWNER, USER, add_button, add_form, add_menu, message, send, tap,
)
from models.admin_links import AdminLink
from models.bots import Bot
from models.button_actions import ActionType
from models.forms import FormField, FormSubmission
from models.menus import Menu
from models.user_sessions import UserSession
from models.users import User


# ------------------------------------------------------------------ screens, media, keyboards

async def test_start_shows_inline_menu(env):
    menu = await add_menu(env, "Bosh", "Salom!", start=True)
    await add_button(env, menu, "Narxlar", ActionType.text, "Narx: 10")
    await send(env, message("/start"))

    sent = env.tg.last()
    assert sent["text"] == "Salom!" and sent["chat_id"] == USER
    assert isinstance(sent["reply_markup"], InlineKeyboardMarkup)
    assert sent["reply_markup"].inline_keyboard[0][0].text == "Narxlar"


async def test_start_with_payload_and_bot_suffix(env):
    menu = await add_menu(env, "Bosh", "Salom!", start=True)
    await send(env, message("/start@ShopBot promo123"))
    assert env.tg.texts() == ["Salom!"]
    assert menu.id


async def test_button_runs_text_action_and_answers_callback(env):
    menu = await add_menu(env, "Bosh", "Salom!", start=True)
    button = await add_button(env, menu, "Narxlar", ActionType.text, "Narx: 10")
    await send(env, tap(button))
    assert env.tg.of("answer_callback_query")
    assert env.tg.texts()[-1] == "Narx: 10"


async def test_button_of_another_bot_is_rejected(env):
    other_owner = (await env.session.execute(select(User))).scalar_one()
    other = Bot(owner_id=other_owner.id, name="Other", token="987654321:ZZZdefGHIjklMNOpqrsTUVwxyz0123456789")
    env.session.add(other)
    await env.session.commit()
    foreign_menu = Menu(bot_id=other.id, title="x", message_text="secret", is_start=True)
    env.session.add(foreign_menu)
    await env.session.commit()
    foreign_button = await add_button(env, foreign_menu, "b", ActionType.text, "SECRET")

    await send(env, tap(foreign_button))
    assert "SECRET" not in env.tg.texts()


async def test_menu_with_photo_sends_caption_and_keyboard_in_one_message(env):
    menu = await add_menu(env, "Bosh", "Chegirma!", start=True, media=("photo", "AgACfile"))
    await add_button(env, menu, "Ha", ActionType.text, "ok")
    await send(env, message("/start"))

    photo = env.tg.last("send_photo")
    assert photo["photo"] == "AgACfile" and photo["caption"] == "Chegirma!"
    assert isinstance(photo["reply_markup"], InlineKeyboardMarkup)
    assert not env.tg.of("send_message")


async def test_long_text_with_media_is_split(env):
    menu = await add_menu(env, "Bosh", "x" * 1500, start=True, media=("video", "BAADfile"))
    await add_button(env, menu, "Ha", ActionType.text, "ok")
    await send(env, message("/start"))

    video = env.tg.last("send_video")
    assert "caption" not in video
    assert env.tg.last()["text"] == "x" * 1500
    assert isinstance(env.tg.last()["reply_markup"], InlineKeyboardMarkup)


async def test_rejected_media_falls_back_to_text(env):
    await add_menu(env, "Bosh", "Matn", start=True, media=("photo", "bad"))

    async def reject(**kw):
        raise BadRequest("wrong file identifier")

    env.tg.send_photo = reject
    await send(env, message("/start"))
    assert env.tg.texts() == ["Matn"]


async def test_invalid_html_is_sent_as_plain_text(env):
    await add_menu(env, "Bosh", "5 < 10 & 3 > 1", start=True)
    env.tg.fail_parse_once = True
    await send(env, message("/start"))
    sent = env.tg.last()
    assert sent["text"] == "5 < 10 & 3 > 1" and sent.get("parse_mode") is None


async def test_reply_keyboard_two_columns_and_text_match(env):
    menu = await add_menu(env, "Bosh", "Tanlang", start=True, mode="reply", columns=2)
    await add_button(env, menu, "Narxlar", ActionType.text, "Narx: 10", position=0)
    await add_button(env, menu, "Manzil", ActionType.text, "Toshkent", position=1)
    await add_button(env, menu, "Aloqa", ActionType.text, "+998", position=2)
    await send(env, message("/start"))

    markup = env.tg.last()["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert [[k.text for k in row] for row in markup.keyboard] == [["Narxlar", "Manzil"], ["Aloqa"]]

    await send(env, message("Manzil"))
    assert env.tg.texts()[-1] == "Toshkent"


async def test_opening_inline_menu_clears_reply_keyboard(env):
    reply_menu = await add_menu(env, "Bosh", "Tanlang", start=True, mode="reply")
    inline_menu = await add_menu(env, "Ichki", "Ichki menyu")
    await add_button(env, inline_menu, "Orqaga", ActionType.text, "x")
    await add_button(env, reply_menu, "Ichki", ActionType.menu, str(inline_menu.id))

    await send(env, message("/start"))
    await send(env, message("Ichki"))

    removal = [kw for kw in env.tg.of("send_message") if isinstance(kw.get("reply_markup"), ReplyKeyboardRemove)]
    assert removal and env.tg.of("delete_message")  # transient message cleaned up
    assert env.tg.last()["text"] == "Ichki menyu"
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.reply_keyboard_active is False


async def test_menu_without_buttons_after_reply_menu_removes_keyboard(env):
    reply_menu = await add_menu(env, "Bosh", "Tanlang", start=True, mode="reply")
    plain = await add_menu(env, "Oddiy", "Faqat matn")
    await add_button(env, reply_menu, "Oddiy", ActionType.menu, str(plain.id))
    await send(env, message("/start"))
    await send(env, message("Oddiy"))
    assert isinstance(env.tg.last()["reply_markup"], ReplyKeyboardRemove)


async def test_media_action_sends_the_file(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(
        env, menu, "Narx-list", ActionType.media,
        json.dumps({"type": "document", "file_id": "BQACdoc", "caption": "Narxlar"}),
    )
    await send(env, tap(button))
    doc = env.tg.last("send_document")
    assert doc["document"] == "BQACdoc" and doc["caption"] == "Narxlar"


async def test_broken_media_action_does_not_crash(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "Bad", ActionType.media, "not json")
    await send(env, tap(button))
    assert env.tg.texts()[-1] == "Bu fayl hozir mavjud emas."


async def test_unknown_text_gets_a_hint(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start"))
    await send(env, message("nimadir"))
    assert env.tg.texts()[-1] == router.HINT_TEXT


# ------------------------------------------------------------------ reliability

async def test_duplicate_update_is_processed_once(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start", update_id=42))
    await send(env, message("/start", update_id=42))
    assert env.tg.texts() == ["Salom"]


async def test_errors_never_escape_and_blocked_user_is_ignored(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    env.tg.blocked_chats.add(USER)
    await send(env, message("/start"))  # must not raise
    assert env.tg.texts() == []


async def test_group_messages_are_ignored(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    update = message("/start")
    update["message"]["chat"]["type"] = "group"
    await send(env, update)
    assert env.tg.calls == []


async def test_bot_without_start_menu_says_so(env):
    await send(env, message("/start"))
    assert "sozlanmoqda" in env.tg.texts()[-1]


# ------------------------------------------------------------------ forms

async def start_form_flow(env, fields, **form_kw):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    form = await add_form(env, fields, **form_kw)
    button = await add_button(env, menu, "Ariza", ActionType.form, str(form.id))
    await send(env, message("/start"))
    await send(env, tap(button))
    return form


async def submissions(env):
    return (await env.session.execute(select(FormSubmission))).scalars().all()


async def test_full_form_flow_saves_answers_and_notifies_admin(env):
    env.session.add(AdminLink(bot_id=env.bot.id, admin_tg_id=555))
    await env.session.commit()
    await start_form_flow(
        env,
        [("Ism", "text", {}), ("Yosh", "number", {}), ("Telefon", "phone", {}),
         ("Shahar", "choice", {"options": ["Toshkent", "Samarqand"]})],
        intro="Keling, tanishamiz",
    )
    assert env.tg.texts()[-2:] == ["Keling, tanishamiz", "<b>1/4</b>  Ism?"]

    await send(env, message("Ali Valiyev"))
    await send(env, message("25"))
    await send(env, message(None, contact={"phone_number": "998 90 123-45-67"}))
    markup = env.tg.last()["reply_markup"]
    assert [row[0].text for row in markup.keyboard] == ["Toshkent", "Samarqand", CANCEL_LABEL]
    await send(env, message("Samarqand"))

    saved = await submissions(env)
    assert len(saved) == 1
    assert [(a["label"], a["value"]) for a in saved[0].answers] == [
        ("Ism", "Ali Valiyev"), ("Yosh", "25"), ("Telefon", "+998901234567"), ("Shahar", "Samarqand"),
    ]
    assert saved[0].tg_user_id == USER and saved[0].username == "ali" and saved[0].full_name == "Ali"

    assert "Rahmat, qabul qilindi!" in env.tg.texts()
    for admin in (555, OWNER):
        assert any("Ali Valiyev" in t and "+998901234567" in t for t in env.tg.texts(admin))
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.form_id is None and state.form_step is None and state.form_data is None
    assert env.tg.texts()[-1] == "Salom"  # menu shown again


async def test_invalid_answer_repeats_the_question(env):
    await start_form_flow(env, [("Yosh", "number", {}), ("Email", "email", {})])
    await send(env, message("yigirma"))
    assert env.tg.texts()[-1] == "🔢 Iltimos, faqat raqam yuboring."
    await send(env, message("20"))
    await send(env, message("bu email emas"))
    assert "Email manzili noto" in env.tg.texts()[-1]
    await send(env, message("Ali@Example.com"))
    assert (await submissions(env))[0].answers[1]["value"] == "ali@example.com"


async def test_optional_question_can_be_skipped(env):
    await start_form_flow(env, [("Ism", "text", {}), ("Izoh", "text", {"required": False})])
    await send(env, message("Ali"))
    markup = env.tg.last()["reply_markup"]
    assert SKIP_LABEL in [k.text for row in markup.keyboard for k in row]
    await send(env, message(SKIP_LABEL))
    assert (await submissions(env))[0].answers[1]["value"] is None


async def test_required_question_cannot_be_skipped(env):
    await start_form_flow(env, [("Ism", "text", {})])
    await send(env, message(SKIP_LABEL))  # just treated as the (valid) text answer, not a skip
    assert (await submissions(env))[0].answers[0]["value"] == SKIP_LABEL


async def test_photo_and_location_answers(env):
    await start_form_flow(env, [("Rasm", "photo", {}), ("Joy", "location", {})])
    await send(env, message("matn"))
    assert "rasm yuboring" in env.tg.texts()[-1]
    await send(env, message(None, photo=[
        {"file_id": "small", "file_size": 10, "width": 90, "height": 90},
        {"file_id": "big", "file_size": 900, "width": 800, "height": 800},
    ]))
    await send(env, message(None, location={"latitude": 41.3, "longitude": 69.2}))
    answers = (await submissions(env))[0].answers
    assert answers[0]["value"] == "big" and answers[1]["value"] == "41.3,69.2"
    assert env.tg.of("send_photo") and env.tg.of("send_location")  # forwarded to the admin


async def test_cancel_button_and_command_leave_the_form(env):
    await start_form_flow(env, [("Ism", "text", {})])
    await send(env, message(CANCEL_LABEL))
    assert not await submissions(env)
    assert "Forma bekor qilindi." in env.tg.texts()
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.form_id is None

    await send(env, message("/start"))  # fresh start works afterwards
    assert env.tg.texts()[-1] == "Salom"


async def test_start_command_abandons_the_form(env):
    await start_form_flow(env, [("Ism", "text", {}), ("Yosh", "number", {})])
    await send(env, message("Ali"))
    await send(env, message("/start"))
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.form_id is None and not await submissions(env)


async def test_tapping_an_old_button_leaves_the_form(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    form = await add_form(env, [("Ism", "text", {})])
    form_button = await add_button(env, menu, "Ariza", ActionType.form, str(form.id))
    info_button = await add_button(env, menu, "Info", ActionType.text, "Ma'lumot", position=1)
    await send(env, message("/start"))
    await send(env, tap(form_button))
    await send(env, tap(info_button))
    assert env.tg.texts()[-1] == "Ma'lumot"
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.form_id is None


async def test_deleted_form_does_not_trap_the_user(env):
    form = await start_form_flow(env, [("Ism", "text", {})])
    await env.session.delete((await env.session.execute(select(FormField))).scalar_one())
    await env.session.commit()
    await send(env, message("Ali"))
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.form_id is None and form.id


async def test_form_of_another_bot_cannot_be_started(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "Ariza", ActionType.form, "9999")
    await send(env, message("/start"))
    await send(env, tap(button))
    assert env.tg.texts()[-1] == "Bu forma hozir mavjud emas."


async def test_shared_contact_outside_form_notifies_and_runs_button_action(env):
    menu = await add_menu(env, "Bosh", "Salom", start=True, mode="reply")
    await add_button(env, menu, "📞 Raqam yuborish", ActionType.text, "Rahmat, aloqaga chiqamiz", kind="contact")
    await send(env, message("/start"))
    markup = env.tg.last()["reply_markup"]
    assert markup.keyboard[0][0].request_contact is True

    await send(env, message(None, contact={"phone_number": "+998901112233"}))
    assert any("+998901112233" in t for t in env.tg.texts(OWNER))
    assert env.tg.texts()[-1] == "Rahmat, aloqaga chiqamiz"


async def test_unrequested_contact_is_ignored(env):
    await add_menu(env, "Bosh", "Salom", start=True)
    await send(env, message("/start"))
    count = len(env.tg.calls)
    await send(env, message(None, contact={"phone_number": "+998901112233"}))
    assert len(env.tg.calls) == count


# ------------------------------------------------------------------ pure helpers

def field(kind, **kw):
    return SimpleNamespace(type=kind, options=kw.get("options"), required=True)


@pytest.mark.parametrize("kind, msg, expected", [
    ("number", {"text": "12,5"}, (True, "12.5")),
    ("number", {"text": "1 000"}, (True, "1000")),
    ("number", {"text": "12a"}, (False, None)),
    ("phone", {"text": "+998 (90) 123-45-67"}, (True, "+998901234567")),
    ("phone", {"text": "123"}, (False, None)),
    ("phone", {"text": "salom"}, (False, None)),
    ("email", {"text": "A@b.co"}, (True, "a@b.co")),
    ("email", {"text": "a@b"}, (False, None)),
    ("text", {"text": "  salom  "}, (True, "salom")),
    ("text", {"text": ""}, (False, None)),
    ("text", {"text": "x" * 1001}, (False, None)),
])
def test_parse_answer(kind, msg, expected):
    ok, value = parse_answer(field(kind), msg)
    assert ok is expected[0]
    if ok:
        assert value == expected[1]


def test_choice_must_match_an_option():
    assert parse_answer(field("choice", options=["A", "B"]), {"text": "B"}) == (True, "B")
    assert parse_answer(field("choice", options=["A", "B"]), {"text": "C"})[0] is False


def test_submission_summary_escapes_html():
    text = format_submission("A<b>", {"id": 1, "username": "x"}, "Ali <script>", [
        {"label": "Izoh", "type": "text", "value": "<i>salom</i> & hayr"},
        {"label": "Rasm", "type": "photo", "value": "file"},
        {"label": "Bosh", "type": "text", "value": None},
    ])
    assert "<script>" not in text and "&lt;i&gt;salom&lt;/i&gt; &amp; hayr" in text
    assert "(rasm pastda)" in text and "Bosh:</b> —" in text
