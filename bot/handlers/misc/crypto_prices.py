"""Crypto prices external api: /price <coin> через CoinGecko (см. CRYPTO_API_URL в .env)."""
import aiohttp
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import settings

router = Router(name="crypto_prices")

COIN_ALIASES = {"btc": "bitcoin", "eth": "ethereum", "ton": "the-open-network", "usdt": "tether"}


@router.message(Command("price"))
async def price(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Использование: /price <btc|eth|ton|...>")
        return
    coin_id = COIN_ALIASES.get(command.args.strip().lower(), command.args.strip().lower())

    async with aiohttp.ClientSession() as http:
        try:
            async with http.get(settings.crypto_api_url, params={"ids": coin_id, "vs_currencies": "usd"},
                                 timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json() if resp.status == 200 else None
        except Exception:
            await message.answer("\u26a0\ufe0f Не удалось получить курс (сервис недоступен).")
            return

    if not isinstance(data, dict):  # 429 / 5xx от CoinGecko
        await message.answer("\u26a0\ufe0f Не удалось получить курс (сервис недоступен).")
        return
    usd = (data.get(coin_id) or {}).get("usd")
    if usd is None:
        await message.answer("Монета не найдена. Пример: /price btc")
        return
    await message.answer(f"\U0001f4b1 {coin_id.upper()}: ${usd:,}")
