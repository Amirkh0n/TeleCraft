from typing import Optional, Any
from enum import Enum
from core.errors import ValidationError, validate_required, validate_min_length, validate_max_length, validate_url
from core.logger import get_logger

logger = get_logger("validators")


class ActionTypes(str, Enum):
    TEXT = "text"
    LINK = "link"
    MENU = "menu"
    ADMIN = "admin"
    FILE = "file"
    VIDEO = "video"


def validate_action_type(action_type: Any) -> ActionTypes:
    """Validate action type"""
    if not isinstance(action_type, str):
        raise ValidationError("Action type must be a string")
    
    try:
        return ActionTypes(action_type.lower())
    except ValueError:
        raise ValidationError(
            f"Invalid action type: {action_type}. Valid types: {[t.value for t in ActionTypes]}"
        )


def validate_bot_token(token: Any) -> str:
    """Validate bot token"""
    validate_required(token, "bot token")
    validate_min_length(token, 30, "bot token")
    return str(token)


def validate_user_id(user_id: Any) -> int:
    """Validate Telegram user ID"""
    validate_required(user_id, "user ID")
    try:
        return int(user_id)
    except (ValueError, TypeError):
        raise ValidationError("User ID must be an integer")


def validate_menu_id(menu_id: Any) -> int:
    """Validate menu ID"""
    validate_required(menu_id, "menu ID")
    try:
        return int(menu_id)
    except (ValueError, TypeError):
        raise ValidationError("Menu ID must be an integer")


def validate_button_id(button_id: Any) -> int:
    """Validate button ID"""
    validate_required(button_id, "button ID")
    try:
        return int(button_id)
    except (ValueError, TypeError):
        raise ValidationError("Button ID must be an integer")


def validate_text_length(text: Any, max_length: int = 1024) -> str:
    """Validate text length"""
    if not text:
        raise ValidationError("Text cannot be empty")
    
    text_str = str(text)
    validate_max_length(text_str, max_length, "text")
    return text_str


def validate_menu_title(title: Any, min_length: int = 1, max_length: int = 255) -> str:
    """Validate menu title"""
    validate_required(title, "menu title")
    validate_min_length(title, min_length, "menu title")
    validate_max_length(title, max_length, "menu title")
    return str(title).strip()


def validate_button_text(text: Any, min_length: int = 1, max_length: int = 255) -> str:
    """Validate button text"""
    validate_required(text, "button text")
    validate_min_length(text, min_length, "button text")
    validate_max_length(text, max_length, "button text")
    return str(text).strip()


def validate_action_value(value: Any, action_type: str) -> Optional[str]:
    """Validate action value based on action type"""
    if action_type == ActionTypes.LINK.value:
        validate_required(value, "action value")
        return validate_url(value, "action value")
    elif action_type in [ActionTypes.TEXT.value, ActionTypes.ADMIN.value]:
        return validate_text_length(value)
    elif action_type in [ActionTypes.FILE.value, ActionTypes.VIDEO.value]:
        validate_required(value, "action value")
        return str(value)
    
    return str(value) if value else None


def validate_admin_id(admin_id: Any) -> int:
    """Validate admin Telegram ID"""
    return validate_user_id(admin_id)


def validate_code(code: Any) -> str:
    """Validate inline code"""
    validate_required(code, "code")
    validate_min_length(code, 1, "code")
    validate_max_length(code, 100, "code")
    return str(code).strip()
