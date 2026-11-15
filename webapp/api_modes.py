"""Mini App API: the bot's mode (ready-made kind), its key numbers, payment settings, switching modes."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from constructor.flows.cinema import set_kind
from engine.booking_time import utcnow
from models import booking as bk, course as cr, join as jn, paid as pd, quiz as qz, shop as sh
from models.audience import BotUser
from models.movies import Movie
from webapp.api import bot_out, owned_bot
from webapp.auth import current_user, get_session
from models.users import User

router = APIRouter(prefix="/api/v1", tags=["miniapp"])

STANDARD = "standard"
# kind -> (icon, name, what it does, how to start it)
MODES = {
    STANDARD: ("💬", "Oddiy bot", "Ekranlar, tugmalar va formalar bilan o‘zingiz tuzadigan bot.",
               ["«Ekranlar» bo‘limida birinchi ekranni yarating", "Tugmalarga javob yoki amal biriktiring"]),
    "cinema": ("🎬", "Kino bot", "Foydalanuvchi kino kodini yozadi, bot videoni yuboradi.",
               ["Botda /admin yozing va kinolarni kod bilan qo‘shing", "Kinolar kanalini ulang (ixtiyoriy)"]),
    "booking": ("📅", "Bron bot", "Xizmat, mutaxassis va vaqt tanlab navbat olish; eslatmalar.",
                ["Botda /admin: xizmat va ish vaqtini kiriting", "Mutaxassislar qo‘shing (ixtiyoriy)"]),
    "quiz": ("📝", "Test bot", "Testlar, natijalar, reyting va guruhdagi jonli musobaqa.",
             ["Botda /admin: test va savollar qo‘shing", "Guruhga botni qo‘shib musobaqa boshlang"]),
    "course": ("🎓", "Kurs bot", "Modul va darslar, ochilish tartibi, to‘lov, sertifikat.",
               ["Botda /admin: kurs, modul va darslarni yarating", "Bu yerdan karta raqamini kiriting (pullik kurs uchun)"]),
    "shop": ("🛒", "Do‘kon bot", "Kategoriya, mahsulot, savat, yetkazish va buyurtmalar.",
             ["Botda /admin: kategoriya va mahsulot qo‘shing", "Bu yerdan karta raqamini kiriting (karta to‘lovi uchun)"]),
    "join": ("📨", "Ariza bot", "Kanal/guruhga qo‘shilish arizalarini avto yoki qo‘lda qabul qiladi.",
             ["Botni kanalga administrator qiling", "Botda /admin: rejim, savollar va havolalarni sozlang"]),
    "paid": ("💎", "Pullik kanal", "Yopiq kanalga obuna: tarif, to‘lov, kirish havolasi, muddat nazorati.",
             ["Botni kanalga administrator qiling", "Bu yerdan karta raqamini kiriting", "Botda /admin: tarif yarating"]),
}
CARD_MODELS = {"course": cr.CourseSettings, "shop": sh.ShopSettings, "paid": pd.PaidSettings}


class ModeIn(BaseModel):
    kind: str


class PaymentIn(BaseModel):
    card_number: str | None = Field(default=None, max_length=40)
    card_holder: str | None = Field(default=None, max_length=120)
    pay_note: str | None = Field(default=None, max_length=700)
    card_enabled: bool | None = None  # shop only: allow paying by card at all


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


async def _count(session, column, *where) -> int:
    return (await session.execute(select(func.count(column)).where(*where))).scalar() or 0


async def _sum(session, column, *where) -> int:
    return (await session.execute(select(func.coalesce(func.sum(column), 0)).where(*where))).scalar() or 0


def _m(label: str, value, money: bool = False) -> dict:
    return {"label": label, "value": value, "money": money}


async def metrics(session: AsyncSession, bot) -> list[dict]:
    """The handful of numbers an owner of this kind of bot wants to see first."""
    b, now = bot.id, utcnow()
    users = await _count(session, BotUser.id, BotUser.bot_id == b)
    kind = bot.kind
    if kind == "cinema":
        return [_m("Kinolar", await _count(session, Movie.id, Movie.bot_id == b)), _m("Foydalanuvchilar", users)]
    if kind == "booking":
        upcoming = await _count(session, bk.Booking.id, bk.Booking.bot_id == b, bk.Booking.status.in_(bk.ACTIVE_STATUSES), bk.Booking.start_at >= now)
        return [_m("Xizmatlar", await _count(session, bk.BookingService.id, bk.BookingService.bot_id == b)),
                _m("Kelayotgan bronlar", upcoming), _m("Jami bronlar", await _count(session, bk.Booking.id, bk.Booking.bot_id == b)),
                _m("Foydalanuvchilar", users)]
    if kind == "quiz":
        done = (qz.QuizAttempt.bot_id == b, qz.QuizAttempt.status == qz.ATTEMPT_FINISHED)
        people = (await session.execute(select(func.count(distinct(qz.QuizAttempt.tg_user_id))).where(*done))).scalar() or 0
        return [_m("Testlar", await _count(session, qz.QuizTest.id, qz.QuizTest.bot_id == b)),
                _m("Topshirilgan urinishlar", await _count(session, qz.QuizAttempt.id, *done)), _m("Ishtirokchilar", people),
                _m("Guruh musobaqalari", await _count(session, qz.QuizGame.id, qz.QuizGame.bot_id == b))]
    if kind == "course":
        students = (await session.execute(select(func.count(distinct(cr.Enrollment.tg_user_id))).where(cr.Enrollment.bot_id == b))).scalar() or 0
        return [_m("Kurslar", await _count(session, cr.Course.id, cr.Course.bot_id == b)), _m("O‘quvchilar", students),
                _m("Tugatganlar", await _count(session, cr.Enrollment.id, cr.Enrollment.bot_id == b, cr.Enrollment.completed_at.is_not(None))),
                _m("Kutilayotgan to‘lovlar", await _count(session, cr.CoursePayment.id, cr.CoursePayment.bot_id == b, cr.CoursePayment.status == cr.PAY_PENDING)),
                _m("Tushum", await _sum(session, cr.CoursePayment.amount, cr.CoursePayment.bot_id == b, cr.CoursePayment.status == cr.PAY_APPROVED), True)]
    if kind == "shop":
        return [_m("Mahsulotlar", await _count(session, sh.ShopProduct.id, sh.ShopProduct.bot_id == b)),
                _m("Faol buyurtmalar", await _count(session, sh.Order.id, sh.Order.bot_id == b, sh.Order.status.in_(sh.ACTIVE_STATUSES))),
                _m("Bajarilgan", await _count(session, sh.Order.id, sh.Order.bot_id == b, sh.Order.status == sh.ST_DONE)),
                _m("Chek kutilmoqda", await _count(session, sh.Order.id, sh.Order.bot_id == b, sh.Order.payment_status == sh.PAID_PENDING)),
                _m("Tushum", await _sum(session, sh.Order.total, sh.Order.bot_id == b, sh.Order.status == sh.ST_DONE), True)]
    if kind == "join":
        reqs = jn.JoinRequest
        return [_m("Kanal va guruhlar", await _count(session, jn.JoinChat.id, jn.JoinChat.bot_id == b)),
                _m("Kutilayotgan arizalar", await _count(session, reqs.id, reqs.bot_id == b, reqs.status.in_(jn.OPEN_STATUSES))),
                _m("Qabul qilingan", await _count(session, reqs.id, reqs.bot_id == b, reqs.status == jn.ST_APPROVED)),
                _m("Rad / muddati o‘tgan", await _count(session, reqs.id, reqs.bot_id == b, reqs.status.in_((jn.ST_DECLINED, jn.ST_EXPIRED))))]
    if kind == "paid":
        live = (pd.PaidSub.bot_id == b, pd.PaidSub.status == pd.SUB_ACTIVE, pd.PaidSub.expires_at > now)
        paid_ok = (pd.PaidPayment.bot_id == b, pd.PaidPayment.status == pd.PAY_APPROVED)
        return [_m("Tariflar", await _count(session, pd.PaidPlan.id, pd.PaidPlan.bot_id == b)),
                _m("Faol obunachilar", await _count(session, pd.PaidSub.id, *live)),
                _m("3 kunda tugaydi", await _count(session, pd.PaidSub.id, *live, pd.PaidSub.expires_at <= now + timedelta(days=3))),
                _m("Kutilayotgan to‘lovlar", await _count(session, pd.PaidPayment.id, pd.PaidPayment.bot_id == b, pd.PaidPayment.status == pd.PAY_PENDING)),
                _m("Tushum", await _sum(session, pd.PaidPayment.price, *paid_ok), True)]
    return [_m("Foydalanuvchilar", users)]


async def payment_settings(session: AsyncSession, bot) -> dict | None:
    model = CARD_MODELS.get(bot.kind)
    if model is None:
        return None
    row = (await session.execute(select(model).where(model.bot_id == bot.id))).scalar_one_or_none()
    out = {"card_number": row.card_number if row else None, "card_holder": row.card_holder if row else None,
           "pay_note": row.pay_note if row else None}
    if bot.kind == "shop":
        out["card_enabled"] = bool(row.card_enabled) if row else True
    return out


async def mode_out(session: AsyncSession, bot) -> dict:
    icon, name, about, steps = MODES.get(bot.kind, MODES[STANDARD])
    return {
        "kind": bot.kind, "icon": icon, "name": name, "about": about, "steps": steps,
        "metrics": await metrics(session, bot), "payment": await payment_settings(session, bot),
        "kinds": [{"kind": k, "icon": v[0], "name": v[1], "about": v[2]} for k, v in MODES.items()],
    }


@router.get("/bots/{bot_id}/mode")
async def get_mode(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await mode_out(session, await owned_bot(session, user, bot_id))


@router.put("/bots/{bot_id}/mode")
async def put_mode(bot_id: int, body: ModeIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    if body.kind not in MODES:
        raise HTTPException(status_code=422, detail="Noma’lum rejim.")
    if body.kind != bot.kind:
        await set_kind(session, bot, body.kind)
    return {"bot": bot_out(bot), "mode": await mode_out(session, bot)}


@router.put("/bots/{bot_id}/payment")
async def put_payment(bot_id: int, body: PaymentIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    model = CARD_MODELS.get(bot.kind)
    if model is None:
        raise HTTPException(status_code=422, detail="Bu rejimda to‘lov sozlamalari yo‘q.")
    row = (await session.execute(select(model).where(model.bot_id == bot.id))).scalar_one_or_none()
    if row is None:
        row = model(bot_id=bot.id)
        session.add(row)
    row.card_number, row.card_holder, row.pay_note = _clean(body.card_number), _clean(body.card_holder), _clean(body.pay_note)
    if bot.kind == "shop" and body.card_enabled is not None:
        row.card_enabled = body.card_enabled
    await session.commit()
    return await payment_settings(session, bot)
