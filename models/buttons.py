from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Button(Base):
    __tablename__ = "buttons"

    id: Mapped[int] = mapped_column(primary_key=True)

    menu_id: Mapped[int] = mapped_column(
        ForeignKey("menus.id"),
        index=True,
        nullable=False
    )

    text: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    position: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # Relationships
    menu = relationship("Menu", backref="buttons")
