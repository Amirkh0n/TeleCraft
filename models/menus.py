from sqlalchemy import String, Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id"),
        index=True,
        nullable=False
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    message_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    is_start: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    # Relationships
    bot = relationship("Bot", backref="menus")
