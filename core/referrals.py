"""Invite friends: 10 friends who each build a bot earn the inviter a month of Start (once per person)."""
from datetime import timedelta

from sqlalchemy import func, select

from core import plans
from engine.booking_time import as_utc, utcnow
from models.referrals import Referral
from models.users import User

PREFIX = "ref_"
NEED = 10
REWARD_PLAN = plans.START
REWARD_DAYS = 30


def link(main_username: str, tg_id: int) -> str:
    return f"https://t.me/{main_username.lstrip('@')}?start={PREFIX}{tg_id}"


def parse(payload: str) -> int | None:
    if not payload.startswith(PREFIX) or not payload[len(PREFIX):].isdigit():
        return None
    return int(payload[len(PREFIX):])


async def register(session, tg_id: int, full_name: str | None, payload: str) -> bool:
    """A brand-new person opened the main bot through an invite link. Existing users and self-invites are ignored."""
    inviter_tg = parse(payload)
    if inviter_tg is None or inviter_tg == tg_id:
        return False
    if (await session.execute(select(User.id).where(User.tg_id == tg_id))).first() is not None:
        return False
    inviter = (await session.execute(select(User).where(User.tg_id == inviter_tg))).scalar_one_or_none()
    if inviter is None:
        return False
    friend = User(tg_id=tg_id, full_name=full_name)
    session.add(friend)
    await session.flush()
    session.add(Referral(referrer_id=inviter.id, referred_id=friend.id))
    await session.commit()
    return True


async def progress(session, user_id: int) -> tuple[int, int]:
    """(friends who built a bot, friends who only joined)."""
    rows = (await session.execute(select(Referral.activated_at).where(Referral.referrer_id == user_id))).all()
    done = sum(1 for (a,) in rows if a is not None)
    return done, len(rows) - done


async def activate(session, friend_user_id: int) -> dict | None:
    """The friend created a bot: count it for the inviter. Returns {tg_id, done, rewarded} to notify, or None."""
    ref = (await session.execute(select(Referral).where(Referral.referred_id == friend_user_id))).scalar_one_or_none()
    if ref is None or ref.activated_at is not None:
        return None
    inviter_id = ref.referrer_id
    ref.activated_at = utcnow()
    await session.commit()
    inviter_tg = (await session.execute(select(User.tg_id).where(User.id == inviter_id))).scalar_one()
    done, _ = await progress(session, inviter_id)
    rewarded = done >= NEED and await _reward(session, inviter_id, inviter_tg)
    return {"tg_id": inviter_tg, "done": done, "rewarded": rewarded}


async def _reward(session, inviter_id: int, inviter_tg: int) -> bool:
    if plans.is_platform_admin(inviter_tg) or not await plans.claim_notice(session, f"ref_reward:{inviter_id}"):
        return False
    now = utcnow()
    acc = await plans.get_account(session, inviter_id)
    code, status = plans.state_of(acc, now)
    if acc is not None and status == "active" and plans.RANK[code] >= plans.RANK[REWARD_PLAN]:
        acc.expires_at = as_utc(acc.expires_at) + timedelta(days=REWARD_DAYS)  # already on an equal or better plan: add time
    elif acc is None:
        session.add(plans.AccountPlan(user_id=inviter_id, plan=REWARD_PLAN, expires_at=now + timedelta(days=REWARD_DAYS)))
    else:
        acc.plan, acc.expires_at = REWARD_PLAN, now + timedelta(days=REWARD_DAYS)
    await session.commit()
    plans.invalidate()
    return True


async def info(session, user: User, main_username: str) -> dict:
    user_id, tg_id = user.id, user.tg_id
    done, joined = await progress(session, user_id)
    got = (await session.execute(select(func.count()).select_from(plans.PlanNotice)
                                 .where(plans.PlanNotice.key == f"ref_reward:{user_id}"))).scalar() or 0
    return {"link": link(main_username, tg_id) if main_username else "", "done": done, "joined": joined,
            "need": NEED, "rewarded": bool(got), "reward": f"{REWARD_DAYS} kun {plans.PLANS[REWARD_PLAN].title}"}
