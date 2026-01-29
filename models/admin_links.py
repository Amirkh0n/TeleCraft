from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class AdminLink(Base):
    __tablename__ = "admin_links"

    id: Mapped[int] = mapped_column(primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id"),
        nullable=False,
        index=True
    )

    admin_tg_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False
    )

    bot = relationship("Bot", backref="admins")
