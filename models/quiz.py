from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_QUIZ = "quiz"

ATTEMPT_ACTIVE, ATTEMPT_FINISHED, ATTEMPT_ABANDONED = "active", "finished", "abandoned"


class QuizSettings(Base):
    """One row per quiz bot."""
    __tablename__ = "quiz_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    who_can_create: Mapped[str] = mapped_column(String(10), default="everyone", server_default="everyone", nullable=False)  # everyone / admins
    max_tests_per_user: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)


class QuizTest(Base):
    __tablename__ = "quiz_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    owner_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_limit_sec: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)  # per question
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    pick_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # random subset size per attempt
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)  # admins can hide
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    questions_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    plays: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("quiz_tests.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    correct: Mapped[list] = mapped_column(JSON, nullable=False)  # indexes into options
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    test_id: Mapped[int] = mapped_column(ForeignKey("quiz_tests.id", ondelete="CASCADE"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=ATTEMPT_ACTIVE, server_default=ATTEMPT_ACTIVE, nullable=False)
    order: Mapped[list] = mapped_column(JSON, nullable=False)  # question ids in the order they are asked
    current: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    missed_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    answers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [{"q": id, "ok": bool|None, "sel": [...]}]
    time_spent_sec: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuizPoll(Base):
    """A poll we sent. Persisted so answers/timeouts survive a restart."""
    __tablename__ = "quiz_polls"

    poll_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id", ondelete="CASCADE"), index=True, nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    option_order: Mapped[list] = mapped_column(JSON, nullable=False)  # displayed position -> original option index
    is_quiz: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
