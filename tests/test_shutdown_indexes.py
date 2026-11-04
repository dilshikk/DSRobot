"""issue #13: индексы под частые запросы и корректное закрытие соединений."""
import asyncio
import importlib

from bot import main as bot_main
from bot.database import legacy
from bot.services import cache

# Не `from bot.database import engine`: пакет экспортирует объект AsyncEngine с тем же
# именем, и импорт вернул бы его, а не модуль.
db_engine = importlib.import_module("bot.database.engine")


class _Recorder:
    def __init__(self, calls: list, name: str) -> None:
        self._calls = calls
        self._name = name

    async def __call__(self):
        self._calls.append(self._name)


def test_indexes_are_idempotent_and_cover_hot_queries():
    ddl = " ".join(legacy.INDEXES_DDL)
    assert all(stmt.startswith("CREATE INDEX IF NOT EXISTS") for stmt in legacy.INDEXES_DDL)
    assert "audit_log (chat_id, created_at)" in ddl
    assert "banned_words (chat_id)" in ddl
    assert any("chat_users (user_id)" in stmt for stmt in legacy.CHAT_USERS_DDL)


def test_baseline_creates_indexes():
    executed = []

    class FakeResult:
        def scalar(self):
            return "date"

        def first(self):
            return None

    class FakeConn:
        def execute(self, stmt, params=None):
            executed.append(str(stmt))
            return FakeResult()

    legacy.run_all(FakeConn())
    for ddl in legacy.INDEXES_DDL:
        assert ddl in executed


def test_close_db_disposes_engine(monkeypatch):
    calls: list = []

    class FakeEngine:
        dispose = _Recorder(calls, "dispose")

    monkeypatch.setattr(db_engine, "engine", FakeEngine())
    asyncio.run(db_engine.close_db())
    assert calls == ["dispose"]


def test_close_redis_closes_pool(monkeypatch):
    calls: list = []

    class FakeRedis:
        aclose = _Recorder(calls, "aclose")

    monkeypatch.setattr(cache, "redis", FakeRedis())
    asyncio.run(cache.close_redis())
    assert calls == ["aclose"]


def test_shutdown_closes_everything_even_if_one_step_fails(monkeypatch):
    calls: list = []

    async def failing_redis():
        calls.append("redis")
        raise RuntimeError("boom")

    monkeypatch.setattr(bot_main, "close_redis", failing_redis)
    monkeypatch.setattr(bot_main, "close_db", _Recorder(calls, "db"))
    asyncio.run(bot_main.shutdown_resources())
    assert calls == ["redis", "db"]
