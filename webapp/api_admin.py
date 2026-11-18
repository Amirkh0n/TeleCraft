"""Mini App API for the platform admins (ADMIN_IDS): dashboard, payments, customers, bots, messages, system."""
import asyncio
import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import TelegramError

from core import plans, pricing, promo
from core.backup import send_backup
from core.config import settings
from core.database import engine
from core.logger import get_logger
from engine.booking_time import as_utc, utcnow
from engine.telegram_client import get_client
from models.audience import BotUser
from models.bots import Bot
from models.plans import AccountPlan, AdminLog, BotLicense, PlanPayment, PromoCode, PAY_APPROVED, PAY_PENDING, PAY_REJECTED
from models.users import User
from webapp.auth import current_user, get_session

logger = get_logger("webapp.admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
PAGE = 30


async def admin_user(user: User = Depends(current_user)) -> User:
    if not plans.is_platform_admin(user.tg_id):
        raise HTTPException(status_code=403, detail="Bu bo‘lim faqat adminlar uchun.")
    return user


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"admin": plans.is_platform_admin(user.tg_id)}


async def log(session: AsyncSession, admin: User, action: str, target: int | None = None, detail: str | None = None):
    session.add(AdminLog(admin_tg_id=admin.tg_id, action=action, target_user_id=target, detail=(detail or "")[:500] or None))
    await session.commit()


async def main_bot():
    return await get_client(settings.TELEGRAM_TOKEN)


def _day(dt):
    return as_utc(dt).isoformat() if dt else None


async def _count(session, col, *where) -> int:
    return (await session.execute(select(func.count(col)).where(*where))).scalar() or 0


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard")
async def dashboard(admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    now = utcnow()
    accounts = (await session.execute(select(AccountPlan))).scalars().all()
    spread = {code: 0 for code in plans.PLANS}
    expiring = 0
    for acc in accounts:
        code, status = plans.state_of(acc, now)
        spread[code] += 1
        if status == "active" and as_utc(acc.expires_at) <= now + timedelta(days=7):
            expiring += 1
    customers = await _count(session, User.id)
    spread["free"] = max(0, customers - sum(v for k, v in spread.items() if k != "free"))
    months = []
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for i in range(5, -1, -1):
        year, month = first.year, first.month - i
        while month <= 0:
            year, month = year - 1, month + 12
        start = first.replace(year=year, month=month)
        end = first.replace(year=year + (month == 12), month=month % 12 + 1)
        total = (await session.execute(select(func.coalesce(func.sum(PlanPayment.amount), 0)).where(
            PlanPayment.status == PAY_APPROVED, PlanPayment.decided_at >= start, PlanPayment.decided_at < end))).scalar() or 0
        months.append({"month": f"{start:%Y-%m}", "total": int(total)})
    return {
        "customers": customers, "bots": await _count(session, Bot.id), "active_bots": await _count(session, Bot.id, Bot.is_active.is_(True)),
        "bot_users": await _count(session, BotUser.id), "plans": spread, "pending": await _count(session, PlanPayment.id, PlanPayment.status == PAY_PENDING),
        "expiring": expiring, "month_revenue": months[-1]["total"], "revenue": months,
        "licenses": await _count(session, BotLicense.id, BotLicense.expires_at > now),
    }


# ------------------------------------------------------------------ payments

def payment_out(p: PlanPayment, user: User | None) -> dict:
    return {
        "id": p.id, "user_id": p.user_id, "tg_user_id": p.tg_user_id, "name": (user.full_name if user else None) or "—",
        "what": plans.describe(p), "amount": p.amount, "status": p.status, "receipt": bool(p.receipt_file_id),
        "created_at": _day(p.created_at), "decided_at": _day(p.decided_at), "decided_by": p.decided_by,
    }


@router.get("/payments")
async def list_payments(status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"), offset: int = 0,
                        admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    q = select(PlanPayment, User).join(User, User.id == PlanPayment.user_id)
    q = q.where(PlanPayment.status.in_(("pending", "approved", "rejected")) if status == "all" else PlanPayment.status == status)
    rows = (await session.execute(q.order_by(PlanPayment.id.desc() if status != "pending" else PlanPayment.id).offset(offset).limit(PAGE + 1))).all()
    return {"items": [payment_out(p, u) for p, u in rows[:PAGE]], "more": len(rows) > PAGE}


@router.get("/payments/{payment_id}/receipt")
async def receipt(payment_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    pay = await session.get(PlanPayment, payment_id)
    if pay is None or not pay.receipt_file_id:
        raise HTTPException(status_code=404, detail="Chek topilmadi.")
    try:
        file = await (await main_bot()).get_file(pay.receipt_file_id)
        data = bytes(await file.download_as_bytearray())
    except TelegramError:
        raise HTTPException(status_code=502, detail="Chekni Telegramdan olib bo‘lmadi.") from None
    return Response(content=data, media_type="image/jpeg" if pay.receipt_type == "photo" else "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=300"})


class DecideIn(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=200)


@router.post("/payments/{payment_id}/decide")
async def decide_payment(payment_id: int, body: DecideIn, admin: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    from constructor.flows.plans import _result_text
    pay = await plans.decide(session, payment_id, admin.tg_id, body.approve)
    if pay is None:
        raise HTTPException(status_code=409, detail="Bu to‘lov allaqachon hal qilingan.")
    text = await _result_text(session, pay, body.approve)
    if not body.approve and body.reason:
        text += f"\nSabab: {body.reason}"
    await log(session, admin, "pay_ok" if body.approve else "pay_no", pay.user_id, f"#{pay.id} {plans.describe(pay)} {pay.amount}")
    try:
        await (await main_bot()).send_message(chat_id=pay.tg_user_id, text=text, parse_mode="HTML")
    except TelegramError as exc:
        logger.info("payer %s not told about payment %s: %s", pay.tg_user_id, pay.id, exc)
    user = await session.get(User, pay.user_id)
    return payment_out(pay, user)


@router.get("/payments.csv")
async def payments_csv(month: str = Query(pattern=r"^\d{4}-\d{2}$"), admin: User = Depends(admin_user),
                       session: AsyncSession = Depends(get_session)):
    year, mon = int(month[:4]), int(month[5:])
    if not 1 <= mon <= 12:
        raise HTTPException(status_code=422, detail="Oy noto‘g‘ri.")
    start = utcnow().replace(year=year, month=mon, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=year + (mon == 12), month=mon % 12 + 1)
    rows = (await session.execute(select(PlanPayment, User).join(User, User.id == PlanPayment.user_id).where(
        PlanPayment.status == PAY_APPROVED, PlanPayment.decided_at >= start, PlanPayment.decided_at < end)
        .order_by(PlanPayment.decided_at))).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "sana", "mijoz", "telegram_id", "nima uchun", "summa", "tasdiqlagan_admin"])
    for p, u in rows:
        writer.writerow([p.id, as_utc(p.decided_at).strftime("%Y-%m-%d %H:%M"), (u.full_name or "").replace("=", ""), p.tg_user_id,
                         plans.describe(p), p.amount, p.decided_by])
    return Response(content="﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="tushum_{month}.csv"'})


# ------------------------------------------------------------------ customers

async def _customer_row(session, u: User, now) -> dict:
    acc = await plans.get_account(session, u.id)
    code, status = plans.state_of(acc, now)
    return {"id": u.id, "tg_id": u.tg_id, "name": u.full_name or "—", "plan": plans.PLANS[code].title if status != "free" else "Free",
            "status": status, "expires_at": _day(acc.expires_at) if acc and status != "free" else None,
            "bots": await plans.bot_count(session, u.id), "admin": plans.is_platform_admin(u.tg_id)}


@router.get("/customers")
async def customers(q: str = Query("", max_length=60), offset: int = 0, admin: User = Depends(admin_user),
                    session: AsyncSession = Depends(get_session)):
    stmt = select(User)
    q = q.strip().lstrip("@")
    if q:
        conds = [User.full_name.ilike(f"%{q}%"), User.id.in_(select(Bot.owner_id).where(Bot.username.ilike(f"%{q}%")))]
        if q.isdigit():
            conds.append(User.tg_id == int(q))
        stmt = stmt.where(or_(*conds))
    rows = (await session.execute(stmt.order_by(User.id.desc()).offset(offset).limit(PAGE + 1))).scalars().all()
    now = utcnow()
    return {"items": [await _customer_row(session, u, now) for u in rows[:PAGE]], "more": len(rows) > PAGE}


@router.get("/customers/{user_id}")
async def customer(user_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    now = utcnow()
    acc = await plans.get_account(session, u.id)
    bots = (await session.execute(select(Bot).where(Bot.owner_id == u.id).order_by(Bot.id))).scalars().all()
    out_bots = []
    for b in bots:
        lic = (await session.execute(select(BotLicense).where(BotLicense.bot_id == b.id))).scalar_one_or_none()
        out_bots.append({"id": b.id, "name": b.name, "username": b.username, "kind": b.kind, "active": b.is_active,
                         "users": await _count(session, BotUser.id, BotUser.bot_id == b.id),
                         "license_until": _day(lic.expires_at) if lic and as_utc(lic.expires_at) > now else None})
    pays = (await session.execute(select(PlanPayment).where(PlanPayment.user_id == u.id, PlanPayment.status != "draft")
                                  .order_by(PlanPayment.id.desc()).limit(20))).scalars().all()
    history = (await session.execute(select(AdminLog).where(AdminLog.target_user_id == u.id).order_by(AdminLog.id.desc()).limit(10))).scalars().all()
    return {**await _customer_row(session, u, now), "trial_used": bool(acc and acc.trial_used), "bot_list": out_bots,
            "payments": [payment_out(p, u) for p in pays], "log": [log_out(x) for x in history]}


class GrantIn(BaseModel):
    plan: str = Field(pattern="^(free|start|pro|business)$")
    days: int = Field(default=30, ge=1, le=3650)
    reason: str = Field(default="", max_length=200)


@router.post("/customers/{user_id}/plan")
async def grant_plan(user_id: int, body: GrantIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    now = utcnow()
    acc = await plans.get_account(session, u.id)
    if body.plan == "free":
        if acc is not None:  # past its grace period: back to Free at once
            acc.expires_at = now - timedelta(days=plans.GRACE_DAYS + 1)
    elif acc is None:
        session.add(AccountPlan(user_id=u.id, plan=body.plan, expires_at=now + timedelta(days=body.days)))
    else:
        live = acc.plan == body.plan and as_utc(acc.expires_at) > now  # same plan: extend from its end
        acc.expires_at = (as_utc(acc.expires_at) if live else now) + timedelta(days=body.days)
        acc.plan = body.plan
    await session.commit()
    plans.invalidate()
    await log(session, admin, "grant", u.id, f"{body.plan} +{body.days} kun. {body.reason}".strip())
    return await _customer_row(session, u, now)


@router.post("/customers/{user_id}/reset-trial")
async def reset_trial(user_id: int, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    acc = await plans.get_account(session, user_id)
    if acc is None or not acc.trial_used:
        raise HTTPException(status_code=409, detail="Bepul sinov ishlatilmagan.")
    acc.trial_used = False
    await session.commit()
    await log(session, admin, "reset_trial", user_id)
    return {"ok": True}


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=3500)


@router.post("/customers/{user_id}/message")
async def message_customer(user_id: int, body: TextIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    try:
        await (await main_bot()).send_message(chat_id=u.tg_id, text=body.text)
    except TelegramError:
        raise HTTPException(status_code=409, detail="Xabar yetib bormadi (mijoz botni bloklagan bo‘lishi mumkin).") from None
    await log(session, admin, "message", u.id, body.text[:120])
    return {"ok": True}


# ------------------------------------------------------------------ bots

@router.get("/bots")
async def all_bots(q: str = Query("", max_length=60), offset: int = 0, admin: User = Depends(admin_user),
                   session: AsyncSession = Depends(get_session)):
    stmt = select(Bot, User).join(User, User.id == Bot.owner_id)
    q = q.strip().lstrip("@")
    if q:
        stmt = stmt.where(or_(Bot.username.ilike(f"%{q}%"), Bot.name.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    rows = (await session.execute(stmt.order_by(Bot.id.desc()).offset(offset).limit(PAGE + 1))).all()
    items = [{"id": b.id, "name": b.name, "username": b.username, "kind": b.kind, "active": b.is_active, "connected": bool(b.webhook_set),
              "owner_id": u.id, "owner": u.full_name or str(u.tg_id), "users": await _count(session, BotUser.id, BotUser.bot_id == b.id)}
             for b, u in rows[:PAGE]]
    return {"items": items, "more": len(rows) > PAGE}


class ActiveIn(BaseModel):
    active: bool


@router.post("/bots/{bot_id}/active")
async def set_active(bot_id: int, body: ActiveIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    bot = await session.get(Bot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot topilmadi.")
    bot.is_active = body.active
    await session.commit()
    plans.invalidate(bot.id)
    await log(session, admin, "bot_on" if body.active else "bot_off", bot.owner_id, f"{bot.name} (#{bot.id})")
    return {"id": bot.id, "active": bot.is_active}


# ------------------------------------------------------------------ platform message, system, log

class BroadcastIn(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    plan: str = Field(default="all", pattern="^(all|free|start|pro|business)$")


async def _deliver(tg_ids: list[int], text: str) -> None:
    tg = await main_bot()
    for tg_id in tg_ids:
        try:
            await tg.send_message(chat_id=tg_id, text=text)
        except TelegramError:
            pass
        except Exception:
            logger.exception("platform message failed")
        await asyncio.sleep(0.05)


@router.post("/broadcast")
async def broadcast(body: BroadcastIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    now = utcnow()
    accounts = {a.user_id: a for a in (await session.execute(select(AccountPlan))).scalars()}
    targets = []
    for u in (await session.execute(select(User))).scalars():
        code, _ = plans.state_of(accounts.get(u.id), now)
        if body.plan in ("all", code):
            targets.append(u.tg_id)
    asyncio.create_task(_deliver(targets, body.text))
    await log(session, admin, "broadcast", None, f"{body.plan}: {len(targets)} ta. {body.text[:100]}")
    return {"queued": len(targets)}


@router.get("/system")
async def system(admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    from sqlalchemy import text
    version = (await session.execute(text("select version_num from alembic_version"))).scalar()
    return {"version": version, "dialect": engine.dialect.name, "enforced": bool(settings.PLANS_ENFORCE),
            "card": bool(settings.PLAN_CARD_NUMBER), "admins": len(settings.admin_ids_list),
            "log": [log_out(x) for x in (await session.execute(select(AdminLog).order_by(AdminLog.id.desc()).limit(25))).scalars()]}


def log_out(x: AdminLog) -> dict:
    return {"id": x.id, "admin": x.admin_tg_id, "action": x.action, "target": x.target_user_id, "detail": x.detail, "at": _day(x.created_at)}


@router.post("/backup")
async def backup_now(admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    try:
        sent = await send_backup(await main_bot(), [admin.tg_id], engine)
    except Exception as exc:
        logger.exception("manual backup failed")
        raise HTTPException(status_code=500, detail=f"Zaxira yaratilmadi: {exc}") from None
    if not sent:
        raise HTTPException(status_code=409, detail="Faylni yuborib bo‘lmadi. Asosiy botga /start yuboring.")
    await log(session, admin, "backup")
    return {"sent": sent}


# ------------------------------------------------------------------ prices and limits

class PricingIn(BaseModel):
    plans: dict = Field(default_factory=dict)
    kind_prices: dict = Field(default_factory=dict)
    discount: dict = Field(default_factory=dict)


@router.get("/pricing")
async def get_pricing(admin: User = Depends(admin_user)):
    return pricing.table()


@router.put("/pricing")
async def put_pricing(body: PricingIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    try:
        await pricing.save(session, body.model_dump())
    except pricing.PricingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await log(session, admin, "pricing", None, ", ".join(sorted({*body.plans, *body.kind_prices, *(f"{m}oy" for m in body.discount)})))
    return pricing.table()


@router.post("/pricing/reset")
async def reset_pricing(admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    await pricing.reset(session)
    await log(session, admin, "pricing_reset")
    return pricing.table()


# ------------------------------------------------------------------ promo codes

def promo_out(p: PromoCode) -> dict:
    now = utcnow()
    expired = p.expires_at is not None and as_utc(p.expires_at) < now
    full = p.max_uses is not None and p.used_count >= p.max_uses
    return {"id": p.id, "code": p.code, "label": promo.label(p), "percent": p.percent, "amount": p.amount, "max_uses": p.max_uses, "used": p.used_count,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None, "active": p.active, "note": p.note,
            "state": "off" if not p.active else "expired" if expired else "full" if full else "live"}


class PromoIn(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    percent: int | None = Field(default=None, ge=1, le=90)
    amount: int | None = Field(default=None, ge=1000, le=10_000_000)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    days: int | None = Field(default=None, ge=1, le=3650)
    note: str | None = Field(default=None, max_length=120)


@router.get("/promos")
async def list_promos(admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(PromoCode).order_by(PromoCode.id.desc()).limit(200))).scalars().all()
    return {"items": [promo_out(p) for p in rows]}


@router.post("/promos", status_code=201)
async def create_promo(body: PromoIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    try:
        p = await promo.create(session, **body.model_dump())
    except plans.PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    out = promo_out(p)
    await log(session, admin, "promo_new", None, f"{out['code']} {out['label']}")
    return out


class PromoActiveIn(BaseModel):
    active: bool


@router.post("/promos/{promo_id}/active")
async def set_promo_active(promo_id: int, body: PromoActiveIn, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    p = await session.get(PromoCode, promo_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Kod topilmadi.")
    p.active = body.active
    await session.commit()
    out = promo_out(p)
    await log(session, admin, "promo_on" if body.active else "promo_off", None, out["code"])
    return out
