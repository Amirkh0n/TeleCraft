from sqlalchemy import Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base
import enum


class ActionType(enum.Enum):
    text = "text"
    link = "link"
    menu = "menu"
    admin = "admin"
    file = "file"
    video = "video"
    media = "media"  # value: JSON {"type", "file_id", "caption"}
    form = "form"    # value: form id


class ButtonAction(Base):
    __tablename__ = "button_actions"

    id: Mapped[int] = mapped_column(primary_key=True)

    button_id: Mapped[int] = mapped_column(
        ForeignKey("buttons.id"),
        unique=True,
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

    # Relationship
    button = relationship("Button", backref="action")
