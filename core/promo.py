"""Promo codes: checked and applied to a draft payment, counted when the admin approves it."""
import re
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from core import plans
from engine.booking_time import as_utc, utcnow
from models.plans import PAY_DRAFT, PlanPayment, PromoCode, PromoUse

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
MIN_AMOUNT = 1000  # a discounted payment never drops below this: a free payment would need no receipt
CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")


def normalize(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def discounted(base: int, promo: PromoCode) -> int:
    if promo.percent:
        value = (base * (100 - promo.percent) // 100 + 500) // 1000 * 1000
    else:
        value = base - (promo.amount or 0)
    return max(MIN_AMOUNT, min(base, value))


def label(promo: PromoCode) -> str:
    return f"−{promo.percent}%" if promo.percent else f"−{plans.money(promo.amount or 0)}"


async def create(session, *, code: str | None, percent: int | None, amount: int | None, max_uses: int | None,
                 days: int | None, note: str | None) -> PromoCode:
    if bool(percent) == bool(amount):
        raise plans.PlanError("Foiz yoki summadan birini kiriting.")
    if percent is not None and not (1 <= percent <= 90):
        raise plans.PlanError("Foiz 1 dan 90 gacha bo‘lsin.")
    if amount is not None and not (1000 <= amount <= 10_000_000):
        raise plans.PlanError("Summa 1 000 dan 10 000 000 gacha bo‘lsin.")
    if max_uses is not None and max_uses < 1:
        raise plans.PlanError("Foydalanish soni kamida 1.")
    code = normalize(code) if code else new_code()
    if not CODE_RE.match(code):
        raise plans.PlanError("Kod 3–32 ta harf, raqam, - yoki _ bo‘lsin.")
    promo = PromoCode(code=code, percent=percent or None, amount=amount or None, max_uses=max_uses,
                      expires_at=utcnow() + timedelta(days=days) if days else None, note=(note or "").strip()[:120] or None)
    session.add(promo)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise plans.PlanError("Bunday kod allaqachon bor.") from None
    return promo


async def check(session, code: str, user_id: int, now=None) -> PromoCode:
    """The promo if this person may use it now, else PlanError with the reason."""
    promo = (await session.execute(select(PromoCode).where(PromoCode.code == normalize(code)))).scalar_one_or_none()
    if promo is None or not promo.active:
        raise plans.PlanError("Bunday promo-kod yo‘q yoki o‘chirilgan.")
    if promo.expires_at is not None and as_utc(promo.expires_at) < (now or utcnow()):
        raise plans.PlanError("Promo-kod muddati tugagan.")
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise plans.PlanError("Promo-kod limiti tugagan.")
    used = (await session.execute(select(PromoUse.id).where(PromoUse.promo_id == promo.id, PromoUse.user_id == user_id))).first()
    if used is not None:
        raise plans.PlanError("Bu kodni siz allaqachon ishlatgansiz.")
    return promo


async def apply_to_payment(session, payment_id: int, user_id: int, code: str) -> PlanPayment:
    """Reduce a draft payment by the code. A second code replaces the first (always counted from the full price)."""
    pay = await session.get(PlanPayment, payment_id)
    if pay is None or pay.user_id != user_id or pay.status != PAY_DRAFT:
        raise plans.PlanError("To‘lov topilmadi yoki allaqachon yuborilgan.")
    promo = await check(session, code, user_id)
    base = pay.amount + (pay.discount or 0)
    pay.amount = discounted(base, promo)
    pay.discount = base - pay.amount
    pay.promo_code = promo.code
    await session.commit()
    return pay


async def consume(session, pay: PlanPayment) -> None:
    """Count the code when its payment is approved (called inside ``plans.decide``). Never blocks the approval."""
    if not pay.promo_code:
        return
    promo = (await session.execute(select(PromoCode).where(PromoCode.code == pay.promo_code))).scalar_one_or_none()
    if promo is None:
        return
    try:
        async with session.begin_nested():
            session.add(PromoUse(promo_id=promo.id, user_id=pay.user_id, payment_id=pay.id))
            await session.flush()
    except IntegrityError:
        return  # the same person already used it on another payment
    await session.execute(update(PromoCode).where(PromoCode.id == promo.id).values(used_count=PromoCode.used_count + 1)
                          .execution_options(synchronize_session=False))
