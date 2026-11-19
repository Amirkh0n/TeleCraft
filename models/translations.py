from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

ENTITIES = ("menu_text", "button_text", "action_text")


class ContentTranslation(Base):
    """A text of a child bot in another language. The base language lives in the menu/button itself."""
    __tablename__ = "content_translations"
    __table_args__ = (UniqueConstraint("entity", "entity_id", "lang", name="uq_content_translation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    entity: Mapped[str] = mapped_column(String(16), nullable=False)  # menu_text | button_text | action_text
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)  # menu.id / button.id
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
