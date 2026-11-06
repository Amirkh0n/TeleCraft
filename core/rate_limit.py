from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
from core.logger import get_logger
from core.config import settings

logger = get_logger("rate_limit")


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        super().__init__(f"Rate limit exceeded: {limit} requests per {window} seconds")


class RateLimiter:
    """In-memory rate limiter with sliding window"""
    
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests: dict[str, list[datetime]] = defaultdict(list)
    
    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed"""
        now = datetime.utcnow()
        
        # Remove old requests outside the window
        self.requests[key] = [
            timestamp for timestamp in self.requests[key]
            if now - timestamp < self.window
        ]
        
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        self.requests[key].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        """Get remaining requests for the key"""
        now = datetime.utcnow()
        
        self.requests[key] = [
            timestamp for timestamp in self.requests[key]
            if now - timestamp < self.window
        ]
        
        return max(0, self.max_requests - len(self.requests[key]))


# Create rate limiter instances
api_limiter = RateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW
)

# Use the admin IDs list from settings
ADMIN_IDS = settings.admin_ids_list


async def rate_limit_middleware(request: Request, call_next):
    """Middleware for rate limiting"""
    # Skip rate limiting for health check endpoint
    if request.url.path == "/health" or request.url.path == "/docs" or request.url.path == "/openapi.json":
        response = await call_next(request)
        return response
    
    # Generate rate limit key from user ID or IP
    user_id = request.headers.get("X-User-ID")
    client_ip = request.client.host if request.client else "unknown"
    
    rate_limit_key = f"user:{user_id}" if user_id else f"ip:{client_ip}"
    
    if not api_limiter.is_allowed(rate_limit_key):
        logger.warning(
            f"Rate limit exceeded for key: {rate_limit_key}",
            user_id=user_id,
            ip=client_ip
        )
        
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "Rate limit exceeded",
                "message": "Too many requests. Please try again later.",
                "retry_after": settings.RATE_LIMIT_WINDOW
            }
        )
    
    response = await call_next(request)
    
    # Add rate limit headers
    remaining = api_limiter.get_remaining(rate_limit_key)
    response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int(datetime.utcnow().timestamp() + settings.RATE_LIMIT_WINDOW))
    
    return response


def check_rate_limit(user_id: Optional[int] = None, ip: Optional[str] = None) -> tuple[bool, Optional[int]]:
    """Manual rate limit check"""
    key = f"user:{user_id}" if user_id else f"ip:{ip}"
    
    if not api_limiter.is_allowed(key):
        return False, api_limiter.get_remaining(key)
    
    return True, api_limiter.get_remaining(key)
