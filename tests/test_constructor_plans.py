"""Main bot: paying with a receipt photo, the admins' decision, and plan messages on locked actions."""
from types import SimpleNamespace

import pytest

from constructor import handlers
from constructor.flows import plans as flow
from core import plans
from core.config import settings
from helpers import FakeTG, OWNER
from models.plans import PlanPayment
from models.users import User

ADMIN = 9000


class Msg:
    def __init__(self, **kw):
        self.replies, self.edits, self.__dict__.update(kw)
        self.caption_html = kw.get("caption_html", "cap")

    async def reply_text(self, text, **kw):
        self.replies.append((text, kw))

    async def edit_text(self, text, **kw):
        self.edits.append((text, kw))

    async def edit_caption(self, **kw):
        self.edits.append(("caption", kw))


def make_msg(**kw):
    m = Msg.__new__(Msg)
    m.replies, m.edits, m.caption_html = [], [], "cap"
    m.__dict__.update(kw)
    return m


class Query:
    def __init__(self, data, message):
        self.data, self.message, self.answers = data, message, []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.fixture
def cenv(env, monkeypatch):
    monkeypatch.setattr(settings, "PLANS_ENFORCE", True)
    monkeypatch.setattr(settings, "ADMIN_IDS", str(ADMIN))
    monkeypatch.setattr(settings, "PLAN_CARD_NUMBER", "8600 1111 2222 3333")
    monkeypatch.setattr(settings, "PLAN_CARD_HOLDER", "Ali Valiyev")
    for module in (flow, handlers, __import__("constructor.session", fromlist=["x"])):
        monkeypatch.setattr(module, "AsyncSessionLocal", env.maker)
    plans.invalidate()
    env.ctx = SimpleNamespace(user_data={}, bot=FakeTG())
    return env


def upd(user_id, *, message=None, query=None, name="Owner"):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, full_name=name, username="owner"),
                           message=message, callback_query=query)


async def test_paying_and_admin_approval_end_to_end(cenv):
    ctx = cenv.ctx
    # 1. the owner picks Pro for 1 month: the card is shown and a draft is created
    page = make_msg()
    query = Query("plx:pm:pro:1", page)
    await flow.make_payment(upd(OWNER, query=query), ctx)
    text = page.edits[-1][0]
    assert "79 000" in text and "8600 1111 2222 3333" in text and "Ali Valiyev" in text
    pay = (await cenv.session.execute(__import__("sqlalchemy").select(PlanPayment))).scalar_one()
    assert pay.status == "draft" and ctx.user_data["draft"]["id"] == pay.id
    # 2. the receipt photo goes to the admins with ✅/❌
    shot = make_msg(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="BIG")], document=None)
    await flow.handle_receipt(upd(OWNER, message=shot), ctx)
    sent = ctx.bot.of("send_photo")
    assert [c["chat_id"] for c in sent] == [ADMIN] and sent[0]["photo"] == "BIG"
    buttons = [b.callback_data for row in sent[0]["reply_markup"].inline_keyboard for b in row]
    assert buttons == [f"pla:ok:{pay.id}", f"pla:no:{pay.id}"]
    assert "Chek yuborildi" in shot.replies[-1][0]
    # 3. a stranger cannot decide
    admin_msg = make_msg()
    stranger = Query(f"pla:ok:{pay.id}", admin_msg)
    await flow.decide(upd(555, query=stranger), ctx)
    assert stranger.answers[-1][1] is True and await plans.get_account(cenv.session, pay.user_id) is None
    # 4. the admin approves: plan on, payer told, message marked
    ok = Query(f"pla:ok:{pay.id}", admin_msg)
    await flow.decide(upd(ADMIN, query=ok), ctx)
    acc = await plans.get_account(cenv.session, pay.user_id)
    assert acc.plan == "pro"
    told = [c for c in ctx.bot.of("send_message") if c["chat_id"] == OWNER]
    assert told and "Pro" in told[-1]["text"] and "tasdiqlandi" in told[-1]["text"]
    assert "Tasdiqlandi" in admin_msg.edits[-1][1]["caption"]
    # 5. a second tap does nothing
    again = Query(f"pla:no:{pay.id}", admin_msg)
    await flow.decide(upd(ADMIN, query=again), ctx)
    assert "allaqachon" in again.answers[-1][0]
    assert len([c for c in ctx.bot.of("send_message") if c["chat_id"] == OWNER]) == len(told)


async def test_rejection_tells_the_owner_and_changes_nothing(cenv):
    ctx = cenv.ctx
    user = await cenv.session.get(User, cenv.bot.owner_id)
    pay = await plans.create_payment(cenv.session, user, plan="start")
    pid = pay.id
    await plans.attach_receipt(cenv.session, pid, OWNER, "document", "DOC")
    await flow.decide(upd(ADMIN, query=Query(f"pla:no:{pid}", make_msg())), ctx)
    assert await plans.get_account(cenv.session, user.id) is None
    assert "tasdiqlanmadi" in ctx.bot.of("send_message")[-1]["text"]


async def test_receipt_without_a_draft_is_refused_politely(cenv):
    shot = make_msg(photo=[SimpleNamespace(file_id="P")], document=None)
    await flow.handle_receipt(upd(OWNER, message=shot), cenv.ctx)
    assert "topilmadi" in shot.replies[-1][0] and not cenv.ctx.bot.of("send_photo")


async def test_guard_turns_a_plan_error_into_a_message_with_a_tariff_button(cenv):
    async def locked(update, context):
        raise plans.PlanError("🔒 <b>Do‘kon bot</b> yopiq")

    page = make_msg()
    await flow.guard(locked)(upd(OWNER, query=Query("shpc:on", page)), cenv.ctx)
    text, kw = page.edits[-1]
    assert "yopiq" in text
    assert [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row] == ["plx:home"]


async def test_new_bot_button_is_blocked_on_free(cenv):
    page = make_msg()
    await handlers.add_bot_click(upd(OWNER, query=Query("add_bot", page)), cenv.ctx)
    assert "1 tagacha bot" in page.edits[-1][0]
    assert "state" not in cenv.ctx.user_data  # the token step did not start


async def test_plan_screen_shows_status_and_trial_button(cenv):
    page = make_msg()
    await flow.plan_home(upd(OWNER, query=Query("plx:home", page)), cenv.ctx)
    text, kw = page.edits[-1]
    data = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "Free" in text and "plx:p:pro" in data and "plx:trial" in data and "plx:b" in data
    trial = make_msg()
    await flow.start_trial(upd(OWNER, query=Query("plx:trial", trial)), cenv.ctx)
    assert "Pro" in trial.edits[-1][0]
    page2 = make_msg()
    await flow.plan_home(upd(OWNER, query=Query("plx:home", page2)), cenv.ctx)
    assert "plx:trial" not in [b.callback_data for row in page2.edits[-1][1]["reply_markup"].inline_keyboard for b in row]


async def test_pending_payments_can_be_resent_to_an_admin(cenv):
    user = await cenv.session.get(User, cenv.bot.owner_id)
    pay = await plans.create_payment(cenv.session, user, plan="pro")
    await plans.attach_receipt(cenv.session, pay.id, OWNER, "photo", "P")
    msg = make_msg()
    await flow.pending_command(upd(ADMIN, message=msg), cenv.ctx)
    assert len(cenv.ctx.bot.of("send_photo")) == 1
    await flow.pending_command(upd(555, message=msg), cenv.ctx)  # not an admin: silent
    assert len(cenv.ctx.bot.of("send_photo")) == 1
