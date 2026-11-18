"""Platform pricing: an owner's account plan, per-bot licences, payments and notice markers."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

PAY_DRAFT, PAY_PENDING, PAY_APPROVED, PAY_REJECTED, PAY_CANCELLED = "draft", "pending", "approved", "rejected", "cancelled"
OPEN_PAY = (PAY_DRAFT, PAY_PENDING)  # a payment the owner can still send a receipt for / admin can decide
TARGET_PLAN, TARGET_BOT = "plan", "bot"


class AccountPlan(Base):
    """One row per owner who ever had a paid plan or a trial. No row = Free."""
    __tablename__ = "account_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # start / pro / business
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)


class BotLicense(Base):
    """A single bot paid for on its own: unlimited users and no brand footer for its current mode."""
    __tablename__ = "bot_licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # the mode that was paid for
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanPayment(Base):
    """A card + receipt-photo payment for a plan or a single bot, decided by a main-bot admin."""
    __tablename__ = "plan_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target: Mapped[str] = mapped_column(String(10), nullable=False)  # plan / bot
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id"), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=PAY_DRAFT, server_default=PAY_DRAFT, nullable=False, index=True)
    receipt_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    discount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)  # amount is already reduced by this


class PlanNotice(Base):
    """"Already told them" marker (reminders, limit warnings): the unique key makes each notice go out once."""
    __tablename__ = "plan_notices"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminLog(Base):
    """Who did what in the admin Mini App (manual plans, decisions, stopping bots, mass messages)."""
    __tablename__ = "admin_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AppSetting(Base):
    """Settings the admins edit in the Mini App (prices and limits), stored as JSON by key."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PromoCode(Base):
    """A discount code the owner types while paying: a percentage or a fixed amount, with an optional cap and expiry."""
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromoUse(Base):
    """One approved payment that used a code. A person can use a code once."""
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id", name="uq_promo_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("plan_payments.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
