"""Общие настройки тестов.

bot.config создаёт Settings() при импорте и требует переменные окружения.
Задаём безопасные фиктивные значения ДО импорта модулей бота. Подключений к
PostgreSQL/Redis при импорте не происходит: движок и клиент создаются лениво.

issue #48: тесты не должны ходить в настоящий Redis и PostgreSQL. Фикстура
`fake_redis` (autouse) подменяет общий клиент Redis во всех модулях бота на
хранилище в памяти, а get_chat_lang() возвращает язык по умолчанию без БД.
Тесты, которым нужен свой фейк, по-прежнему могут подменить его через monkeypatch.
"""
import os
import sys
import time

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")


def _gh_escape(text: str) -> str:
    # Экранирование для workflow-команд GitHub Actions (::error ...::message).
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def pytest_terminal_summary(terminalreporter):
    """
    В GitHub Actions выводит упавшие тесты как аннотации (::error::), чтобы причина
    была видна прямо в PR и на странице запуска, без открытия полного лога.
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    reports = terminalreporter.stats.get("failed", []) + terminalreporter.stats.get("error", [])
    for report in reports:
        nodeid = getattr(report, "nodeid", "") or "collection"
        path = nodeid.split("::", 1)[0]
        details = (getattr(report, "longreprtext", "") or "")[-3000:]
        terminalreporter.write_line(
            f"::error file={path},title={_gh_escape(nodeid)}::{_gh_escape(details)}"
        )


class InMemoryRedis:
    """Минимальная асинхронная замена redis.asyncio.Redis (decode_responses=True)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expires: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        deadline = self.expires.get(key)
        if deadline is not None and deadline <= time.monotonic():
            self.data.pop(key, None)
            self.expires.pop(key, None)
        return key in self.data

    async def get(self, key):
        return self.data[key] if self._alive(key) else None

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and self._alive(key):
            return None
        self.data[key] = str(value)
        self.expires.pop(key, None)
        if ex:
            self.expires[key] = time.monotonic() + ex
        elif px:
            self.expires[key] = time.monotonic() + px / 1000
        return True

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if self._alive(key):
                removed += 1
            self.data.pop(key, None)
            self.expires.pop(key, None)
        return removed

    async def exists(self, *keys):
        return sum(1 for key in keys if self._alive(key))

    async def incr(self, key, amount=1):
        value = int(self.data[key]) + amount if self._alive(key) else amount
        self.data[key] = str(value)
        return value

    async def expire(self, key, seconds, nx=False):
        if not self._alive(key) or (nx and key in self.expires):
            return False
        self.expires[key] = time.monotonic() + seconds
        return True

    async def ttl(self, key):
        if not self._alive(key):
            return -2
        deadline = self.expires.get(key)
        return -1 if deadline is None else max(int(deadline - time.monotonic()), 0)

    def pipeline(self, transaction=True):
        return _InMemoryPipeline(self)


class _InMemoryPipeline:
    """Копит команды и выполняет их по execute(), как redis-py pipeline."""

    def __init__(self, redis: InMemoryRedis) -> None:
        self._redis = redis
        self._calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __getattr__(self, name):
        method = getattr(self._redis, name)

        def queue(*args, **kwargs):
            self._calls.append((method, args, kwargs))
            return self

        return queue

    async def execute(self):
        calls, self._calls = self._calls, []
        return [await method(*args, **kwargs) for method, args, kwargs in calls]


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Подменяет Redis и язык чата во всех загруженных модулях бота (issue #48)."""
    from bot.services import cache, chat_lang

    real_redis = cache.redis
    real_get_chat_lang = chat_lang.get_chat_lang
    fake = InMemoryRedis()

    async def fake_get_chat_lang(chat_id: int) -> str:
        return chat_lang.default_lang()

    # Модули делают `from bot.services.cache import redis`, поэтому подменяем ссылку в каждом.
    for name, module in list(sys.modules.items()):
        if not (name == "bot" or name.startswith("bot.")) or module is None:
            continue
        if getattr(module, "redis", None) is real_redis:
            monkeypatch.setattr(module, "redis", fake)
        if getattr(module, "get_chat_lang", None) is real_get_chat_lang:
            monkeypatch.setattr(module, "get_chat_lang", fake_get_chat_lang)
    return fake
