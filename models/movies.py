from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_STANDARD = "standard"
KIND_CINEMA = "cinema"


class Movie(Base):
    """A movie of a cinema bot. The video itself lives on Telegram: we keep only its file_id."""
    __tablename__ = "movies"
    __table_args__ = (UniqueConstraint("bot_id", "code", name="uq_movies_bot_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)  # what viewers type, e.g. "105"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), default="video", server_default="video", nullable=False)
    poster_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
