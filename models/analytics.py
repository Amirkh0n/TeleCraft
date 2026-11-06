from sqlalchemy import BigInteger, String, Integer, DateTime, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from sqlalchemy.sql import func
from .base import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    bot_id: Mapped[int] = mapped_column(index=True)
    
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)
    
    menu_id: Mapped[int] = mapped_column(Integer, nullable=True)
    
    button_id: Mapped[int] = mapped_column(Integer, nullable=True)
    
    action_taken: Mapped[str] = mapped_column(String(255), nullable=True)
    
    extra_data: Mapped[dict] = mapped_column()
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )
    
    bot = relationship("Bot", backref="events")
    
    __table_args__ = (
        Index("ix_bot_event_type", "bot_id", "event_type"),
        Index("ix_user_event", "user_id", "event_type"),
    )


class BotStats(Base):
    __tablename__ = "bot_stats"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    bot_id: Mapped[int] = mapped_column(index=True, unique=True)
    
    total_users: Mapped[int] = mapped_column(Integer, default=0)
    
    total_events: Mapped[int] = mapped_column(Integer, default=0)
    
    active_menus: Mapped[int] = mapped_column(Integer, default=0)
    
    total_buttons: Mapped[int] = mapped_column(Integer, default=0)
    
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class UserStats(Base):
    __tablename__ = "user_stats"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    bot_id: Mapped[int] = mapped_column(index=True)
    
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    
    unique_menus_visited: Mapped[int] = mapped_column(Integer, default=0)
    
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True
    )
    
    bot = relationship("Bot")
    
    __table_args__ = (
        Index("ix_bot_user_stats", "bot_id", "user_id", unique=True),
    )


class BotMetrics(Base):
    __tablename__ = "bot_metrics"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    bot_id: Mapped[int] = mapped_column(index=True)
    
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )
    
    __table_args__ = (
        Index("ix_bot_metric", "bot_id", "metric_type", "recorded_at"),
    )
