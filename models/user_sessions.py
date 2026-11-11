from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, JSON, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id"),
        nullable=False,
        index=True
    )

    tg_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True
    )

    current_menu_id: Mapped[int] = mapped_column(
        ForeignKey("menus.id"),
        nullable=False
    )

    pending_admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # Form the user is filling in right now (None when not in a form).
    form_id: Mapped[int | None] = mapped_column(ForeignKey("forms.id"), nullable=True)
    form_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    form_data: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # True while a reply keyboard from our bot is shown in this chat (so it can be removed later).
    reply_keyboard_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # Small state machine used by cinema admins (e.g. "await_video"); None when idle.
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    bot = relationship("Bot")
    menu = relationship("Menu")

    __table_args__ = (
        Index("ix_bot_user", "bot_id", "tg_user_id"),
    )
