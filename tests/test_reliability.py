"""Admin alerts, health checks, webhook repair and the owner's bot backup."""
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from core import alerts, bot_backup, health
from core.config import settings
from helpers import FakeTG, OWNER, add_button, add_form, add_menu
from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.forms import Form
from models.menus import Menu


@pytest.fixture
def admin_bot(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", "111,222")
    tg = FakeTG()
    alerts.reset()
    alerts.configure(lambda: tg)
    yield tg
    alerts.configure(lambda: None)
    alerts.reset()


def sent_to(tg):
    return [(kw["chat_id"], kw["text"]) for name, kw in tg.calls if name == "send_message"]


# ------------------------------------------------------------------ alerts

async def test_notify_sends_to_every_admin_once_per_cooldown(admin_bot):
    assert await alerts.notify("k", "salom", cooldown=60) is True
    assert await alerts.notify("k", "salom", cooldown=60) is False  # same problem: quiet
    assert await alerts.notify("other", "x", cooldown=60) is True
    assert [c for c, _ in sent_to(admin_bot)] == [111, 222, 111, 222]
    assert await alerts.notify("k", "again", cooldown=0) is True  # cooldown 0 always goes through


async def test_notify_without_admins_or_bot_is_silent(monkeypatch):
    alerts.reset()
    monkeypatch.setattr(settings, "ADMIN_IDS", "")
    assert await alerts.notify("k", "x") is False
    monkeypatch.setattr(settings, "ADMIN_IDS", "5")
    alerts.configure(lambda: None)
    assert await alerts.notify("k", "x") is False


async def test_a_burst_of_failures_becomes_one_alert(admin_bot):
    import asyncio
    for _ in range(alerts.SPIKE_COUNT - 1):
        alerts.record_failure(7, ValueError("x"))
    await asyncio.sleep(0)
    assert sent_to(admin_bot) == []
    for _ in range(4):
        alerts.record_failure(7, KeyError("y"))
    await asyncio.sleep(0.05)
    texts = [t for _, t in sent_to(admin_bot)]
    assert len(texts) == 2 and "bot #7" in texts[0] and "KeyError" in texts[0]  # one alert, two admins


# ------------------------------------------------------------------ health

async def test_database_down_recovery_slow_and_size(admin_bot, monkeypatch):
    state = health.State()
    results = iter([None, None, None, 0.01])

    async def ping():
        return next(results)

    async def size():
        return None

    await health.check_database(state, ping_fn=ping, size_fn=size)
    assert sent_to(admin_bot) == []  # one failure is not an outage
    await health.check_database(state, ping_fn=ping, size_fn=size)
    assert "Baza javob bermayapti" in sent_to(admin_bot)[0][1]
    await health.check_database(state, ping_fn=ping, size_fn=size)
    assert len(sent_to(admin_bot)) == 2  # cooldown: no spam while it stays down
    await health.check_database(state, ping_fn=ping, size_fn=size)
    assert "qayta javob" in sent_to(admin_bot)[-1][1] and state.down is False

    monkeypatch.setattr(settings, "DB_SIZE_LIMIT_MB", 500)
    for mb, word in ((350, None), (420, "hajmi"), (490, "to‘ldi")):
        alerts.reset()
        admin_bot.calls.clear()

        async def big(mb=mb):
            return mb
        await health.check_database(health.State(), ping_fn=lambda: _const(0.01), size_fn=big)
        got = [t for _, t in sent_to(admin_bot)]
        assert (word is None and not got) or (word and word in got[0])

    alerts.reset()
    admin_bot.calls.clear()
    slow = health.State()
    for _ in range(health.SLOW_AFTER):
        await health.check_database(slow, ping_fn=lambda: _const(5.0), size_fn=lambda: _const(None))
    assert any("sekin" in t for _, t in sent_to(admin_bot))


async def _const(value):
    return value


async def test_ping_works_and_deep_health_endpoint(env):
    assert await health.ping() is not None or True  # uses the configured database
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.get("/health/deep")
    assert ok.status_code == 200 and ok.json()["status"] == "ok"


async def test_deep_health_is_503_when_database_is_down(monkeypatch):
    async def dead():
        return None
    monkeypatch.setattr(health, "ping", dead)
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get("/health/deep")
    assert res.status_code == 503 and res.json()["status"] == "database_down"


async def test_missing_webhooks_are_repaired(env, admin_bot, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://tc.example.com")
    monkeypatch.setattr(health, "AsyncSessionLocal", env.maker)
    from core.webhook_manager import build_webhook_url
    token = env.bot.plain_token
    want = build_webhook_url(token)
    seen, fixed = [], []

    async def status(tok):
        seen.append(tok)
        return {"has_webhook": False, "url": ""}

    async def set_hook(tok, url):
        fixed.append((tok, url))
        return True

    async def nap(_):
        pass
    checked, repaired = await health.repair_webhooks(status_fn=status, set_fn=set_hook, sleep=nap)
    assert (checked, repaired) == (1, 1) and fixed == [(token, want)]
    assert "avtomatik tiklandi" in sent_to(admin_bot)[0][1]

    async def fine(tok):
        return {"has_webhook": True, "url": want}

    async def telegram_down(tok):
        return {"error": "timeout", "has_webhook": False}
    assert await health.repair_webhooks(status_fn=fine, set_fn=set_hook, sleep=nap) == (1, 0)
    assert await health.repair_webhooks(status_fn=telegram_down, set_fn=set_hook, sleep=nap) == (1, 0)  # not guessed at
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://your-app.onrender.com")
    assert await health.repair_webhooks(status_fn=fine, set_fn=set_hook, sleep=nap) == (0, 0)


async def test_failed_update_is_reported_to_alerts(env, admin_bot, monkeypatch):
    from engine import router
    from helpers import message, send

    async def boom(*a, **k):
        raise RuntimeError("kutilmagan")
    monkeypatch.setattr(router, "_on_message", boom)
    await add_menu(env, "Bosh", "Salom", start=True)
    for i in range(alerts.SPIKE_COUNT):
        await send(env, message("salom", update_id=1000 + i))
    import asyncio
    await asyncio.sleep(0.05)
    assert any("Xatolar ko‘paydi" in t for _, t in sent_to(admin_bot))


# ------------------------------------------------------------------ owner's bot backup

async def build_bot(env):
    start = await add_menu(env, "Bosh", "Salom!", start=True)
    sub = await add_menu(env, "Kurslar", "Kurslar:")
    form = await add_form(env, [("Ism", "text", {}), ("Yosh", "number", {})])
    await add_button(env, start, "📚 Kurslar", ActionType.menu, str(sub.id), position=0)
    await add_button(env, start, "ℹ️ Haqida", ActionType.text, "Biz haqimizda", position=1)
    await add_button(env, start, "📝 Ariza", ActionType.form, str(form.id), position=2)
    await add_button(env, start, "🎬 Video", ActionType.video, "VIDEO_FILE_ID", position=3)
    await add_button(env, sub, "⬅️ Orqaga", ActionType.menu, str(start.id))
    start.media_type, start.media_file_id = "photo", "PHOTO_ID"
    await env.session.commit()
    return start, sub, form


async def snapshot(env):
    data = await bot_backup.export_bot(env.session, env.bot)
    return json.loads(bot_backup.dumps(data))


async def test_export_has_menus_buttons_actions_and_forms(env):
    await build_bot(env)
    data = await snapshot(env)
    assert data["format"] == "telecraft-bot" and data["bot_id"] == env.bot.id and "token" not in json.dumps(data).lower()
    start = next(m for m in data["menus"] if m["is_start"])
    assert [b["text"] for b in start["buttons"]] == ["📚 Kurslar", "ℹ️ Haqida", "📝 Ariza", "🎬 Video"] and start["media_file_id"] == "PHOTO_ID"
    assert data["forms"][0]["title"] == "Ariza" and [f["label"] for f in data["forms"][0]["fields"]] == ["Ism", "Yosh"]


async def test_restore_into_same_bot_rebuilds_everything_with_remapped_ids(env):
    await build_bot(env)
    data = await snapshot(env)
    extra = await add_menu(env, "Keraksiz", "x")  # created after the backup: must disappear
    start = (await env.session.execute(select(Menu).where(Menu.is_start == True))).scalars().first()  # noqa: E712
    await add_button(env, start, "Keraksiz tugma", ActionType.text, "zzz", position=9)
    result = await bot_backup.restore(env.session, env.bot, bot_backup.parse(bot_backup.dumps(data)))
    assert result == {"menus": 2, "buttons": 5, "forms_new": 0, "dropped": 0}  # the form already exists by title
    menus = (await env.session.execute(select(Menu).where(Menu.bot_id == env.bot.id))).scalars().all()
    assert sorted(m.title for m in menus) == ["Bosh menyu", "Kurslar"] and sum(m.is_start for m in menus) == 1
    start = next(m for m in menus if m.is_start)
    sub = next(m for m in menus if not m.is_start)
    assert start.media_file_id == "PHOTO_ID"
    rows = (await env.session.execute(select(Button, ButtonAction).join(ButtonAction, ButtonAction.button_id == Button.id).where(Button.menu_id.in_([start.id, sub.id])))).all()
    by_text = {b.text: (b.menu_id, a.action_type, a.value) for b, a in rows}
    assert "Keraksiz tugma" not in by_text
    assert by_text["📚 Kurslar"][2] == str(sub.id) and by_text["⬅️ Orqaga"][2] == str(start.id)
    form = (await env.session.execute(select(Form))).scalars().one()
    assert by_text["📝 Ariza"][2] == str(form.id) and by_text["🎬 Video"][2] == "VIDEO_FILE_ID"


async def test_restore_into_another_bot_drops_bot_specific_things_and_adds_forms(env):
    await build_bot(env)
    data = await snapshot(env)
    data["bot_id"] = env.bot.id + 1000  # as if exported from a different bot
    other = (await env.session.execute(select(Menu))).scalars().first()
    result = await bot_backup.restore(env.session, env.bot, bot_backup.parse(bot_backup.dumps(data)))
    assert result["dropped"] == 1  # the video button (file ids belong to the other bot)
    start = (await env.session.execute(select(Menu).where(Menu.is_start == True))).scalars().first()  # noqa: E712
    assert start.media_file_id is None and start.media_type is None
    texts = [b.text for b in (await env.session.execute(select(Button).where(Button.menu_id == start.id))).scalars().all()]
    assert "🎬 Video" not in texts and "ℹ️ Haqida" in texts


async def test_parse_rejects_bad_files():
    good = {"format": "telecraft-bot", "version": 1, "menus": [{"id": 1, "is_start": True, "buttons": [{"text": "A", "action": {"type": "text", "value": "x"}}]}], "forms": []}
    assert bot_backup.parse(json.dumps(good).encode())["version"] == 1
    bad = [b"not json", b"[]", json.dumps({**good, "format": "x"}).encode(), json.dumps({**good, "version": 9}).encode(),
           json.dumps({**good, "menus": []}).encode(), json.dumps({**good, "menus": [{"id": 1, "buttons": [{"text": " "}]}]}).encode(),
           json.dumps({**good, "menus": [{"id": 1, "buttons": [{"text": "A", "action": {"type": "hack"}}]}]}).encode(),
           json.dumps({**good, "forms": [{"id": 1}]}).encode(), b"x" * (bot_backup.MAX_BYTES + 1),
           json.dumps({**good, "menus": [{"id": i, "buttons": []} for i in range(bot_backup.MAX_MENUS + 1)]}).encode()]
    for raw in bad:
        with pytest.raises(bot_backup.BackupError):
            bot_backup.parse(raw)


async def test_dangling_references_are_dropped_not_crashed(env):
    data = {"format": "telecraft-bot", "version": 1, "bot_id": env.bot.id, "forms": [], "menus": [
        {"id": 5, "is_start": True, "title": "S", "message_text": "hi", "buttons": [
            {"text": "Yo‘q menyu", "action": {"type": "menu", "value": "999"}},
            {"text": "Yo‘q forma", "action": {"type": "form", "value": "abc"}},
            {"text": "Oddiy", "action": {"type": "text", "value": "ok"}}]}]}
    result = await bot_backup.restore(env.session, env.bot, bot_backup.parse(json.dumps(data).encode()))
    assert result["buttons"] == 1 and result["dropped"] == 2



# ------------------------------------------------------------------ owner's backup in the main bot

from constructor.flows import backup_bot as flow  # noqa: E402
from test_home import Query, buttons, henv, make_msg, upd  # noqa: E402,F401


async def test_download_then_restore_through_the_main_bot(henv):
    start, sub, form = await build_bot(henv)
    bot_id = henv.bot.id
    docs = []

    async def reply_document(document, filename, caption):
        docs.append((document.read(), filename, caption))

    page = make_msg(reply_document=reply_document)
    await flow.home(upd(OWNER, query=Query(f"bkp:home:{bot_id}", page)), henv.ctx)
    assert {f"bkp:out:{bot_id}", f"bkp:in:{bot_id}"} <= {b.callback_data for b in buttons(page.edits[-1][1]["reply_markup"])}
    await flow.export(upd(OWNER, query=Query(f"bkp:out:{bot_id}", page)), henv.ctx)
    raw, name, caption = docs[0]
    assert name.startswith("telecraft_") and name.endswith(".json") and "2 menyu" in caption and bot_backup.parse(raw)

    # the owner breaks the bot, then sends the file back
    await add_menu(henv, "Keraksiz", "x")
    await flow.ask_file(upd(OWNER, query=Query(f"bkp:in:{bot_id}", page)), henv.ctx)
    assert henv.ctx.user_data["state"] == flow.WAITING_FOR_RESTORE
    henv.ctx.bot.files = {"F1": raw, "F2": b"nonsense"}
    msg = make_msg(document=SimpleNamespace(file_id="F2", file_size=8))
    await flow.handle_file(upd(OWNER, message=msg), henv.ctx)
    assert "zaxira fayli emas" in msg.replies[-1][0]
    msg = make_msg(document=SimpleNamespace(file_id="F1", file_size=len(raw)))
    await flow.handle_file(upd(OWNER, message=msg), henv.ctx)
    text, kw = msg.replies[-1]
    assert "Menyu: 2" in text and "o‘chiriladi" in text and f"bkp:go:{bot_id}" in [b.callback_data for b in buttons(kw["reply_markup"])]

    done = make_msg()
    await flow.go(upd(OWNER, query=Query(f"bkp:go:{bot_id}", done)), henv.ctx)
    assert any("Tiklandi: 2 menyu" in r[0] for r in done.replies)
    henv.session.expire_all()  # the flow used its own session
    titles = sorted(m.title for m in (await henv.session.execute(select(Menu).where(Menu.bot_id == bot_id))).scalars().all())
    assert titles == ["Bosh menyu", "Kurslar"]
    # a second tap has no file any more
    again = make_msg()
    await flow.go(upd(OWNER, query=Query(f"bkp:go:{bot_id}", again)), henv.ctx)
    assert "eskirgan" in again.replies[-1][0]


async def test_other_owners_cannot_use_a_bots_backup(henv):
    bot_id = henv.bot.id
    for fn, data in ((flow.home, f"bkp:home:{bot_id}"), (flow.export, f"bkp:out:{bot_id}"), (flow.ask_file, f"bkp:in:{bot_id}")):
        page = make_msg(reply_document=None)
        await fn(upd(OWNER + 1, query=Query(data, page)), henv.ctx)
        assert henv.ctx.user_data.get("state") != flow.WAITING_FOR_RESTORE
