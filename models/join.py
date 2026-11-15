from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_JOIN = "join"

MODE_AUTO, MODE_MANUAL, MODE_CAPTCHA = "auto", "manual", "captcha"
MODES = (MODE_AUTO, MODE_MANUAL, MODE_CAPTCHA)

# A request moves: pending -> (captcha) -> (questions) -> scheduled (auto) | review (manual) -> approved/declined.
ST_PENDING, ST_CAPTCHA, ST_QUESTIONS, ST_SCHEDULED, ST_REVIEW = "pending", "captcha", "questions", "scheduled", "review"
ST_APPROVED, ST_DECLINED, ST_EXPIRED = "approved", "declined", "expired"
OPEN_STATUSES = (ST_PENDING, ST_CAPTCHA, ST_QUESTIONS, ST_SCHEDULED, ST_REVIEW)
FINAL_STATUSES = (ST_APPROVED, ST_DECLINED, ST_EXPIRED)


class JoinSettings(Base):
    """Texts shared by every channel/group of one join-request bot."""
    __tablename__ = "join_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    welcome_text: Mapped[str | None] = mapped_column(Text, nullable=True)   # sent when a request arrives
    approved_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # sent after approval (optional)
    declined_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # sent after a decline (optional)


class JoinChat(Base):
    """A channel or group whose join requests this bot handles."""
    __tablename__ = "join_chats"
    __table_args__ = (UniqueConstraint("bot_id", "chat_id", name="uq_join_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    chat_type: Mapped[str] = mapped_column(String(20), default="channel", server_default="channel", nullable=False)
    mode: Mapped[str] = mapped_column(String(10), default=MODE_AUTO, server_default=MODE_AUTO, nullable=False)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    questions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # up to 3 texts
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JoinLink(Base):
    """A named invite link (creates_join_request) so admins can see which source brings people."""
    __tablename__ = "join_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    chat_ref: Mapped[int] = mapped_column(ForeignKey("join_chats.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JoinRequest(Base):
    __tablename__ = "join_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False, index=True)
    chat_ref: Mapped[int] = mapped_column(ForeignKey("join_chats.id", ondelete="CASCADE"), nullable=False, index=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("join_links.id", ondelete="SET NULL"), nullable=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=ST_PENDING, server_default=ST_PENDING, nullable=False, index=True)
    step: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)  # next question index
    answers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    dm_failed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # admin tg id, None = automatic
