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

    # Optional media shown with the message. file_id belongs to the CHILD bot (see core/media.py).
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # "inline": buttons under the message. "reply": keyboard replacing the phone keyboard.
    keyboard_mode: Mapped[str] = mapped_column(
        String(10), default="inline", server_default="inline", nullable=False
    )
    # Buttons per row (1 or 2).
    columns: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    # Relationships
    bot = relationship("Bot", backref="menus")
