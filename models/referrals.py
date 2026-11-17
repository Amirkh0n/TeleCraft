"""Referral invitations: who brought whom to the main bot, and whether that friend built a bot."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    referred_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)  # a person is invited once
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # friend created a bot
