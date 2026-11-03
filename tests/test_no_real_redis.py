"""issue #48: тесты не требуют запущенного Redis."""
import asyncio

from bot.services import cache, chat_lang
from bot.utils import telegram as tg


def test_shared_client_is_replaced(fake_redis):
    assert cache.redis is fake_redis
    assert tg.redis is fake_redis


def test_chat_lang_does_not_touch_redis_or_db():
    assert asyncio.run(chat_lang.get_chat_lang(-100)) == chat_lang.default_lang()


def test_fake_supports_ttl_nx_and_counters(fake_redis):
    async def scenario():
        assert await fake_redis.set("k", 1, ex=60, nx=True) is True
        assert await fake_redis.set("k", 2, nx=True) is None
        assert await fake_redis.incr("n") == 1
        assert await fake_redis.incr("n") == 2
        assert await fake_redis.ttl("n") == -1
        await fake_redis.expire("n", 30)
        assert 0 < await fake_redis.ttl("n") <= 30
        async with fake_redis.pipeline() as pipe:
            pipe.incr("p").expire("p", 10)
            assert await pipe.execute() == [1, True]
        assert await fake_redis.delete("k", "missing") == 1
        assert await fake_redis.get("k") is None

    asyncio.run(scenario())
