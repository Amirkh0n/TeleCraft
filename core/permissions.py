from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.users import User
from core.logger import get_logger
from core.config import settings
from typing import Optional

logger = get_logger("permissions")


class PermissionError(Exception):
    """Permission error"""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def check_user_permission(user_id: int, required_role: str = "user") -> bool:
    """Check if user has required permission"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return False
            
            # In production, this would check roles from a separate table
            # For now, we'll use admin_ids from settings
            from core.config import settings
            
            if required_role == "admin" and user.tg_id in settings.ADMIN_IDS:
                return True
            
            return True  # All users have basic access
            
    except Exception as e:
        logger.error(f"Failed to check permission: {e}")
        return False


# Get admin IDs from settings
ADMIN_IDS = settings.admin_ids_list


async def get_user_role(user_id: int) -> str:
    """Get user role"""
    from core.config import settings
    
    if user_id in settings.ADMIN_IDS:
        return "admin"
    return "user"


async def require_admin(user_id: int):
    """Require admin permission"""
    if not await check_user_permission(user_id, "admin"):
        raise PermissionError("You don't have permission to perform this action")


async def get_user_by_tg_id(tg_id: int) -> Optional[User]:
    """Get user by Telegram ID"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id == tg_id)
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return None


async def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by database ID"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return None
