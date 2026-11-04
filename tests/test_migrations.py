"""issue #13: Alembic вместо create_all, chat_settings.data в JSONB. База для тестов не нужна."""
import asyncio
import importlib

from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from bot.database.models import Base, ChatSettings

db_engine = importlib.import_module("bot.database.engine")


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(db_engine.alembic_config())


def test_single_linear_history():
    script = _script()
    assert script.get_heads() == ["0002_chat_settings_jsonb"]
    assert [rev.revision for rev in script.walk_revisions()] == ["0002_chat_settings_jsonb", "0001_baseline"]


def test_baseline_covers_every_model_table():
    # Если добавляете модель или колонку — нужна новая ревизия, а не правка 0001.
    baseline = _script().get_revision("0001_baseline").module.metadata
    assert set(baseline.tables) == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert set(baseline.tables[name].columns.keys()) == set(table.columns.keys()), name


def test_chat_settings_data_is_jsonb():
    assert isinstance(ChatSettings.__table__.columns["data"].type, postgresql.JSONB)


def test_init_models_runs_alembic_upgrade(monkeypatch):
    calls = []

    class FakeConn:
        async def run_sync(self, fn):
            fn("sync-connection")

    class FakeBegin:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    def fake_upgrade(config, revision):
        calls.append((config.attributes["connection"], revision))

    monkeypatch.setattr(db_engine, "engine", FakeEngine())
    monkeypatch.setattr(db_engine.command, "upgrade", fake_upgrade)
    asyncio.run(db_engine.init_models())
    assert calls == [("sync-connection", "head")]
