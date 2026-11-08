import pytest

from core import security
from core.config import settings

PLAIN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789"


def test_encrypt_roundtrip_and_is_not_plaintext():
    stored = security.encrypt_token(PLAIN)
    assert stored.startswith("enc:")
    assert PLAIN not in stored
    assert security.decrypt_token(stored) == PLAIN


def test_encrypt_is_idempotent():
    stored = security.encrypt_token(PLAIN)
    assert security.encrypt_token(stored) == stored


def test_plaintext_passes_through_decrypt():
    assert security.decrypt_token(PLAIN) == PLAIN


def test_hash_is_stable_and_differs_per_token():
    assert security.token_hash(PLAIN) == security.token_hash(PLAIN)
    assert security.token_hash(PLAIN) != security.token_hash(PLAIN + "x")
    assert PLAIN not in security.token_hash(PLAIN)


def test_webhook_secret_is_telegram_safe():
    secret = security.webhook_secret(PLAIN)
    assert 1 <= len(secret) <= 256
    assert secret.replace("-", "").replace("_", "").isalnum()


def test_secrets_match():
    secret = security.webhook_secret(PLAIN)
    assert security.secrets_match(secret, secret)
    assert not security.secrets_match("wrong", secret)
    assert not security.secrets_match(None, secret)


def test_old_key_still_decrypts_after_key_change(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    stored_with_fallback = security.encrypt_token(PLAIN)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "brand-new-primary-key")
    assert security.decrypt_token(stored_with_fallback) == PLAIN
    assert not security.uses_primary_key(stored_with_fallback)


def test_undecryptable_value_raises(monkeypatch):
    stored = security.encrypt_token(PLAIN)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "other-key")
    monkeypatch.setattr(settings, "TELEGRAM_TOKEN", "999:other_constructor_token")
    with pytest.raises(ValueError):
        security.decrypt_token(stored)
