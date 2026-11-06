from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class AnalyticsEvent(BaseModel):
    bot_id: int
    event_type: str
    user_id: Optional[int] = None
    menu_id: Optional[int] = None
    button_id: Optional[int] = None
    data: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BotStats(BaseModel):
    bot_id: int
    total_users: int = 0
    total_events: int = 0
    active_menus: int = 0
    total_buttons: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserStats(BaseModel):
    user_id: int
    bot_id: int
    total_messages: int = 0
    unique_menus_visited: int = 0
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)


class BulkOperation(BaseModel):
    operation_type: str
    bot_id: int
    items: List[int] = Field(default_factory=list)
    status: str = "pending"
    progress: float = 0.0
    completed_at: Optional[datetime] = None


class ExportData(BaseModel):
    bot_id: int
    menus: List[dict]
    buttons: List[dict]
    actions: List[dict]
    export_type: str
    exported_at: datetime = Field(default_factory=datetime.utcnow)
