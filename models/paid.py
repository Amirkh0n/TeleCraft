from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_PAID = "paid"

SUB_ACTIVE, SUB_EXPIRED, SUB_CANCELLED = "active", "expired", "cancelled"
PAY_PENDING, PAY_APPROVED, PAY_REJECTED, PAY_CANCELLED = "pending", "approved", "rejected", "cancelled"
OPEN_PAY = ("draft", PAY_PENDING)  # a payment the student can still send a receipt for / admin can decide


class PaidSettings(Base):
    """One row per paid-channel bot."""
    __tablename__ = "paid_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    card_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    card_holder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pay_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    trial_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # plan whose channels the trial opens


class PaidChannel(Base):
    """A channel/group the bot guards (it must be an administrator there)."""
    __tablename__ = "paid_channels"
    __table_args__ = (UniqueConstraint("bot_id", "chat_id", name="uq_paid_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    chat_type: Mapped[str] = mapped_column(String(20), default="channel", server_default="channel", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class PaidPlan(Base):
    __tablename__ = "paid_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaidPlanChannel(Base):
    """Which channels a plan opens."""
    __tablename__ = "paid_plan_channels"

    plan_id: Mapped[int] = mapped_column(ForeignKey("paid_plans.id", ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("paid_channels.id", ondelete="CASCADE"), primary_key=True)


class PaidPromo(Base):
    __tablename__ = "paid_promos"
    __table_args__ = (UniqueConstraint("bot_id", "code", name="uq_paid_promo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)  # stored upper-case
    percent: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..100
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # fixed discount
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class PaidSub(Base):
    """A student's subscription to one plan. Paying again extends it."""
    __tablename__ = "paid_subs"
    __table_args__ = (UniqueConstraint("bot_id", "tg_user_id", "plan_id", name="uq_paid_sub"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("paid_plans.id"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default=SUB_ACTIVE, server_default=SUB_ACTIVE, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    reminded_3: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    reminded_1: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)


class PaidPayment(Base):
    __tablename__ = "paid_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("paid_plans.id"), nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_title: Mapped[str] = mapped_column(String(120), default="", nullable=False)  # snapshots survive plan edits
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    original_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # after the promo code
    promo_id: Mapped[int | None] = mapped_column(ForeignKey("paid_promos.id", ondelete="SET NULL"), nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft", nullable=False, index=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
