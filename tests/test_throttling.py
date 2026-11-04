"""issue #98: throttling команд атомарный и использует общее определение команды."""
import asyncio
from datetime import datetime

from aiogram.types import Chat, Message, MessageEntity, User

from bot.middlewares import throttling
from bot.middlewares.throttling import ThrottlingMiddleware


class YieldingRedis:
    """Отдаёт управление event loop внутри каждой команды, как настоящий сетевой клиент.
    Без этого гонка EXISTS/SET не воспроизводится."""

    def __init__(self, inner) -> None:
        self._inner = inner

    async def exists(self, *keys):
        await asyncio.sleep(0)
        return await self._inner.exists(*keys)

    async def set(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await self._inner.set(*args, **kwargs)


def _msg(text: str, *, command: bool = True, caption: bool = False) -> Message:
    entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))] if command else None
    return Message.model_construct(
        message_id=1,
        date=datetime.now(),
        chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="Test"),
        text=None if caption else text,
        entities=None if caption else entities,
        caption=text if caption else None,
        caption_entities=entities if caption else None,
    )


def _run_parallel(*messages: Message) -> list[Message]:
    handled: list[Message] = []
    middleware = ThrottlingMiddleware()

    async def handler(event, data):
        handled.append(event)

    async def run():
        await asyncio.gather(*(middleware(handler, m, {}) for m in messages))

    asyncio.run(run())
    return handled


def test_parallel_commands_are_handled_once(fake_redis, monkeypatch):
    monkeypatch.setattr(throttling, "redis", YieldingRedis(fake_redis))
    assert len(_run_parallel(_msg("/stats"), _msg("/stats"))) == 1


def test_slash_text_without_command_entity_is_not_throttled(fake_redis, monkeypatch):
    monkeypatch.setattr(throttling, "redis", YieldingRedis(fake_redis))
    assert len(_run_parallel(_msg("/ привет", command=False), _msg("/ привет", command=False))) == 2


def test_command_in_caption_is_throttled(fake_redis, monkeypatch):
    monkeypatch.setattr(throttling, "redis", YieldingRedis(fake_redis))
    assert len(_run_parallel(_msg("/stats", caption=True), _msg("/stats", caption=True))) == 1
