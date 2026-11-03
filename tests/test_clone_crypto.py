"""Тесты шифрования токенов клонов и списка разрешённых пользователей (issue #6)."""
import pytest
from cryptography.fernet import Fernet

from bot.config import settings
from bot.services import clone_crypto

TOKEN = "1234567890:AAH-secret_part_of_the_token_0123456789"


@pytest.fixture
def key(monkeypatch):
    value = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "clone_encryption_key", value)
    return value


def test_roundtrip(key):
    encrypted = clone_crypto.encrypt_token(TOKEN)
    assert clone_crypto.decrypt_token(encrypted) == TOKEN


def test_ciphertext_does_not_contain_token(key):
    encrypted = clone_crypto.encrypt_token(TOKEN)
    assert TOKEN not in encrypted
    assert "secret_part" not in encrypted


def test_ciphertext_is_random_but_fingerprint_is_stable(key):
    assert clone_crypto.encrypt_token(TOKEN) != clone_crypto.encrypt_token(TOKEN)
    assert clone_crypto.token_fingerprint(TOKEN) == clone_crypto.token_fingerprint(TOKEN)
    assert clone_crypto.token_fingerprint(TOKEN) != clone_crypto.token_fingerprint(TOKEN + "x")
    assert len(clone_crypto.token_fingerprint(TOKEN)) == 64


def test_other_key_cannot_decrypt(key, monkeypatch):
    encrypted = clone_crypto.encrypt_token(TOKEN)
    monkeypatch.setattr(settings, "clone_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(clone_crypto.InvalidToken):
        clone_crypto.decrypt_token(encrypted)


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-fernet-key"])
def test_missing_or_invalid_key_disables_clones(monkeypatch, value):
    monkeypatch.setattr(settings, "clone_encryption_key", value)
    assert not clone_crypto.is_configured()
    with pytest.raises(clone_crypto.CloneCryptoNotConfigured):
        clone_crypto.encrypt_token(TOKEN)


def test_valid_key_enables_clones(key):
    assert clone_crypto.is_configured()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", set()),
        ("123", {123}),
        (" 123 , 456,", {123, 456}),
        ("123,abc,-5,789", {123, 789}),
    ],
)
def test_allowed_user_ids_parsing(monkeypatch, raw, expected):
    monkeypatch.setattr(settings, "clone_allowed_user_ids", raw)
    assert settings.clone_allowed_ids == expected
