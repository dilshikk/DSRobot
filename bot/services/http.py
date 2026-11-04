"""
Общая HTTP-сессия aiohttp для обращений к внешним API (issue #99).

aiohttp рекомендует одну ClientSession на приложение: она держит пул соединений,
и каждый запрос не делает заново TCP/TLS-рукопожатие. Сессия создаётся лениво при
первом запросе (внутри работающего event loop) и закрывается в shutdown_resources().
"""
from __future__ import annotations

import aiohttp

DEFAULT_TIMEOUT_SEC = 10

_session: aiohttp.ClientSession | None = None


def get_http() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SEC))
    return _session


async def close_http() -> None:
    global _session
    session, _session = _session, None
    if session is not None and not session.closed:
        await session.close()
