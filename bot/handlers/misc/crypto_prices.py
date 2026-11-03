"""Crypto prices external api: /price МОНЕТА через CoinGecko (см. CRYPTO_API_URL в .env).
Ответы — на языке чата (issue #12)."""
import asyncio
import logging
from html import escape

import aiohttp
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import settings
from bot.utils.i18n import t

router = Router(name="crypto_prices")
logger = logging.getLogger(__name__)

COIN_ALIASES = {"btc": "bitcoin", "eth": "ethereum", "ton": "the-open-network", "usdt": "tether"}


def resolve_coin(raw: str) -> str:
    name = raw.strip().lower()
    return COIN_ALIASES.get(name, name)


def price_text(lang: str, coin_id: str, data: object) -> str:
    """data — ответ CoinGecko вида {"bitcoin": {"usd": 65000}}. Любая другая форма = «не найдена»."""
    entry = data.get(coin_id) if isinstance(data, dict) else None
    usd = entry.get("usd") if isinstance(entry, dict) else None
    if not isinstance(usd, (int, float)):
        return t(lang, "price_not_found")
    # coin_id приходит из сообщения пользователя — экранируем для parse_mode=HTML.
    return t(lang, "price_value", coin=escape(coin_id.upper()), price=f"{usd:,}")


@router.message(Command("price"))
async def price(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if not command.args:
        await message.answer(t(lang, "price_usage", options=" | ".join(COIN_ALIASES)))
        return
    coin_id = resolve_coin(command.args)

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(settings.crypto_api_url, params={"ids": coin_id, "vs_currencies": "usd"},
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        # Раньше ловилось любое Exception и ошибка не писалась в лог (в духе #9).
        logger.warning("Crypto price request failed for %s: %s", coin_id, exc)
        await message.answer(t(lang, "price_unavailable"))
        return

    await message.answer(price_text(lang, coin_id, data))
