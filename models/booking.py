from datetime import date, datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_BOOKING = "booking"

PENDING, CONFIRMED, CANCELLED, REJECTED, DONE, NO_SHOW = (
    "pending", "confirmed", "cancelled", "rejected", "done", "no_show",
)
ACTIVE_STATUSES = (PENDING, CONFIRMED)  # these occupy a time slot


class BookingSettings(Base):
    """One row per booking bot."""
    __tablename__ = "booking_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent", server_default="Asia/Tashkent", nullable=False)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    slot_step_min: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    min_notice_min: Mapped[int] = mapped_column(Integer, default=60, server_default="60", nullable=False)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    cancel_deadline_min: Mapped[int] = mapped_column(Integer, default=120, server_default="120", nullable=False)
    reminders: Mapped[list] = mapped_column(JSON, default=lambda: [1440, 60], nullable=False)  # minutes before start
    contact_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class BookingService(Base):
    __tablename__ = "booking_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class BookingStaff(Base):
    __tablename__ = "booking_staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class BookingStaffService(Base):
    """Which services a specialist performs. A specialist without rows performs all of them."""
    __tablename__ = "booking_staff_services"

    staff_id: Mapped[int] = mapped_column(ForeignKey("booking_staff.id", ondelete="CASCADE"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("booking_services.id", ondelete="CASCADE"), primary_key=True)


class BookingHours(Base):
    """Working intervals (minutes from midnight). ``staff_id`` NULL = business-wide hours."""
    __tablename__ = "booking_hours"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("booking_staff.id", ondelete="CASCADE"), nullable=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday
    start_min: Mapped[int] = mapped_column(Integer, nullable=False)
    end_min: Mapped[int] = mapped_column(Integer, nullable=False)


class BookingDayOff(Base):
    __tablename__ = "booking_days_off"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("booking_staff.id", ondelete="CASCADE"), nullable=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("booking_services.id", ondelete="SET NULL"), nullable=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("booking_staff.id", ondelete="SET NULL"), nullable=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # snapshots: the booking must stay readable after the service/specialist is renamed or deleted
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    staff_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=PENDING, server_default=PENDING, index=True, nullable=False)
    reminders_sent: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    cancelled_by: Mapped[str | None] = mapped_column(String(16), nullable=True)  # client / admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
