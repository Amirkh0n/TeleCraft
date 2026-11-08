import os

# Must be set before any application module is imported.
os.environ.setdefault("TELEGRAM_TOKEN", "111111:test_constructor_token_not_real_xxxxxxxx")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key")
