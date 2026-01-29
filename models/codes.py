from sqlalchemy import String, Text, ForeignKey, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
from .button_actions import ActionType


class Code(Base):
    __tablename__ = "codes"

    id: Mapped[int] = mapped_column(primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id"),
        nullable=False,
        index=True
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType),
        nullable=False
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=True
    )

    bot = relationship("Bot", backref="codes")

    __table_args__ = (
        Index("ix_bot_code", "bot_id", "code"),
    )
