"""
Шифрование токенов клонов (issue #6).

Токен клона даёт полный контроль над ботом, поэтому в БД он хранится только
зашифрованным (Fernet: AES-128-CBC + HMAC-SHA256). Ключ задаётся переменной
CLONE_ENCRYPTION_KEY и в БД не попадает: утечка дампа БД без ключа не раскрывает токены.

Сгенерировать ключ:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Fernet недетерминирован (одинаковый токен даёт разный шифротекст), поэтому для поиска
дублей рядом хранится SHA-256 отпечаток токена. Секретная часть токена Telegram —
длинная случайная строка, подобрать её по хэшу нереально.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from bot.config import settings

__all__ = [
    "CloneCryptoNotConfigured",
    "InvalidToken",
    "decrypt_token",
    "encrypt_token",
    "is_configured",
    "token_fingerprint",
]


class CloneCryptoNotConfigured(RuntimeError):
    """CLONE_ENCRYPTION_KEY не задан или некорректен."""


@lru_cache(maxsize=4)
def _fernet_for(key: str) -> Fernet:
    return Fernet(key.encode())


def _fernet() -> Fernet:
    key = (settings.clone_encryption_key or "").strip()
    if not key:
        raise CloneCryptoNotConfigured("CLONE_ENCRYPTION_KEY is not set")
    try:
        return _fernet_for(key)
    except (ValueError, TypeError) as exc:
        raise CloneCryptoNotConfigured("CLONE_ENCRYPTION_KEY is not a valid Fernet key") from exc


def is_configured() -> bool:
    try:
        _fernet()
    except CloneCryptoNotConfigured:
        return False
    return True


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Бросает InvalidToken, если шифротекст повреждён или зашифрован другим ключом."""
    return _fernet().decrypt(encrypted.encode()).decode()


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
