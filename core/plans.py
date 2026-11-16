"""Pricing rules of the platform: plans, per-bot licences, limits and receipt payments.

No Telegram calls in here: the main bot UI (constructor/flows/plans.py), the child-bot router and the
reminder loop (engine/plans_notify.py) all build on these functions.
"""
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from core.config import settings
from engine.booking_time import as_utc, utcnow
from models.audience import BotUser, Broadcast
from models.bots import Bot
from models.plans import (
    OPEN_PAY, PAY_APPROVED, PAY_CANCELLED, PAY_DRAFT, PAY_PENDING, PAY_REJECTED, TARGET_BOT, TARGET_PLAN,
    AccountPlan, BotLicense, PlanNotice, PlanPayment,
)
from models.users import User

FREE, START, PRO, BUSINESS = "free", "start", "pro", "business"
PERIOD_DAYS = 30
GRACE_DAYS = 3
TRIAL_DAYS = 7
TRIAL_PLAN = PRO
MONTH_CHOICES = (1, 3, 12)
DISCOUNT = {1: 0, 3: 10, 12: 25}  # percent by number of months paid at once

FREE_KINDS = ("standard", "cinema", "quiz")
START_KINDS = FREE_KINDS + ("booking", "join")
ALL_KINDS = START_KINDS + ("course", "shop", "paid")


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    price: int  # UZS per month
    max_bots: int | None
    user_cap: int | None  # users per bot
    kinds: tuple
    broadcasts: int | None  # per bot and calendar month
    watermark: bool


PLANS = {
    FREE: Plan(FREE, "Free", 0, 1, 20, FREE_KINDS, 1, True),
    START: Plan(START, "Start", 29_000, 3, 1_000, START_KINDS, 4, True),
    PRO: Plan(PRO, "Pro", 79_000, 10, None, ALL_KINDS, None, False),
    BUSINESS: Plan(BUSINESS, "Business", 149_000, None, None, ALL_KINDS, None, False),
}
PAID_PLANS = (START, PRO, BUSINESS)
RANK = {FREE: 0, START: 1, PRO: 2, BUSINESS: 3}

# One bot, one month: unlimited users, no brand footer, for that mode only.
KIND_PRICES = {
    "standard": 15_000, "cinema": 20_000, "quiz": 20_000, "booking": 30_000,
    "join": 25_000, "course": 40_000, "paid": 40_000, "shop": 50_000,
}
KIND_TITLES = {
    "standard": "Oddiy bot", "cinema": "Kino bot", "quiz": "Test bot", "booking": "Bron bot",
    "join": "Ariza bot", "course": "Kurs bot", "paid": "Pullik kanal", "shop": "Do‘kon bot",
}
KIND_MIN_PLAN = {k: (FREE if k in FREE_KINDS else START if k in START_KINDS else PRO) for k in ALL_KINDS}


def price_for(monthly: int, months: int) -> int:
    """Monthly price times months, minus the long-period discount, rounded to whole thousands."""
    total = monthly * months * (100 - DISCOUNT[months]) // 100
    return (total + 500) // 1000 * 1000


def plain_text(text: str) -> str:
    """A PlanError message without its HTML tags (for alerts and the Mini App)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


class PlanError(Exception):
    """A request the pricing rules refuse (shown to the person as is)."""


def _unlimited() -> Plan:
    return PLANS[BUSINESS]


# ------------------------------------------------------------------ account plan state

def state_of(acc: AccountPlan | None, now: datetime) -> tuple[str, str]:
    """``(plan code, "active" | "grace" | "free")`` for an account row. After the grace days: Free."""
    if acc is None:
        return FREE, "free"
    end = as_utc(acc.expires_at)
    if now <= end:
        return acc.plan, "active"
    if now <= end + timedelta(days=GRACE_DAYS):
        return acc.plan, "grace"
    return FREE, "free"


async def get_account(session, user_id: int) -> AccountPlan | None:
    return (await session.execute(select(AccountPlan).where(AccountPlan.user_id == user_id))).scalar_one_or_none()


def is_platform_admin(tg_id: int | None) -> bool:
    return tg_id is not None and tg_id in settings.admin_ids_list


async def owner_plan(session, user_id: int, now: datetime | None = None) -> Plan:
    if not settings.PLANS_ENFORCE:
        return _unlimited()
    tg_id = (await session.execute(select(User.tg_id).where(User.id == user_id))).scalar_one_or_none()
    if is_platform_admin(tg_id):
        return _unlimited()
    code, _ = state_of(await get_account(session, user_id), now or utcnow())
    return PLANS[code]


async def bot_count(session, user_id: int) -> int:
    return (await session.execute(select(func.count(Bot.id)).where(Bot.owner_id == user_id))).scalar() or 0


async def check_new_bot(session, user_id: int, now: datetime | None = None) -> None:
    """Raise PlanError when this owner may not create one more bot."""
    plan = await owner_plan(session, user_id, now)
    if plan.max_bots is not None and await bot_count(session, user_id) >= plan.max_bots:
        raise PlanError(
            f"🔒 <b>{plan.title}</b> tarifida {plan.max_bots} tagacha bot yaratish mumkin.\n"
            "Ko‘proq bot uchun tarifni oshiring.")


async def check_kind(session, user_id: int, kind: str, bot_id: int | None = None, now: datetime | None = None) -> None:
    """Raise PlanError when the owner's plan (or the bot's own licence) does not allow this mode."""
    now = now or utcnow()
    plan = await owner_plan(session, user_id, now)
    if kind in plan.kinds:
        return
    if bot_id is not None:
        lic = (await session.execute(select(BotLicense).where(BotLicense.bot_id == bot_id))).scalar_one_or_none()
        if lic is not None and lic.kind == kind and now <= as_utc(lic.expires_at) + timedelta(days=GRACE_DAYS):
            return
    need = PLANS[KIND_MIN_PLAN[kind]]
    raise PlanError(
        f"🔒 <b>{KIND_TITLES[kind]}</b> rejimi <b>{need.title}</b> tarifidan boshlanadi.\n"
        f"Yoki shu botning o‘zini oyiga {KIND_PRICES[kind]:,} so‘mga oching.".replace(",", " "))


# ------------------------------------------------------------------ what a child bot may do right now

@dataclass(frozen=True)
class Limits:
    plan: str
    kind_ok: bool
    user_cap: int | None
    watermark: bool
    broadcasts: int | None
    licensed: bool = False
    full: bool = False  # the user cap is reached (as of the last refresh)


_CACHE_SECONDS = 60
_cache: dict[int, tuple[float, Limits]] = {}


def invalidate(bot_id: int | None = None) -> None:
    if bot_id is None:
        _cache.clear()
    else:
        _cache.pop(bot_id, None)


async def _compute(session, bot: Bot, now: datetime) -> Limits:
    plan = await owner_plan(session, bot.owner_id, now)
    lic = (await session.execute(select(BotLicense).where(BotLicense.bot_id == bot.id))).scalar_one_or_none()
    licensed = (settings.PLANS_ENFORCE and lic is not None and lic.kind == bot.kind
                and now <= as_utc(lic.expires_at) + timedelta(days=GRACE_DAYS))
    if licensed:
        return Limits(plan.code, True, None, False, None, licensed=True)
    kind_ok = (bot.kind or "standard") in plan.kinds
    full = False
    if plan.user_cap is not None:
        users = (await session.execute(select(func.count(BotUser.id)).where(BotUser.bot_id == bot.id))).scalar() or 0
        full = users >= plan.user_cap
    return Limits(plan.code, kind_ok, plan.user_cap, plan.watermark, plan.broadcasts, full=full)


async def bot_limits(session, bot: Bot, now: datetime | None = None, use_cache: bool = True) -> Limits:
    """Cached for a minute per bot: every child-bot update asks for this."""
    if not settings.PLANS_ENFORCE:
        return Limits(BUSINESS, True, None, False, None)
    hit = _cache.get(bot.id)
    if use_cache and hit is not None and hit[0] > time.monotonic():
        return hit[1]
    limits = await _compute(session, bot, now or utcnow())
    _cache[bot.id] = (time.monotonic() + _CACHE_SECONDS, limits)
    return limits


async def admits(session, bot: Bot, tg_user_id: int, limits: Limits) -> bool:
    """False only for a person the bot has never seen while its user cap is reached."""
    if not limits.full:
        return True
    known = (await session.execute(
        select(BotUser.id).where(BotUser.bot_id == bot.id, BotUser.tg_user_id == tg_user_id))).first()
    return known is not None


async def check_broadcast(session, bot: Bot, now: datetime | None = None) -> None:
    """Raise PlanError when this bot used up its mass messages of the month."""
    now = now or utcnow()
    limits = await bot_limits(session, bot, now, use_cache=False)
    if limits.broadcasts is None:
        return
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = (await session.execute(select(func.count(Broadcast.id)).where(
        Broadcast.bot_id == bot.id, Broadcast.started_at >= month_start))).scalar() or 0
    if used >= limits.broadcasts:
        raise PlanError(
            f"🔒 Bu oy {limits.broadcasts} ta ommaviy xabar limiti tugadi.\n"
            "Cheksiz rassilka <b>Pro</b> tarifida yoki bot uchun alohida to‘lovda mavjud.")


# ------------------------------------------------------------------ payments

def _check_months(months: int) -> None:
    if months not in MONTH_CHOICES:
        raise PlanError("Muddat noto‘g‘ri.")


async def create_payment(session, user: User, *, plan: str | None = None, bot_id: int | None = None, months: int = 1,
                         kind: str | None = None) -> PlanPayment:
    """A draft payment for a plan or for one bot (its current mode, or ``kind`` to switch it on approval)."""
    _check_months(months)
    if plan is not None:
        if plan not in PAID_PLANS:
            raise PlanError("Bunday tarif yo‘q.")
        target, kind, amount = TARGET_PLAN, None, price_for(PLANS[plan].price, months)
    else:
        bot = (await session.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id))).scalar_one_or_none()
        if bot is None:
            raise PlanError("Bot topilmadi.")
        kind = kind or bot.kind or "standard"
        if kind not in KIND_PRICES:
            raise PlanError("Bunday rejim yo‘q.")
        target = TARGET_BOT
        amount = price_for(KIND_PRICES[kind], months)
    await session.execute(update(PlanPayment).where(PlanPayment.user_id == user.id, PlanPayment.status == PAY_DRAFT)
                          .values(status=PAY_CANCELLED).execution_options(synchronize_session=False))
    pay = PlanPayment(user_id=user.id, tg_user_id=user.tg_id, target=target, plan=plan, bot_id=bot_id if plan is None else None,
                      kind=kind, months=months, amount=amount)
    session.add(pay)
    await session.commit()
    return pay


def describe(pay: PlanPayment) -> str:
    what = (f"{PLANS[pay.plan].title} tarifi" if pay.target == TARGET_PLAN else f"{KIND_TITLES.get(pay.kind, pay.kind)} uchun alohida to‘lov")
    return f"{what} · {pay.months} oy"


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so‘m"


async def attach_receipt(session, payment_id: int, tg_user_id: int, rtype: str, file_id: str) -> PlanPayment | None:
    """The owner sent the receipt: draft -> pending. None if it is not theirs or no longer a draft."""
    claimed = await session.execute(
        update(PlanPayment).where(PlanPayment.id == payment_id, PlanPayment.tg_user_id == tg_user_id,
                                  PlanPayment.status == PAY_DRAFT)
        .values(status=PAY_PENDING, receipt_type=rtype, receipt_file_id=file_id).execution_options(synchronize_session=False))
    await session.commit()
    if claimed.rowcount == 0:
        return None
    return await session.get(PlanPayment, payment_id, populate_existing=True)


async def cancel_payment(session, payment_id: int, tg_user_id: int) -> bool:
    res = await session.execute(update(PlanPayment).where(
        PlanPayment.id == payment_id, PlanPayment.tg_user_id == tg_user_id, PlanPayment.status.in_(OPEN_PAY))
        .values(status=PAY_CANCELLED).execution_options(synchronize_session=False))
    await session.commit()
    return res.rowcount > 0


async def decide(session, payment_id: int, admin_tg_id: int, approve: bool, now: datetime | None = None) -> PlanPayment | None:
    """Approve or reject a pending payment exactly once. Returns the payment, or None if it was already decided."""
    now = now or utcnow()
    claimed = await session.execute(
        update(PlanPayment).where(PlanPayment.id == payment_id, PlanPayment.status == PAY_PENDING)
        .values(status=PAY_APPROVED if approve else PAY_REJECTED, decided_by=admin_tg_id, decided_at=now)
        .execution_options(synchronize_session=False))
    if claimed.rowcount == 0:
        return None
    pay = await session.get(PlanPayment, payment_id, populate_existing=True)
    if approve:
        await _apply(session, pay, now)
    await session.commit()
    return pay


async def _apply(session, pay: PlanPayment, now: datetime) -> None:
    days = PERIOD_DAYS * pay.months
    if pay.target == TARGET_PLAN:
        acc = await get_account(session, pay.user_id)
        if acc is None:
            session.add(AccountPlan(user_id=pay.user_id, plan=pay.plan, expires_at=now + timedelta(days=days)))
        else:
            live = as_utc(acc.expires_at) > now and acc.plan == pay.plan  # same plan: continue from its end
            acc.expires_at = (as_utc(acc.expires_at) if live else now) + timedelta(days=days)
            acc.plan = pay.plan
        await session.flush()
        invalidate()  # every bot of this owner is affected
        return
    lic = (await session.execute(select(BotLicense).where(BotLicense.bot_id == pay.bot_id))).scalar_one_or_none()
    if lic is None:
        session.add(BotLicense(bot_id=pay.bot_id, kind=pay.kind, expires_at=now + timedelta(days=days)))
    else:
        live = as_utc(lic.expires_at) > now and lic.kind == pay.kind
        lic.expires_at = (as_utc(lic.expires_at) if live else now) + timedelta(days=days)
        lic.kind = pay.kind
    await session.flush()
    bot = await session.get(Bot, pay.bot_id)
    if bot is not None and (bot.kind or "standard") != pay.kind:  # paid for another mode: switch the bot to it
        from constructor.flows.cinema import set_kind
        await set_kind(session, bot, pay.kind)
    invalidate(pay.bot_id)


async def pending_payments(session) -> list[PlanPayment]:
    return list((await session.execute(select(PlanPayment).where(PlanPayment.status == PAY_PENDING)
                                       .order_by(PlanPayment.id))).scalars())


# ------------------------------------------------------------------ free trial

async def start_trial(session, user: User, now: datetime | None = None) -> AccountPlan:
    """A one-time 7-day Pro per person."""
    now = now or utcnow()
    if is_platform_admin(user.tg_id):
        raise PlanError("Siz platforma adminisiz: cheklovlar sizga tatbiq etilmaydi.")
    acc = await get_account(session, user.id)
    if acc is not None and acc.trial_used:
        raise PlanError("Bepul sinov bir marta beriladi va u allaqachon ishlatilgan.")
    code, status = state_of(acc, now)
    if acc is not None and status == "active" and RANK[code] >= RANK[TRIAL_PLAN]:
        raise PlanError("Sizda allaqachon shu darajadagi tarif faol.")
    end = now + timedelta(days=TRIAL_DAYS)
    if acc is None:
        acc = AccountPlan(user_id=user.id, plan=TRIAL_PLAN, expires_at=end, trial_used=True)
        session.add(acc)
    else:
        acc.plan, acc.expires_at, acc.trial_used = TRIAL_PLAN, end, True
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise PlanError("Bepul sinov allaqachon yoqilgan.")
    invalidate()
    return acc


# ------------------------------------------------------------------ notices

async def claim_notice(session, key: str) -> bool:
    """True the first time a key is claimed: send that notice only then."""
    session.add(PlanNotice(key=key[:120]))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True
