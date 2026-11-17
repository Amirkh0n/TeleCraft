"""Invite friends: 10 friends who each build a bot give the inviter a month of Start."""
import datetime as dt
from types import SimpleNamespace

from sqlalchemy import select

from constructor import handlers
from constructor.flows import referral as flow
from core import plans, referrals
from helpers import FakeTG, OWNER
from models.plans import AccountPlan
from models.referrals import Referral
from models.users import User
from test_home import Query, buttons, henv, make_msg, upd  # noqa: F401

NOW = dt.datetime.now(dt.UTC)


async def invite(env, tg_id, payload=None):
    return await referrals.register(env.session, tg_id, f"F{tg_id}", payload or f"ref_{OWNER}")


async def friend(env, tg_id):
    await invite(env, tg_id)
    return (await env.session.execute(select(User).where(User.tg_id == tg_id))).scalar_one()


async def test_register_only_new_users_and_never_self(henv):
    assert await invite(henv, 500) is True
    assert await invite(henv, 500) is False  # already known
    assert await invite(henv, OWNER) is False  # self
    assert await invite(henv, 501, "ref_999999") is False  # unknown inviter
    assert await invite(henv, 502, "ref_abc") is False and await invite(henv, 503, "hello") is False
    assert len((await henv.session.execute(select(Referral))).scalars().all()) == 1
    assert (await henv.session.execute(select(User).where(User.tg_id == 501))).scalar_one_or_none() is None


async def test_a_bot_counts_once_and_ten_give_start(henv):
    owner_id = henv.bot.owner_id
    for i in range(9):
        res = await referrals.activate(henv.session, (await friend(henv, 600 + i)).id)
        assert res == {"tg_id": OWNER, "done": i + 1, "rewarded": False}
    again = await friend(henv, 600)  # known user: a second link changes nothing
    assert await referrals.activate(henv.session, again.id) is None  # already counted
    assert await plans.get_account(henv.session, owner_id) is None
    res = await referrals.activate(henv.session, (await friend(henv, 700)).id)
    assert res["done"] == 10 and res["rewarded"] is True
    acc = await plans.get_account(henv.session, owner_id)
    assert acc.plan == "start" and 29 <= (plans.as_utc(acc.expires_at) - plans.utcnow()).days <= 30
    # the 11th friend does not pay out a second time
    res = await referrals.activate(henv.session, (await friend(henv, 701)).id)
    assert res["done"] == 11 and res["rewarded"] is False
    assert await referrals.progress(henv.session, owner_id) == (11, 0)
    assert (await referrals.info(henv.session, await henv.session.get(User, owner_id), "tc_bot"))["rewarded"] is True


async def test_joined_but_no_bot_does_not_count(henv):
    owner_id = henv.bot.owner_id
    await friend(henv, 800)
    assert await referrals.progress(henv.session, owner_id) == (0, 1)


async def test_reward_extends_a_better_plan_and_replaces_free_or_expired(henv):
    owner_id = henv.bot.owner_id
    end = NOW + dt.timedelta(days=10)
    henv.session.add(AccountPlan(user_id=owner_id, plan="pro", expires_at=end))
    await henv.session.commit()
    assert await referrals._reward(henv.session, owner_id, OWNER) is True
    acc = await plans.get_account(henv.session, owner_id)
    assert acc.plan == "pro" and 39 <= (plans.as_utc(acc.expires_at) - NOW).days <= 40  # +30 days on Pro, not a downgrade
    other = User(tg_id=77, full_name="x")
    henv.session.add(other)
    await henv.session.commit()
    other_id = other.id
    henv.session.add(AccountPlan(user_id=other_id, plan="start", expires_at=NOW - dt.timedelta(days=60)))
    await henv.session.commit()
    assert await referrals._reward(henv.session, other_id, 77) is True
    acc = await plans.get_account(henv.session, other_id)
    assert acc.plan == "start" and plans.state_of(acc, NOW)[1] == "active"


async def test_platform_admin_gets_no_reward(henv, monkeypatch):
    monkeypatch.setattr(plans.settings, "ADMIN_IDS", str(OWNER))
    assert await referrals._reward(henv.session, henv.bot.owner_id, OWNER) is False


async def test_start_with_invite_link_and_notice_to_inviter(henv):
    ctx = henv.ctx
    ctx.args = [f"ref_{OWNER}"]
    await handlers.start(upd(900, message=make_msg(), name="Do'st"), ctx)
    friend_user = (await henv.session.execute(select(User).where(User.tg_id == 900))).scalar_one()
    friend_id = friend_user.id
    ref = (await henv.session.execute(select(Referral).where(Referral.referred_id == friend_id))).scalar_one()
    assert ref.activated_at is None
    await flow.friend_built_bot(ctx, friend_id)
    sent = [kw for name, kw in ctx.bot.calls if name == "send_message"]
    assert sent[-1]["chat_id"] == OWNER and "1 / 10" in sent[-1]["text"]
    await flow.friend_built_bot(ctx, friend_id)  # no duplicate notice
    assert len([1 for name, _ in ctx.bot.calls if name == "send_message"]) == 1


async def test_referral_screen_shows_link_and_progress(henv):
    henv.ctx.bot = SimpleNamespace(username="tc_bot", sent=[])
    page = make_msg()
    await flow.show(upd(OWNER, query=Query("ref:home", page)), henv.ctx)
    text, kw = page.edits[-1]
    assert f"https://t.me/tc_bot?start=ref_{OWNER}" in text and "0</b> / 10" in text
    urls = [b.url for b in buttons(kw["reply_markup"]) if b.url]
    assert urls and urls[0].startswith("https://t.me/share/url?url=")
