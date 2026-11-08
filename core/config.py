from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    TELEGRAM_TOKEN: str = Field(..., description="Constructor bot Telegram token")
    BOT_TOKENS: str = Field(default="", description="List of user bot tokens (comma-separated)")
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./constructor.db", description="Database connection URL")
    WEBHOOK_HOST: str = Field(default="0.0.0.0", description="Webhook host")
    WEBHOOK_PORT: int = Field(default=8000, description="Webhook port")
    WEBHOOK_PATH: str = Field(default="/webhook/{token}", description="Webhook path")
    PUBLIC_BASE_URL: str = Field(
        default="https://your-app.onrender.com",
        description="Public base URL of the webhook server (used for auto setWebhook)"
    )
    ENCRYPTION_KEY: str = Field(
        default="",
        description="Long random string used to encrypt child-bot tokens. Set it in production.",
    )
    WEBHOOK_SECRET_ENFORCE: bool = Field(
        default=False,
        description="Reject child-bot webhook calls that lack Telegram's secret header. "
                    "Enable after one deploy, once every webhook has been re-registered.",
    )
    WEBHOOK_REFRESH_ON_START: bool = Field(
        default=True,
        description="Re-register child-bot webhooks on startup (applies URL and secret changes).",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(default="json", description="Log format (json or text)")
    MAX_CONNECTIONS: int = Field(default=20, description="Maximum database connections")
    CONNECTION_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    RATE_LIMIT_REQUESTS: int = Field(default=100, description="Rate limit per minute")
    RATE_LIMIT_WINDOW: int = Field(default=60, description="Rate limit window in seconds")
    ADMIN_IDS: str = Field(default="", description="List of admin user IDs (comma-separated)")
    DEBUG: bool = Field(default=False, description="Debug mode")
    TESTING: bool = Field(default=False, description="Testing mode")

    @property
    def bot_tokens_list(self) -> list[str]:
        """Convert comma-separated string to list"""
        if not self.BOT_TOKENS:
            return []
        return [token.strip() for token in self.BOT_TOKENS.split(",") if token.strip()]

    @property
    def admin_ids_list(self) -> list[int]:
        """Convert comma-separated string to list of integers"""
        if not self.ADMIN_IDS:
            return []
        return [int(id.strip()) for id in self.ADMIN_IDS.split(",") if id.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
