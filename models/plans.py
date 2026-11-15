"""Platform pricing: an owner's account plan, per-bot licences, payments and notice markers."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
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


class PlanNotice(Base):
    """"Already told them" marker (reminders, limit warnings): the unique key makes each notice go out once."""
    __tablename__ = "plan_notices"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
