from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from core.logger import get_logger

logger = get_logger("middleware")


class ErrorResponse(BaseModel):
    error: str
    message: str
    status_code: int
    details: Optional[dict] = None


async def http_error_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    error_data = ErrorResponse(
        error=exc.detail if isinstance(exc.detail, str) else "Error",
        message=str(exc.detail) if isinstance(exc.detail, str) else "An error occurred",
        status_code=exc.status_code
    )
    
    logger.error(
        f"HTTP Error: {exc.status_code} - {exc.detail}",
        path=request.url.path,
        method=request.method
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_data.model_dump()
    )


async def general_error_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    error_data = ErrorResponse(
        error="Internal Server Error",
        message="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={
            "type": type(exc).__name__,
            "message": str(exc)
        } if settings.DEBUG else None
    )
    
    logger.error(
        f"Unhandled Exception: {type(exc).__name__}",
        error=str(exc),
        path=request.url.path,
        method=request.method,
        exc_info=True
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_data.model_dump()
    )


class ValidationError(Exception):
    """Custom validation error"""
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(message)


def validate_required(value, field_name: str, error_message: str = None):
    """Validate that a field is not empty"""
    if not value:
        message = error_message or f"{field_name} is required"
        raise ValidationError(message, field_name)
    return value


def validate_min_length(value: str, min_length: int, field_name: str):
    """Validate minimum string length"""
    if len(value) < min_length:
        raise ValidationError(
            f"{field_name} must be at least {min_length} characters",
            field_name
        )
    return value


def validate_max_length(value: str, max_length: int, field_name: str):
    """Validate maximum string length"""
    if len(value) > max_length:
        raise ValidationError(
            f"{field_name} must not exceed {max_length} characters",
            field_name
        )
    return value


def validate_url(value: str, field_name: str):
    """Validate URL format"""
    import re
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    if not re.match(pattern, value):
        raise ValidationError(
            f"{field_name} must be a valid URL",
            field_name
        )
    return value
