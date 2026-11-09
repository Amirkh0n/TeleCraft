from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

# Answer types a form question can collect.
FIELD_TEXT = "text"
FIELD_NUMBER = "number"
FIELD_PHONE = "phone"
FIELD_EMAIL = "email"
FIELD_CHOICE = "choice"
FIELD_PHOTO = "photo"
FIELD_LOCATION = "location"
FIELD_TYPES = (FIELD_TEXT, FIELD_NUMBER, FIELD_PHONE, FIELD_EMAIL, FIELD_CHOICE, FIELD_PHOTO, FIELD_LOCATION)


class Form(Base):
    """A questionnaire a child bot's user can fill in (application, order, survey...)."""

    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Shown to the user right before the first question.
    intro_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Shown to the user after the last answer.
    final_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notify_admins: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)

    bot = relationship("Bot", backref="forms")
    fields = relationship(
        "FormField", back_populates="form", order_by="FormField.position", cascade="all, delete-orphan"
    )


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Short name used in the admin summary and as the CSV column title.
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # The question the user sees.
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default=FIELD_TEXT, server_default=FIELD_TEXT, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    # For FIELD_CHOICE: list of option strings.
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)

    form = relationship("Form", back_populates="fields")


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), index=True, nullable=False)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Snapshot: [{"label": ..., "type": ..., "value": ...}, ...] so old results survive form edits.
    answers: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    form = relationship("Form")


__all__ = [
    "Form", "FormField", "FormSubmission", "FIELD_TYPES",
    "FIELD_TEXT", "FIELD_NUMBER", "FIELD_PHONE", "FIELD_EMAIL", "FIELD_CHOICE", "FIELD_PHOTO", "FIELD_LOCATION",
]
