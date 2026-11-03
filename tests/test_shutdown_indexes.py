"""issue #13: индексы под частые запросы и корректное закрытие соединений."""
import asyncio
import inspect

from bot import main as bot_main
from bot.database import engine as db_engine
from bot.services import cache


def test_indexes_are_idempotent_and_cover_hot_queries():
    ddl = " ".join(db_engine.INDEXES_DDL)
    assert all(stmt.startswith("CREATE INDEX IF NOT EXISTS") for stmt in db_engine.INDEXES_DDL)
    assert "audit_log (chat_id, created_at)" in ddl
    assert "banned_words (chat_id)" in ddl


def test_init_models_creates_indexes():
    assert "_create_indexes" in inspect.getsource(db_engine.init_models)


def test_close_db_disposes_engine(monkeypatch):
    calls = []

    async def fake_dispose():
        calls.append("dispose")

    monkeypatch.setattr(db_engine.engine, "dispose", fake_dispose)
    asyncio.run(db_engine.close_db())
    assert calls == ["dispose"]


def test_close_redis_closes_pool(monkeypatch):
    calls = []

    class FakeRedis:
        async def aclose(self):
            calls.append("aclose")

    monkeypatch.setattr(cache, "redis", FakeRedis())
    asyncio.run(cache.close_redis())
    assert calls == ["aclose"]


def test_shutdown_closes_everything_even_if_one_step_fails(monkeypatch):
    calls = []

    async def failing_redis():
        calls.append("redis")
        raise RuntimeError("boom")

    async def ok_db():
        calls.append("db")

    monkeypatch.setattr(bot_main, "close_redis", failing_redis)
    monkeypatch.setattr(bot_main, "close_db", ok_db)
    asyncio.run(bot_main.shutdown_resources())
    assert calls == ["redis", "db"]
