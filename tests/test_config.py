"""Конфигурация из .env.example должна загружаться без ошибок (issue #33)."""
from pathlib import Path

import pytest

from bot.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("BOT_ID", "SUPPORT_CHAT_ID", "SENTRY_DSN", "REDIS_PASSWORD", "CLONE_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_env_example_loads():
    settings = Settings(_env_file=ENV_EXAMPLE)
    assert settings.bot_id == 123456
    assert settings.support_chat_id is None
    assert settings.clone_encryption_key is None
    assert settings.sentry_dsn is None


def test_empty_env_var_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SUPPORT_CHAT_ID", "")
    monkeypatch.setenv("BOT_ID", "")
    settings = Settings(_env_file=None)
    assert settings.support_chat_id is None
    assert settings.bot_id is None


def test_env_example_has_no_inline_comments():
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            assert "#" not in line.split("=", 1)[1], line
