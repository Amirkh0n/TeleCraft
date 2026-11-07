from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    token: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    webhook_url: Mapped[str] = mapped_column(
        String(500),
        nullable=True
    )

    webhook_set: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    # Relationship
    owner = relationship("User", backref="bots")
