from urllib.parse import urljoin

from core.config import settings


def editor_url() -> str | None:
    """HTTPS address of the Mini App, or None when the public URL is not a secure one
    (Telegram refuses to open Mini Apps over plain http)."""
    base = (settings.PUBLIC_BASE_URL or "").strip()
    if not base.lower().startswith("https://") or "your-app" in base:
        return None
    return urljoin(base.rstrip("/") + "/", "app/")
