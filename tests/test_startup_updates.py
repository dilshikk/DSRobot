"""issue #94: при перезапуске накопившиеся апдейты по умолчанию не выбрасываются."""
import asyncio

from bot.config import Settings
from bot.main import prepare_bots_for_polling


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def delete_webhook(self, drop_pending_updates: bool = False):
        self.calls.append(drop_pending_updates)


def test_pending_updates_are_kept_by_default(monkeypatch):
    monkeypatch.delenv("DROP_PENDING_UPDATES", raising=False)
    assert Settings(_env_file=None).drop_pending_updates is False


def test_drop_pending_updates_can_be_enabled(monkeypatch):
    monkeypatch.setenv("DROP_PENDING_UPDATES", "true")
    assert Settings(_env_file=None).drop_pending_updates is True


def test_prepare_bots_passes_setting_to_every_bot():
    bots = [FakeBot(), FakeBot()]
    asyncio.run(prepare_bots_for_polling(bots, drop_pending=False))
    assert [b.calls for b in bots] == [[False], [False]]
