"""issue #99: /price кэширует ответ, переживает 429, локализован и форматирует мелкие цены."""
import asyncio
from types import SimpleNamespace

import aiohttp
import pytest
from aiogram.filters import CommandObject

from bot.handlers.misc import crypto_prices as cp
from bot.services import http
from bot.utils.i18n import t


class FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data


class FakeHttp:
    def __init__(self, status=200, data=None, error=None):
        self.status = status
        self.data = data
        self.error = error
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status, self.data)


@pytest.fixture
def fake_http(monkeypatch):
    def install(**kwargs):
        fake = FakeHttp(**kwargs)
        monkeypatch.setattr(cp, "get_http", lambda: fake)
        return fake

    return install


def _message():
    sent: list[str] = []

    async def answer(text, **kwargs):
        sent.append(text)

    return SimpleNamespace(chat=SimpleNamespace(id=-100), answer=answer), sent


def _run(message, args, lang="en"):
    command = CommandObject(prefix="/", command="price", args=args)
    asyncio.run(cp.price(message, command, lang=lang))


def test_success_is_cached(fake_http):
    fake = fake_http(data={"bitcoin": {"usd": 65000.5}})
    message, sent = _message()

    _run(message, "btc")
    _run(message, "BTC")

    expected = t("en", "price_result", coin="BITCOIN", price="$65,000.50")
    assert sent == [expected, expected]
    assert len(fake.calls) == 1


def test_rate_limit_is_reported_and_not_cached(fake_http):
    fake = fake_http(status=429, data={"status": {"error_code": 429}})
    message, sent = _message()

    _run(message, "btc")
    _run(message, "btc")

    assert sent == [t("en", "price_unavailable")] * 2
    assert len(fake.calls) == 2


def test_network_error_is_reported(fake_http):
    fake_http(error=aiohttp.ClientConnectionError("down"))
    message, sent = _message()

    _run(message, "btc")

    assert sent == [t("en", "price_unavailable")]


def test_unknown_coin(fake_http):
    fake = fake_http(data={})
    message, sent = _message()

    _run(message, "nosuchcoin")
    _run(message, "nosuchcoin")

    assert sent == [t("en", "price_not_found")] * 2
    assert len(fake.calls) == 1


def test_small_price_has_no_exponent(fake_http):
    fake_http(data={"shiba-inu": {"usd": 1.234e-05}})
    message, sent = _message()

    _run(message, "shiba-inu")

    assert sent == [t("en", "price_result", coin="SHIBA-INU", price="$0.00001234")]


def test_second_currency(fake_http):
    fake = fake_http(data={"ethereum": {"eur": 3000}})
    message, sent = _message()

    _run(message, "eth eur")

    assert fake.calls == [{"ids": "ethereum", "vs_currencies": "eur"}]
    assert sent == [t("en", "price_result", coin="ETHEREUM", price="\u20ac3,000.00")]


def test_bad_currency_and_usage_do_not_call_api(fake_http):
    fake = fake_http(data={})
    message, sent = _message()

    _run(message, "btc xyz")
    _run(message, None)
    _run(message, "<b>")

    assert sent[0] == t("en", "price_bad_currency", currencies=", ".join(cp.CURRENCIES))
    assert sent[1] == t("en", "price_usage")
    assert sent[2] == t("en", "price_not_found")
    assert fake.calls == []


def test_reply_follows_chat_language(fake_http):
    fake_http(status=500, data=None)
    message, sent = _message()

    _run(message, "btc", lang="ru")

    assert sent == [t("ru", "price_unavailable")]
    assert sent[0] != t("en", "price_unavailable")


@pytest.mark.parametrize("value, expected", [
    (65000.123, "65,000.12"),
    (1, "1.00"),
    (0.5, "0.5"),
    (0.123456789, "0.12345679"),
    (1.234e-05, "0.00001234"),
    (0, "0"),
])
def test_format_amount(value, expected):
    assert cp.format_amount(value) == expected


def test_format_price_without_symbol():
    assert cp.format_price(2.5, "uah") == "2.50 UAH"


def test_shared_session_is_reused_and_closed():
    async def run():
        session = http.get_http()
        assert http.get_http() is session
        await http.close_http()
        assert session.closed
        await http.close_http()  # повторное закрытие не падает

    asyncio.run(run())
