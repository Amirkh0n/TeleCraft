from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

BROADCAST_DRAFT = "draft"
BROADCAST_SENDING = "sending"
BROADCAST_DONE = "done"
BROADCAST_CANCELLED = "cancelled"


class BotUser(Base):
    """Everyone who ever talked to a child bot: the bot's audience."""
    __tablename__ = "bot_users"
    __table_args__ = (UniqueConstraint("bot_id", "tg_user_id", name="uq_bot_users_bot_tg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # /start payload of the first visit
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RequiredChannel(Base):
    """A channel/group users must join before they can use the bot."""
    __tablename__ = "required_channels"
    __table_args__ = (UniqueConstraint("bot_id", "chat_id", name="uq_required_channels_bot_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class Broadcast(Base):
    """A mass message. ``cursor`` is the last BotUser.id handled, so a restart can resume."""
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)  # constructor user's tg id
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=BROADCAST_DRAFT, server_default=BROADCAST_DRAFT, nullable=False)
    cursor: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    blocked: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
