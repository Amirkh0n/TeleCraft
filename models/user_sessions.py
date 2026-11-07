from sqlalchemy import BigInteger, ForeignKey, Index
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

    bot = relationship("Bot")
    menu = relationship("Menu")

    __table_args__ = (
        Index("ix_bot_user", "bot_id", "tg_user_id"),
    )
