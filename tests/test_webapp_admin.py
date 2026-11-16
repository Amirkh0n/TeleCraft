"""Admin Mini App API: access, dashboard, payments, customers, bots, platform message, system."""
import datetime as dt
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from core import plans
from core.config import settings
from helpers import FakeTG, OWNER
from models.bots import Bot
from models.plans import AccountPlan, AdminLog
from models.users import User
from test_webapp_api import sign
from webapp import api_admin
from webapp.auth import get_session

ADMIN = 9000
NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
async def ac(env, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_IDS", str(ADMIN))
    tg = FakeTG()

    async def fake_main_bot():
        return tg

    monkeypatch.setattr(api_admin, "main_bot", fake_main_bot)
    app = FastAPI()
    app.include_router(api_admin.router)

    async def override():
        yield env.session

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.env, c.tg = env, tg
        c.hdr = {"Authorization": f"tma {sign(ADMIN, name='Admin')}"}
        c.owner = {"Authorization": f"tma {sign(OWNER)}"}
        yield c


async def customer(ac) -> User:
    return await ac.env.session.get(User, ac.env.bot.owner_id)


async def paid_up(ac, plan="pro", months=1, approve=True):
    user = await customer(ac)
    pay = await plans.create_payment(ac.env.session, user, plan=plan, months=months)
    pid = pay.id
    await plans.attach_receipt(ac.env.session, pid, user.tg_id, "photo", "FILE")
    if approve is not None:
        await plans.decide(ac.env.session, pid, ADMIN, approve)
    return pid


async def test_only_admins_get_in(ac):
    assert (await ac.get("/api/v1/admin/me", headers=ac.hdr)).json() == {"admin": True}
    assert (await ac.get("/api/v1/admin/me", headers=ac.owner)).json() == {"admin": False}
    for path in ("/dashboard", "/payments", "/customers", "/bots", "/system"):
        assert (await ac.get(f"/api/v1/admin{path}", headers=ac.owner)).status_code == 403
        assert (await ac.get(f"/api/v1/admin{path}")).status_code == 401
    assert (await ac.post("/api/v1/admin/backup", headers=ac.owner)).status_code == 403


async def test_dashboard_counts_and_revenue(ac):
    await paid_up(ac, "pro", 1)
    await paid_up(ac, "pro", 1, approve=None)  # waiting for a decision
    data = (await ac.get("/api/v1/admin/dashboard", headers=ac.hdr)).json()
    assert data["bots"] == 1 and data["pending"] == 1 and data["month_revenue"] == 79_000
    assert data["plans"]["pro"] == 1 and len(data["revenue"]) == 6 and data["revenue"][-1]["total"] == 79_000


async def test_payments_list_decide_and_notify(ac):
    pid = await paid_up(ac, "start", approve=None)
    items = (await ac.get("/api/v1/admin/payments?status=pending", headers=ac.hdr)).json()["items"]
    assert [p["id"] for p in items] == [pid] and items[0]["receipt"] and items[0]["amount"] == 29_000
    res = await ac.post(f"/api/v1/admin/payments/{pid}/decide", json={"approve": False, "reason": "Summa mos emas"}, headers=ac.hdr)
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    note = ac.tg.of("send_message")[-1]
    assert note["chat_id"] == OWNER and "Summa mos emas" in note["text"]
    again = await ac.post(f"/api/v1/admin/payments/{pid}/decide", json={"approve": True}, headers=ac.hdr)
    assert again.status_code == 409
    assert (await ac.get("/api/v1/admin/payments?status=pending", headers=ac.hdr)).json()["items"] == []
    assert len((await ac.get("/api/v1/admin/payments?status=all", headers=ac.hdr)).json()["items"]) == 1
    log = (await ac.env.session.execute(select(AdminLog))).scalars().all()
    assert [x.action for x in log] == ["pay_no"]


async def test_approving_in_the_app_turns_the_plan_on(ac):
    pid = await paid_up(ac, "pro", approve=None)
    res = await ac.post(f"/api/v1/admin/payments/{pid}/decide", json={"approve": True}, headers=ac.hdr)
    assert res.json()["status"] == "approved"
    acc = await plans.get_account(ac.env.session, (await customer(ac)).id)
    assert acc.plan == "pro"
    assert "tasdiqlandi" in ac.tg.of("send_message")[-1]["text"]


async def test_receipt_is_streamed_from_telegram(ac, monkeypatch):
    pid = await paid_up(ac, approve=None)

    class File:
        async def download_as_bytearray(self):
            return bytearray(b"\xff\xd8jpeg")

    seen = []

    async def get_file(file_id):
        seen.append(file_id)
        return File()

    ac.tg.get_file = get_file
    res = await ac.get(f"/api/v1/admin/payments/{pid}/receipt", headers=ac.hdr)
    assert res.status_code == 200 and res.content == b"\xff\xd8jpeg" and res.headers["content-type"] == "image/jpeg" and seen == ["FILE"]
    assert (await ac.get("/api/v1/admin/payments/999/receipt", headers=ac.hdr)).status_code == 404


async def test_csv_lists_the_months_approved_payments(ac):
    await paid_up(ac, "pro")
    await paid_up(ac, "start", approve=False)
    res = await ac.get(f"/api/v1/admin/payments.csv?month={NOW:%Y-%m}", headers=ac.hdr)
    lines = res.text.lstrip("﻿").strip().splitlines()
    assert len(lines) == 2 and "79000" in lines[1] and "Pro tarifi" in lines[1]
    assert (await ac.get("/api/v1/admin/payments.csv?month=2026-13", headers=ac.hdr)).status_code == 422


async def test_customer_search_and_details(ac):
    user = await customer(ac)
    by_id = (await ac.get(f"/api/v1/admin/customers?q={user.tg_id}", headers=ac.hdr)).json()["items"]
    assert [c["id"] for c in by_id] == [user.id]
    assert (await ac.get("/api/v1/admin/customers?q=zzzzqq", headers=ac.hdr)).json()["items"] == []
    detail = (await ac.get(f"/api/v1/admin/customers/{user.id}", headers=ac.hdr)).json()
    assert detail["plan"] == "Free" and len(detail["bot_list"]) == 1 and detail["bot_list"][0]["id"] == ac.env.bot.id
    assert (await ac.get("/api/v1/admin/customers/99999", headers=ac.hdr)).status_code == 404


async def test_manual_grant_extend_and_remove(ac):
    user = await customer(ac)
    uid = user.id
    res = await ac.post(f"/api/v1/admin/customers/{uid}/plan", json={"plan": "pro", "days": 10, "reason": "sovg‘a"}, headers=ac.hdr)
    assert res.status_code == 200 and res.json()["plan"] == "Pro"
    acc = await plans.get_account(ac.env.session, uid)
    first_end = plans.as_utc(acc.expires_at)
    await ac.post(f"/api/v1/admin/customers/{uid}/plan", json={"plan": "pro", "days": 5}, headers=ac.hdr)
    await ac.env.session.refresh(acc)
    assert plans.as_utc(acc.expires_at) == first_end + dt.timedelta(days=5)
    res = await ac.post(f"/api/v1/admin/customers/{uid}/plan", json={"plan": "free", "days": 1}, headers=ac.hdr)
    assert res.json()["plan"] == "Free"
    assert (await ac.post(f"/api/v1/admin/customers/{uid}/plan", json={"plan": "gold"}, headers=ac.hdr)).status_code == 422
    actions = [x.action for x in (await ac.env.session.execute(select(AdminLog).order_by(AdminLog.id))).scalars()]
    assert actions == ["grant", "grant", "grant"]


async def test_trial_reset_and_customer_message(ac):
    user = await customer(ac)
    uid, tg_id = user.id, user.tg_id
    assert (await ac.post(f"/api/v1/admin/customers/{uid}/reset-trial", headers=ac.hdr)).status_code == 409
    await plans.start_trial(ac.env.session, user)
    assert (await ac.post(f"/api/v1/admin/customers/{uid}/reset-trial", headers=ac.hdr)).status_code == 200
    assert (await plans.get_account(ac.env.session, uid)).trial_used is False
    res = await ac.post(f"/api/v1/admin/customers/{uid}/message", json={"text": "Salom"}, headers=ac.hdr)
    assert res.status_code == 200 and ac.tg.of("send_message")[-1]["chat_id"] == tg_id
    assert (await ac.post(f"/api/v1/admin/customers/{uid}/message", json={"text": ""}, headers=ac.hdr)).status_code == 422


async def test_admin_can_stop_and_restart_a_bot(ac):
    bid = ac.env.bot.id
    rows = (await ac.get("/api/v1/admin/bots", headers=ac.hdr)).json()["items"]
    assert rows[0]["id"] == bid and rows[0]["active"]
    assert (await ac.post(f"/api/v1/admin/bots/{bid}/active", json={"active": False}, headers=ac.hdr)).json() == {"id": bid, "active": False}
    assert (await ac.env.session.get(Bot, bid)).is_active is False
    await ac.post(f"/api/v1/admin/bots/{bid}/active", json={"active": True}, headers=ac.hdr)
    assert (await ac.env.session.get(Bot, bid)).is_active is True
    assert (await ac.post("/api/v1/admin/bots/999/active", json={"active": True}, headers=ac.hdr)).status_code == 404


async def test_platform_message_goes_to_the_chosen_plan(ac, monkeypatch):
    delivered = []

    async def deliver(ids, text):
        delivered.append((sorted(ids), text))

    monkeypatch.setattr(api_admin, "_deliver", deliver)
    ac.env.session.add_all([User(tg_id=7001, full_name="A"), User(tg_id=7002, full_name="B")])
    await ac.env.session.commit()
    pro_user = (await ac.env.session.execute(select(User).where(User.tg_id == 7001))).scalar_one()
    ac.env.session.add(AccountPlan(user_id=pro_user.id, plan="pro", expires_at=NOW + dt.timedelta(days=5)))
    await ac.env.session.commit()
    res = await ac.post("/api/v1/admin/broadcast", json={"text": "Yangilik", "plan": "pro"}, headers=ac.hdr)
    assert res.json() == {"queued": 1}
    res = await ac.post("/api/v1/admin/broadcast", json={"text": "Hamma", "plan": "all"}, headers=ac.hdr)
    assert res.json()["queued"] == 4  # the owner, the admin himself, A and B
    await __import__("asyncio").sleep(0)
    assert delivered[0] == ([7001], "Yangilik")


async def test_system_page_and_log(ac, monkeypatch):
    data = (await ac.get("/api/v1/admin/system", headers=ac.hdr)).json()
    assert data["version"] == "0014_admin_log" and data["admins"] == 1 and data["log"] == []

    async def fake_backup(bot, admin_ids, engine, **kw):
        return len(admin_ids)

    monkeypatch.setattr(api_admin, "send_backup", fake_backup)
    assert (await ac.post("/api/v1/admin/backup", headers=ac.hdr)).json() == {"sent": 1}
    assert (await ac.get("/api/v1/admin/system", headers=ac.hdr)).json()["log"][0]["action"] == "backup"
