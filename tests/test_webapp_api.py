"""Mini App API: authentication, ownership, and the editing operations."""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from telegram.error import Forbidden

from core.config import settings
from helpers import OWNER, add_button, add_form, add_menu
from models.bots import Bot
from models.button_actions import ActionType, ButtonAction
from models.menus import Menu
from models.user_sessions import UserSession
from models.users import User
from webapp import api as webapp_api
from webapp import api_audience
from webapp.auth import AuthError, get_session, validate_init_data
from webapp.telegram_html import check_html


def sign(user_id=OWNER, *, token=None, age=0, extra=None, name="Owner"):
    params = {"auth_date": str(int(time.time()) - age), "query_id": "AAH", "user": json.dumps({"id": user_id, "first_name": name})}
    params.update(extra or {})
    check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", (token or settings.TELEGRAM_TOKEN).encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


@pytest.fixture
async def client(env):
    app = FastAPI()
    app.include_router(webapp_api.router)
    app.include_router(api_audience.router)

    async def override():
        yield env.session

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.env = env
        c.hdr = {"Authorization": f"tma {sign()}"}
        yield c


# ---------------------------------------------------------------- authentication

def test_init_data_roundtrip_and_tampering():
    user = validate_init_data(sign(42), settings.TELEGRAM_TOKEN)
    assert user["id"] == 42
    tampered = sign(42).replace("42", "43", 1)
    with pytest.raises(AuthError):
        validate_init_data(tampered, settings.TELEGRAM_TOKEN)
    with pytest.raises(AuthError):
        validate_init_data(sign(42, token="999999:other_token_xxxxxxxxxxxxxxxxxxxxxxx"), settings.TELEGRAM_TOKEN)


def test_init_data_expiry_and_garbage():
    with pytest.raises(AuthError):
        validate_init_data(sign(42, age=2 * 24 * 3600), settings.TELEGRAM_TOKEN)
    with pytest.raises(AuthError):
        validate_init_data(sign(42, age=-3600), settings.TELEGRAM_TOKEN)  # issued in the future
    for junk in ("", "hash=abc", "a=b", "x" * 9000):
        with pytest.raises(AuthError):
            validate_init_data(junk, settings.TELEGRAM_TOKEN)


async def test_requests_without_valid_auth_are_rejected(client):
    assert (await client.get("/api/v1/bots")).status_code == 401
    assert (await client.get("/api/v1/bots", headers={"Authorization": "Bearer x"})).status_code == 401
    assert (await client.get("/api/v1/bots", headers={"Authorization": "tma garbage"})).status_code == 401


async def test_unknown_user_is_created_with_no_bots(client):
    response = await client.get("/api/v1/bots", headers={"Authorization": f"tma {sign(5555, name='New')}"})
    assert response.status_code == 200 and response.json() == []
    assert (await client.get("/api/v1/me", headers={"Authorization": f"tma {sign(5555, name='New')}"})).json()["name"] == "New"


# ---------------------------------------------------------------- ownership

async def test_cannot_touch_other_users_data(client):
    env = client.env
    menu = await add_menu(env, "Bosh", "Salom", start=True)
    button = await add_button(env, menu, "Ha", ActionType.text, "ok")
    form = await add_form(env, [("Ism", "text", {})])
    stranger = {"Authorization": f"tma {sign(999)}"}
    calls = [
        ("get", f"/api/v1/bots/{env.bot.id}"), ("get", f"/api/v1/bots/{env.bot.id}/stats"),
        ("post", f"/api/v1/bots/{env.bot.id}/menus", {"title": "x"}),
        ("patch", f"/api/v1/menus/{menu.id}", {"title": "x"}), ("delete", f"/api/v1/menus/{menu.id}"),
        ("post", f"/api/v1/menus/{menu.id}/buttons", {"text": "x"}),
        ("patch", f"/api/v1/buttons/{button.id}", {"text": "x"}), ("delete", f"/api/v1/buttons/{button.id}"),
        ("put", f"/api/v1/menus/{menu.id}/buttons/order", {"ids": [button.id]}),
        ("get", f"/api/v1/forms/{form.id}/submissions"), ("get", f"/api/v1/forms/{form.id}/export.csv"),
        ("put", f"/api/v1/forms/{form.id}", {"title": "x"}), ("delete", f"/api/v1/forms/{form.id}"),
    ]
    for method, url, *body in calls:
        response = await getattr(client, method)(url, headers=stranger, **({"json": body[0]} if body else {}))
        assert response.status_code == 404, (method, url, response.status_code)
    await env.session.refresh(menu)
    assert menu.title == "Bosh"


# ---------------------------------------------------------------- screens and buttons

async def test_bot_payload_contains_screens_buttons_and_actions(client):
    env = client.env
    menu = await add_menu(env, "Bosh", "Salom <b>dunyo</b>", start=True, mode="reply", columns=2)
    await add_button(env, menu, "Narx", ActionType.text, "10")
    await add_button(env, menu, "Aloqa", None, kind="contact", position=1)
    data = (await client.get(f"/api/v1/bots/{env.bot.id}", headers=client.hdr)).json()
    [screen] = data["menus"]
    assert screen["is_start"] and screen["keyboard_mode"] == "reply" and screen["columns"] == 2
    assert [(b["text"], b["kind"], b["action"]) for b in screen["buttons"]] == [
        ("Narx", "normal", {"type": "text", "value": "10"}), ("Aloqa", "contact", None)]
    assert "token" not in json.dumps(data).lower()


async def test_first_screen_becomes_start_and_limits_hold(client):
    env = client.env
    first = (await client.post(f"/api/v1/bots/{env.bot.id}/menus", json={"title": "Bosh"}, headers=client.hdr)).json()
    second = (await client.post(f"/api/v1/bots/{env.bot.id}/menus", json={"title": "Narx"}, headers=client.hdr)).json()
    assert first["is_start"] and not second["is_start"]
    assert (await client.post(f"/api/v1/bots/{env.bot.id}/menus", json={"title": ""}, headers=client.hdr)).status_code == 422


async def test_patch_screen_validates_html_and_switching_to_inline_drops_share_buttons(client):
    env = client.env
    menu = await add_menu(env, "Bosh", "x", start=True, mode="reply")
    await add_button(env, menu, "Aloqa", None, kind="contact")
    url = f"/api/v1/menus/{menu.id}"
    bad = await client.patch(url, json={"message_text": "<b>yopilmagan"}, headers=client.hdr)
    assert bad.status_code == 422 and "yopilmagan" in bad.json()["detail"]
    assert (await client.patch(url, json={"message_text": "<script>x</script>"}, headers=client.hdr)).status_code == 422
    ok = await client.patch(url, json={"message_text": "<b>Salom</b>", "keyboard_mode": "inline", "columns": 2}, headers=client.hdr)
    assert ok.status_code == 200 and ok.json()["buttons"] == [] and ok.json()["columns"] == 2
    assert (await client.patch(url, json={"columns": 3}, headers=client.hdr)).status_code == 422


async def test_remove_media_and_clear_text(client):
    env = client.env
    menu = await add_menu(env, "Bosh", "x", start=True, media=("photo", "AgAC"))
    out = (await client.patch(f"/api/v1/menus/{menu.id}", json={"remove_media": True, "message_text": ""}, headers=client.hdr)).json()
    assert out["media_type"] is None and out["message_text"] is None


async def test_button_crud_and_actions(client):
    env = client.env
    start = await add_menu(env, "Bosh", "x", start=True)
    other = await add_menu(env, "Narx", "y")
    form = await add_form(env, [("Ism", "text", {})])
    created = await client.post(f"/api/v1/menus/{start.id}/buttons", json={"text": "  Narx  "}, headers=client.hdr)
    assert created.status_code == 201 and created.json()["text"] == "Narx" and created.json()["action"] is None
    bid = created.json()["id"]
    url = f"/api/v1/buttons/{bid}"

    for action in ({"type": "text", "value": "Salom"}, {"type": "link", "value": "https://example.com"},
                   {"type": "menu", "value": str(other.id)}, {"type": "form", "value": str(form.id)},
                   {"type": "admin", "value": "123456"}):
        response = await client.patch(url, json={"action": action}, headers=client.hdr)
        assert response.status_code == 200 and response.json()["action"] == action
    assert (await env.session.execute(select(ButtonAction))).scalars().all()[0].action_type == ActionType.admin

    for bad in ({"type": "link", "value": "javascript:alert(1)"}, {"type": "menu", "value": "9999"},
                {"type": "form", "value": "9999"}, {"type": "admin", "value": "abc"}, {"type": "text", "value": "<i>x"},
                {"type": "media", "value": "x"}):
        assert (await client.patch(url, json={"action": bad}, headers=client.hdr)).status_code == 422, bad

    cleared = await client.patch(url, json={"clear_action": True}, headers=client.hdr)
    assert cleared.json()["action"] is None
    assert (await client.delete(url, headers=client.hdr)).status_code == 204
    assert (await client.delete(url, headers=client.hdr)).status_code == 404


async def test_action_cannot_point_to_another_bots_screen(client):
    env = client.env
    start = await add_menu(env, "Bosh", "x", start=True)
    button = await add_button(env, start, "Ha")
    other_bot = Bot(owner_id=env.bot.owner_id, name="B2", token="987654321:ZZZdefGHIjklMNOpqrsTUVwxyz0123456789")
    env.session.add(other_bot)
    await env.session.commit()
    foreign = Menu(bot_id=other_bot.id, title="f", is_start=True)
    env.session.add(foreign)
    await env.session.commit()
    response = await client.patch(f"/api/v1/buttons/{button.id}", json={"action": {"type": "menu", "value": str(foreign.id)}},
                                  headers=client.hdr)
    assert response.status_code == 422


async def test_contact_buttons_need_reply_keyboard_and_are_unique(client):
    env = client.env
    inline = await add_menu(env, "Bosh", "x", start=True)
    reply = await add_menu(env, "Reply", "y", mode="reply")
    assert (await client.post(f"/api/v1/menus/{inline.id}/buttons", json={"text": "Raqam", "kind": "contact"},
                              headers=client.hdr)).status_code == 422
    body = {"text": "Raqam", "kind": "contact"}
    assert (await client.post(f"/api/v1/menus/{reply.id}/buttons", json=body, headers=client.hdr)).status_code == 201
    assert (await client.post(f"/api/v1/menus/{reply.id}/buttons", json=body, headers=client.hdr)).status_code == 409


async def test_button_limit_and_reorder(client):
    env = client.env
    menu = await add_menu(env, "Bosh", "x", start=True)
    ids = []
    for i in range(3):
        ids.append((await client.post(f"/api/v1/menus/{menu.id}/buttons", json={"text": f"B{i}"}, headers=client.hdr)).json()["id"])
    out = await client.put(f"/api/v1/menus/{menu.id}/buttons/order", json={"ids": list(reversed(ids))}, headers=client.hdr)
    assert [b["id"] for b in out.json()["buttons"]] == list(reversed(ids))
    assert (await client.put(f"/api/v1/menus/{menu.id}/buttons/order", json={"ids": ids[:2]}, headers=client.hdr)).status_code == 422
    for i in range(webapp_api.MAX_BUTTONS - 3):
        assert (await client.post(f"/api/v1/menus/{menu.id}/buttons", json={"text": "x"}, headers=client.hdr)).status_code == 201
    assert (await client.post(f"/api/v1/menus/{menu.id}/buttons", json={"text": "x"}, headers=client.hdr)).status_code == 409


async def test_delete_screen_cleans_up_references(client):
    env = client.env
    start = await add_menu(env, "Bosh", "x", start=True)
    doomed = await add_menu(env, "Narx", "y")
    await add_button(env, doomed, "Ichki", ActionType.text, "z")
    opener = await add_button(env, start, "Narxga", ActionType.menu, str(doomed.id))
    env.session.add(UserSession(bot_id=env.bot.id, tg_user_id=5, current_menu_id=doomed.id))
    await env.session.commit()

    assert (await client.delete(f"/api/v1/menus/{start.id}", headers=client.hdr)).status_code == 409
    assert (await client.delete(f"/api/v1/menus/{doomed.id}", headers=client.hdr)).status_code == 204

    data = (await client.get(f"/api/v1/bots/{env.bot.id}", headers=client.hdr)).json()
    assert [m["id"] for m in data["menus"]] == [start.id]
    assert data["menus"][0]["buttons"][0]["id"] == opener.id and data["menus"][0]["buttons"][0]["action"] is None
    state = (await env.session.execute(select(UserSession))).scalar_one()
    assert state.current_menu_id == start.id


# ---------------------------------------------------------------- media upload

def fake_child(env, monkeypatch, *, fail=None):
    sent = []

    class Child:
        async def send_photo(self, **kw):
            if fail:
                raise fail
            sent.append(("photo", kw))
            return SimpleNamespace(message_id=1, photo=[SimpleNamespace(file_id="child-photo")])

        async def send_document(self, **kw):
            sent.append(("document", kw))
            return SimpleNamespace(message_id=1, document=SimpleNamespace(file_id="child-doc"))

        async def delete_message(self, **kw):
            pass

    async def get_client(token):
        return Child()

    monkeypatch.setattr(webapp_api, "get_client", get_client)
    return sent


async def test_screen_media_upload_goes_through_the_child_bot(client, monkeypatch):
    env = client.env
    sent = fake_child(env, monkeypatch)
    menu = await add_menu(env, "Bosh", "x", start=True)
    png = {"file": ("a.png", b"\x89PNG" + b"0" * 100, "image/png")}
    response = await client.post(f"/api/v1/menus/{menu.id}/media", headers=client.hdr, files=png)
    assert response.status_code == 200 and response.json()["media_type"] == "photo"
    assert sent[0][1]["chat_id"] == OWNER
    await env.session.refresh(menu)
    assert menu.media_file_id == "child-photo"


async def test_upload_errors_are_actionable(client, monkeypatch):
    env = client.env
    menu = await add_menu(env, "Bosh", "x", start=True)
    fake_child(env, monkeypatch, fail=Forbidden("bot can't initiate conversation"))
    png = {"file": ("a.png", b"data", "image/png")}
    blocked = await client.post(f"/api/v1/menus/{menu.id}/media", headers=client.hdr, files=png)
    assert blocked.status_code == 409 and "/start" in blocked.json()["detail"]
    empty = await client.post(f"/api/v1/menus/{menu.id}/media", headers=client.hdr, files={"file": ("a.png", b"", "image/png")})
    assert empty.status_code == 422
    monkeypatch.setattr(webapp_api, "PHOTO_LIMIT", 10)
    big = await client.post(f"/api/v1/menus/{menu.id}/media", headers=client.hdr,
                            files={"file": ("a.png", b"x" * 50, "image/png")})
    assert big.status_code == 413


async def test_button_media_action_stores_json_and_hides_file_id(client, monkeypatch):
    env = client.env
    fake_child(env, monkeypatch)
    menu = await add_menu(env, "Bosh", "x", start=True)
    button = await add_button(env, menu, "Katalog")
    response = await client.post(f"/api/v1/buttons/{button.id}/media", headers=client.hdr, data={"caption": "<b>Narxlar</b>"},
                                 files={"file": ("k.pdf", b"%PDF" + b"0" * 50, "application/pdf")})
    assert response.status_code == 200
    assert response.json()["action"] == {"type": "media", "value": None, "media": {"type": "document", "caption": "<b>Narxlar</b>"}}
    stored = json.loads((await env.session.execute(select(ButtonAction))).scalar_one().value)
    assert stored == {"type": "document", "file_id": "child-doc", "caption": "<b>Narxlar</b>"}
    assert "child-doc" not in response.text


# ---------------------------------------------------------------- forms

async def test_form_lifecycle_with_validation(client):
    env = client.env
    created = (await client.post(f"/api/v1/bots/{env.bot.id}/forms", json={"title": "Ariza"}, headers=client.hdr)).json()
    url = f"/api/v1/forms/{created['id']}"
    body = {"title": "Ariza", "final_message": "Rahmat", "notify_admins": False, "fields": [
        {"label": "Ism", "prompt": "Ismingiz?", "type": "text"},
        {"label": "Shahar", "prompt": "Qayerdan?", "type": "choice", "options": ["A", "B", "A", " "]},
        {"label": "Rasm", "prompt": "Rasm", "type": "photo", "required": False, "options": ["ignored"]},
    ]}
    saved = await client.put(url, json=body, headers=client.hdr)
    assert saved.status_code == 200
    fields = saved.json()["fields"]
    assert [f["options"] for f in fields] == [None, ["A", "B"], None] and fields[2]["required"] is False
    assert saved.json()["notify_admins"] is False

    for bad_field in ({"label": "x", "prompt": "q", "type": "bogus"},
                      {"label": "x", "prompt": "q", "type": "choice", "options": ["only"]},
                      {"label": "x", "prompt": "<b>q", "type": "text"}):
        response = await client.put(url, json={"title": "Ariza", "fields": [bad_field]}, headers=client.hdr)
        assert response.status_code == 422, bad_field
    assert len((await client.get(f"/api/v1/bots/{env.bot.id}", headers=client.hdr)).json()["forms"][0]["fields"]) == 3


async def test_form_submissions_csv_and_delete(client):
    env = client.env
    form = await add_form(env, [("Ism", "text", {})])
    from models.forms import FormSubmission
    env.session.add(FormSubmission(form_id=form.id, bot_id=env.bot.id, tg_user_id=7, username="ali", full_name="Ali",
                                   answers=[{"label": "Ism", "type": "text", "value": "=HYPERLINK()"}]))
    menu = await add_menu(env, "Bosh", "x", start=True)
    await add_button(env, menu, "Ariza", ActionType.form, str(form.id))
    await env.session.commit()

    subs = (await client.get(f"/api/v1/forms/{form.id}/submissions", headers=client.hdr)).json()
    assert subs[0]["username"] == "ali" and subs[0]["answers"][0]["value"] == "=HYPERLINK()"
    csv_response = await client.get(f"/api/v1/forms/{form.id}/export.csv", headers=client.hdr)
    assert csv_response.headers["content-type"].startswith("text/csv") and "'=HYPERLINK()" in csv_response.content.decode("utf-8-sig")

    assert (await client.delete(f"/api/v1/forms/{form.id}", headers=client.hdr)).status_code == 204
    data = (await client.get(f"/api/v1/bots/{env.bot.id}", headers=client.hdr)).json()
    assert data["forms"] == [] and data["menus"][0]["buttons"][0]["action"] is None


async def test_stats_endpoint(client):
    env = client.env
    stats = (await client.get(f"/api/v1/bots/{env.bot.id}/stats", headers=client.hdr)).json()
    assert stats["total"] == 0 and "sources" in stats
    assert (await env.session.get(User, env.bot.owner_id)).tg_id == OWNER


# ---------------------------------------------------------------- telegram html

@pytest.mark.parametrize("text, ok", [
    ("<b>a</b> <i>b</i> <a href='https://x.com'>c</a>", True),
    ("plain & text", True), ("<b><i>x</i></b>", True), ("<b>x</i>", False), ("<b>x", False),
    ("<script>x</script>", False), ("<a>x</a>", False), ("</b>", False), ("<tg-spoiler>x</tg-spoiler>", True),
])
def test_check_html(text, ok):
    assert (check_html(text) is None) is ok


# ---------------------------------------------------------------- serving

async def test_editor_is_served_and_api_requires_auth():
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        page = await c.get("/app/")
        assert page.status_code == 200 and "TeleCraft muharriri" in page.text
        assert (await c.get("/app/app.js")).status_code == 200
        assert (await c.get("/app/styles.css")).headers["content-type"].startswith("text/css")
        assert (await c.get("/api/v1/bots")).status_code == 401


def test_editor_url_needs_https(monkeypatch):
    from webapp import editor_url
    for value, expected in (("https://bot.example.com", "https://bot.example.com/app/"),
                            ("https://bot.example.com/", "https://bot.example.com/app/"),
                            ("http://bot.example.com", None), ("https://your-app.onrender.com", None), ("", None)):
        monkeypatch.setattr(settings, "PUBLIC_BASE_URL", value)
        assert editor_url() == expected
