"""
Crypto prices external api: /price <coin> [currency] через CoinGecko (см. CRYPTO_API_URL в .env).

issue #99:
- ответ кэшируется в Redis на CACHE_TTL_SEC по ключу coin:currency: бесплатный CoinGecko
  даёт ~30 запросов в минуту на IP, а все чаты и клоны работают с одного IP;
- одна общая HTTP-сессия (bot/services/http.py) вместо новой на каждую команду;
- тексты в locales/, ответ на языке чата;
- ошибки сети и разбора ответа логируются, а не глотаются через except Exception;
- цены меньше 1 выводятся с SIGNIFICANT_DIGITS значащими цифрами без экспоненты;
- вторая валюта аргументом: /price btc eur.
"""
from __future__ import annotations

import asyncio
import html
import logging
import math
import re

import aiohttp
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import settings
from bot.services.cache import get_json, set_json
from bot.services.http import get_http
from bot.utils.i18n import t

logger = logging.getLogger(__name__)

router = Router(name="crypto_prices")

COIN_ALIASES = {"btc": "bitcoin", "eth": "ethereum", "ton": "the-open-network", "usdt": "tether"}
# Валюта -> символ перед суммой. Пустая строка: код валюты пишется после суммы.
CURRENCIES = {
    "usd": "$", "eur": "\u20ac", "gbp": "\u00a3", "rub": "\u20bd",
    "uah": "", "kzt": "", "try": "", "jpy": "", "cny": "", "btc": "", "eth": "",
}
DEFAULT_CURRENCY = "usd"
CACHE_TTL_SEC = 60
REQUEST_TIMEOUT_SEC = 10
SIGNIFICANT_DIGITS = 8
# id монет CoinGecko: строчные буквы, цифры и дефис. Остальное не отправляем в API.
_COIN_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class PriceUnavailable(Exception):
    """CoinGecko не ответил, ответил ошибкой (429/5xx) или прислал не то."""


def price_cache_key(coin_id: str, currency: str) -> str:
    return f"price:{coin_id}:{currency}"


def parse_args(args: str | None) -> tuple[str, str] | None:
    """'btc eur' -> ('bitcoin', 'eur'). None, если аргументов нет или их больше двух."""
    parts = (args or "").lower().split()
    if not parts or len(parts) > 2:
        return None
    coin_id = COIN_ALIASES.get(parts[0], parts[0])
    currency = parts[1] if len(parts) == 2 else DEFAULT_CURRENCY
    return coin_id, currency


def format_amount(value: float) -> str:
    if value >= 1:
        return f"{value:,.2f}"
    if value <= 0:
        return "0"
    # Формат .Nf вместо .Ng: иначе 0.00001234 превращается в 1.234e-05.
    decimals = SIGNIFICANT_DIGITS - 1 - math.floor(math.log10(value))
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def format_price(value: float, currency: str) -> str:
    symbol = CURRENCIES.get(currency)
    amount = format_amount(value)
    return f"{symbol}{amount}" if symbol else f"{amount} {currency.upper()}"


async def fetch_price(coin_id: str, currency: str) -> float | None:
    """Цена монеты или None, если CoinGecko такой монеты не знает."""
    params = {"ids": coin_id, "vs_currencies": currency}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
    try:
        async with get_http().get(settings.crypto_api_url, params=params, timeout=timeout) as resp:
            if resp.status != 200:
                logger.warning("CoinGecko %s/%s: HTTP %s", coin_id, currency, resp.status)
                raise PriceUnavailable(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("CoinGecko %s/%s failed: %s", coin_id, currency, exc)
        raise PriceUnavailable(str(exc)) from exc

    if not isinstance(data, dict):
        logger.warning("CoinGecko %s/%s: unexpected response %r", coin_id, currency, data)
        raise PriceUnavailable("unexpected response")
    coin = data.get(coin_id)
    value = coin.get(currency) if isinstance(coin, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


async def get_price(coin_id: str, currency: str) -> float | None:
    """Цена из кэша Redis или из CoinGecko. Кэшируется и «монета не найдена»: опечатки не тратят лимит."""
    key = price_cache_key(coin_id, currency)
    cached = await get_json(key)
    if isinstance(cached, dict):
        return cached.get("price")
    value = await fetch_price(coin_id, currency)
    await set_json(key, {"price": value}, ex=CACHE_TTL_SEC)
    return value


@router.message(Command("price"))
async def price(message: Message, command: CommandObject, lang: str | None = None) -> None:
    lang = lang or settings.default_lang
    parsed = parse_args(command.args)
    if parsed is None:
        await message.answer(t(lang, "price_usage"))
        return
    coin_id, currency = parsed
    if currency not in CURRENCIES:
        await message.answer(t(lang, "price_bad_currency", currencies=", ".join(CURRENCIES)))
        return
    if not _COIN_ID_RE.match(coin_id):
        await message.answer(t(lang, "price_not_found"))
        return

    try:
        value = await get_price(coin_id, currency)
    except PriceUnavailable:
        await message.answer(t(lang, "price_unavailable"))
        return
    if value is None:
        await message.answer(t(lang, "price_not_found"))
        return
    await message.answer(
        t(lang, "price_result", coin=html.escape(coin_id.upper()), price=format_price(value, currency))
    )
