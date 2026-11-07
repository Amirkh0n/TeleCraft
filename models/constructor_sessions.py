from sqlalchemy import String, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime

from .base import Base


class ConstructorSession(Base):
    """Persistent navigation and draft state for a constructor user."""

    __tablename__ = "constructor_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    current_bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id"), nullable=True)
    current_menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id"), nullable=True)
    current_button_id: Mapped[int | None] = mapped_column(ForeignKey("buttons.id"), nullable=True)
    pending_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
