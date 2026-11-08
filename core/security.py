"""Token encryption, lookup hashing and webhook secrets.

Child-bot tokens are never stored in plaintext. A token is stored encrypted
(Fernet, prefix ``enc:``) and found again through a keyed hash (``token_hash``),
so Telegram tokens do not have to appear in URLs or equality queries.

Key handling:
* ``ENCRYPTION_KEY`` (any long random string) is the primary key. Set it in the
  hosting dashboard (e.g. Render environment).
* If it is empty, a key derived from ``TELEGRAM_TOKEN`` is used so existing
  deployments keep working. When ``ENCRYPTION_KEY`` is added later, old data is
  still readable (the fallback key is tried) and is re-encrypted on startup.
"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings
from core.logger import get_logger

logger = get_logger("security")

ENC_PREFIX = "enc:"


def _derive(raw: str, purpose: str) -> bytes:
    return hashlib.sha256(f"telecraft:{purpose}:{raw}".encode()).digest()


def _key_sources() -> list[str]:
    """Primary key first, then the TELEGRAM_TOKEN-derived fallback."""
    sources = []
    if settings.ENCRYPTION_KEY:
        sources.append(settings.ENCRYPTION_KEY)
    if settings.TELEGRAM_TOKEN and settings.TELEGRAM_TOKEN not in sources:
        sources.append(settings.TELEGRAM_TOKEN)
    return sources


def _fernet(raw: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_derive(raw, "fernet")))


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(ENC_PREFIX)


def encrypt_token(token: str) -> str:
    if is_encrypted(token):
        return token
    return ENC_PREFIX + _fernet(_key_sources()[0]).encrypt(token.encode()).decode()


def decrypt_token(value: str) -> str:
    """Return the plaintext token. Plaintext input (not yet migrated) passes through."""
    if not is_encrypted(value):
        return value
    payload = value[len(ENC_PREFIX):].encode()
    for raw in _key_sources():
        try:
            return _fernet(raw).decrypt(payload).decode()
        except InvalidToken:
            continue
    raise ValueError("Bot token cannot be decrypted with the configured keys")


def uses_primary_key(value: str) -> bool:
    """True if ``value`` is encrypted with the current primary key."""
    if not is_encrypted(value):
        return False
    try:
        _fernet(_key_sources()[0]).decrypt(value[len(ENC_PREFIX):].encode())
        return True
    except InvalidToken:
        return False


def token_hash(token: str) -> str:
    """Stable keyed hash used to look a bot up by its token."""
    return hmac.new(_derive(_key_sources()[0], "lookup"), token.encode(), hashlib.sha256).hexdigest()


def webhook_secret(token: str) -> str:
    """Per-bot value for Telegram's ``secret_token`` (allowed chars: A-Z a-z 0-9 _ -)."""
    return hmac.new(_derive(_key_sources()[0], "webhook"), token.encode(), hashlib.sha256).hexdigest()


def secrets_match(received: str | None, expected: str) -> bool:
    return received is not None and hmac.compare_digest(received, expected)
