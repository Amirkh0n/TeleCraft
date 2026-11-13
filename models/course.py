from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_COURSE = "course"

ACCESS_FREE, ACCESS_CODE, ACCESS_PAID = "free", "code", "paid"
UNLOCK_ALL, UNLOCK_SEQ, UNLOCK_DRIP = "all", "seq", "drip"
PAY_PENDING, PAY_APPROVED, PAY_REJECTED = "pending", "approved", "rejected"
VIA_FREE, VIA_CODE, VIA_PAID, VIA_ADMIN = "free", "code", "paid", "admin"


class CourseSettings(Base):
    """One row per course bot."""
    __tablename__ = "course_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent", server_default="Asia/Tashkent", nullable=False)
    drip_hour: Mapped[int] = mapped_column(Integer, default=9, server_default="9", nullable=False)  # local hour new lessons open
    card_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    card_holder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pay_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    questions_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access: Mapped[str] = mapped_column(String(10), default=ACCESS_FREE, server_default=ACCESS_FREE, nullable=False)
    access_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    unlock_mode: Mapped[str] = mapped_column(String(10), default=UNLOCK_ALL, server_default=UNLOCK_ALL, nullable=False)
    drip_days: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class Lesson(Base):
    __tablename__ = "course_lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    module_id: Mapped[int] = mapped_column(ForeignKey("course_modules.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)


class LessonFile(Base):
    """One attachment of a lesson. ``file_id`` belongs to this bot (uploaded through it)."""
    __tablename__ = "course_lesson_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("course_lessons.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # video / audio / document / photo
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Enrollment(Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (UniqueConstraint("course_id", "tg_user_id", name="uq_course_enrollment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    via: Mapped[str] = mapped_column(String(10), default=VIA_FREE, server_default=VIA_FREE, nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notified_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)  # drip lessons already announced
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LessonProgress(Base):
    __tablename__ = "course_progress"
    __table_args__ = (UniqueConstraint("lesson_id", "tg_user_id", name="uq_course_progress"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("course_lessons.id", ondelete="CASCADE"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoursePayment(Base):
    __tablename__ = "course_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    receipt_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    receipt_type: Mapped[str] = mapped_column(String(10), default="photo", server_default="photo", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=PAY_PENDING, server_default=PAY_PENDING, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CourseQuestion(Base):
    __tablename__ = "course_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("course_lessons.id", ondelete="SET NULL"), nullable=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
