from sqlalchemy import select, func, insert
from core.database import AsyncSessionLocal
from models.analytics import AnalyticsEvent, BotStats, UserStats, BotMetrics
from core.logger import get_logger
from typing import Optional, Dict, Any

logger = get_logger("analytics")


async def track_event(
    bot_id: int,
    event_type: str,
    user_id: Optional[int] = None,
    menu_id: Optional[int] = None,
    button_id: Optional[int] = None,
    action_taken: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Track an analytics event"""
    try:
        async with AsyncSessionLocal() as session:
            event = AnalyticsEvent(
                bot_id=bot_id,
                event_type=event_type,
                user_id=user_id,
                menu_id=menu_id,
                button_id=button_id,
                action_taken=action_taken,
                metadata=metadata or {}
            )
            session.add(event)
            await session.commit()
            
            # Update bot stats
            await update_bot_stats(session, bot_id)
            
            # Update user stats if applicable
            if user_id:
                await update_user_stats(session, bot_id, user_id)
                
    except Exception as e:
        logger.error(f"Failed to track analytics event: {e}")


async def update_bot_stats(session, bot_id: int):
    """Update bot statistics"""
    # Update total events
    event_count = await session.execute(
        select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.bot_id == bot_id)
    )
    total_events = event_count.scalar() or 0
    
    # Update unique users
    user_count = await session.execute(
        select(func.count(func.distinct(AnalyticsEvent.user_id))).where(AnalyticsEvent.bot_id == bot_id)
    )
    unique_users = user_count.scalar() or 0
    
    # Update menu count
    menu_count = await session.execute(
        select(func.count()).where(AnalyticsEvent.menu_id.is_not(None))
    )
    active_menus = menu_count.scalar() or 0
    
    # Update button count
    button_count = await session.execute(
        select(func.count()).where(AnalyticsEvent.button_id.is_not(None))
    )
    total_buttons = button_count.scalar() or 0
    
    # Update or create bot stats
    result = await session.execute(
        select(BotStats).where(BotStats.bot_id == bot_id)
    )
    stats = result.scalar_one_or_none()
    
    if stats:
        stats.total_events = total_events
        stats.total_users = unique_users
        stats.active_menus = active_menus
        stats.total_buttons = total_buttons
    else:
        stats = BotStats(
            bot_id=bot_id,
            total_events=total_events,
            total_users=unique_users,
            active_menus=active_menus,
            total_buttons=total_buttons
        )
        session.add(stats)


async def update_user_stats(session, bot_id: int, user_id: int):
    """Update user statistics"""
    result = await session.execute(
        select(UserStats).where(
            UserStats.bot_id == bot_id,
            UserStats.user_id == user_id
        )
    )
    stats = result.scalar_one_or_none()
    
    if stats:
        stats.total_messages += 1
        if menu_id and stats.unique_menus_visited < 1000:
            stats.unique_menus_visited = await session.execute(
                select(func.count(func.distinct(UserStats.unique_menus_visited)))
            ).scalar() or 0
        stats.last_active = func.now()
    else:
        stats = UserStats(
            bot_id=bot_id,
            user_id=user_id,
            total_messages=1
        )
        session.add(stats)


async def get_bot_stats(bot_id: int) -> Optional[Dict[str, Any]]:
    """Get bot statistics"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(BotStats).where(BotStats.bot_id == bot_id)
            )
            stats = result.scalar_one_or_none()
            
            if stats:
                return {
                    "bot_id": bot_id,
                    "total_users": stats.total_users,
                    "total_events": stats.total_events,
                    "active_menus": stats.active_menus,
                    "total_buttons": stats.total_buttons,
                    "last_updated": stats.last_updated
                }
    except Exception as e:
        logger.error(f"Failed to get bot stats: {e}")
    
    return None


async def get_user_stats(bot_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Get user statistics"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserStats).where(
                    UserStats.bot_id == bot_id,
                    UserStats.user_id == user_id
                )
            )
            stats = result.scalar_one_or_none()
            
            if stats:
                return {
                    "bot_id": bot_id,
                    "user_id": user_id,
                    "total_messages": stats.total_messages,
                    "unique_menus_visited": stats.unique_menus_visited,
                    "first_seen": stats.first_seen,
                    "last_active": stats.last_active
                }
    except Exception as e:
        logger.error(f"Failed to get user stats: {e}")
    
    return None


async def record_metric(bot_id: int, metric_type: str, metric_value: float):
    """Record a metric for monitoring"""
    try:
        async with AsyncSessionLocal() as session:
            metric = BotMetrics(
                bot_id=bot_id,
                metric_type=metric_type,
                metric_value=metric_value
            )
            session.add(metric)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to record metric: {e}")


async def get_analytics_summary(bot_id: int) -> Dict[str, Any]:
    """Get comprehensive analytics summary for a bot"""
    try:
        async with AsyncSessionLocal() as session:
            # Get basic stats
            stats = await get_bot_stats(bot_id)
            if not stats:
                stats = {}
            
            # Get event breakdown
            event_breakdown = await session.execute(
                select(
                    AnalyticsEvent.event_type,
                    func.count(AnalyticsEvent.id).label("count")
                )
                .where(AnalyticsEvent.bot_id == bot_id)
                .group_by(AnalyticsEvent.event_type)
            )
            
            event_types = {}
            for event_type, count in event_breakdown:
                event_types[event_type] = count
            
            # Get recent activity
            recent_events = await session.execute(
                select(AnalyticsEvent)
                .where(AnalyticsEvent.bot_id == bot_id)
                .order_by(AnalyticsEvent.created_at.desc())
                .limit(10)
            )
            
            recent_activities = [
                {
                    "event_type": event.event_type,
                    "user_id": event.user_id,
                    "menu_id": event.menu_id,
                    "button_id": event.button_id,
                    "created_at": event.created_at
                }
                for event in recent_events.scalars().all()
            ]
            
            return {
                "bot_id": bot_id,
                "stats": stats,
                "event_types": event_types,
                "recent_activities": recent_activities,
                "timestamp": func.now()
            }
    except Exception as e:
        logger.error(f"Failed to get analytics summary: {e}")
        return {"bot_id": bot_id, "error": str(e)}
