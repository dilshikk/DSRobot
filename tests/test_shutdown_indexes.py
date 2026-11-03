"""issue #13: индексы под частые запросы и корректное закрытие соединений."""
import asyncio
import inspect

from bot import main as bot_main
from bot.database import engine as db_engine
from bot.services import cache


class _Recorder:
    def __init__(self, calls: list, name: str) -> None:
        self._calls = calls
        self._name = name

    async def __call__(self):
        self._calls.append(self._name)


def test_indexes_are_idempotent_and_cover_hot_queries():
    ddl = " ".join(db_engine.INDEXES_DDL)
    assert all(stmt.startswith("CREATE INDEX IF NOT EXISTS") for stmt in db_engine.INDEXES_DDL)
    assert "audit_log (chat_id, created_at)" in ddl
    assert "banned_words (chat_id)" in ddl


def test_init_models_creates_indexes():
    assert "_create_indexes" in inspect.getsource(db_engine.init_models)


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
