"""issue #35: текст с «<» / «&» не должен ломать отправку при parse_mode=HTML по умолчанию."""
import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, SendMessage

from bot.handlers.welcome.goodbye import goodbye_text
from bot.handlers.welcome.welcome import welcome_text
from bot.services.clone_runner import create_bot
from bot.utils.html_fallback import HtmlFallbackMiddleware, send_html_or_escaped

PARSE_ERROR = "Bad Request: can't parse entities: Unsupported start tag \"forwards|links\" at byte offset 20"


def _bad_request(method, text=PARSE_ERROR) -> TelegramBadRequest:
    return TelegramBadRequest(method=method, message=text)


class FakeRequests:
    """make_request, который падает на первой попытке."""

    def __init__(self, error: str | None = PARSE_ERROR):
        self.error = error
        self.calls = []

    async def __call__(self, bot, method):
        self.calls.append(method)
        if len(self.calls) == 1 and self.error:
            raise _bad_request(method, self.error)
        return "ok"


def _run(requests, method):
    return asyncio.run(HtmlFallbackMiddleware()(requests, None, method))


def test_default_html_parse_error_retries_without_parse_mode():
    requests = FakeRequests()
    method = SendMessage(chat_id=-100, text="Использование: /block <forwards|links>")

    assert _run(requests, method) == "ok"
    assert len(requests.calls) == 2
    assert requests.calls[1].parse_mode is None
    assert requests.calls[1].text == method.text


def test_explicit_html_is_not_retried():
    requests = FakeRequests()
    with pytest.raises(TelegramBadRequest):
        _run(requests, SendMessage(chat_id=-100, text="<b>x", parse_mode="HTML"))
    assert len(requests.calls) == 1


def test_other_bad_requests_are_not_retried():
    requests = FakeRequests(error="Bad Request: chat not found")
    with pytest.raises(TelegramBadRequest):
        _run(requests, SendMessage(chat_id=-100, text="hi"))
    assert len(requests.calls) == 1


def test_create_bot_registers_fallback():
    bot = create_bot("123456:TEST")
    assert any(isinstance(m, HtmlFallbackMiddleware) for m in bot.session.middleware[:])


class FakeBot:
    def __init__(self, fail_first: bool):
        self.fail_first = fail_first
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        if self.fail_first and len(self.sent) == 1:
            raise _bad_request(DeleteMessage(chat_id=chat_id, message_id=1))
        return text


MENTION = '<a href="tg://user?id=1">Bob</a>'


def test_custom_welcome_with_broken_html_is_sent_escaped():
    cfg = {"text": "Привет, {mention}! Возраст <18 & старше"}
    bot = FakeBot(fail_first=True)

    asyncio.run(send_html_or_escaped(bot, -100, lambda esc: welcome_text(cfg, "ru", MENTION, esc)))

    assert bot.sent[-1] == f"Привет, {MENTION}! Возраст &lt;18 &amp; старше"


def test_custom_welcome_with_valid_html_is_kept():
    cfg = {"text": "<b>Привет</b>, {mention}!"}
    bot = FakeBot(fail_first=False)

    asyncio.run(send_html_or_escaped(bot, -100, lambda esc: welcome_text(cfg, "ru", MENTION, esc)))

    assert bot.sent == [f"<b>Привет</b>, {MENTION}!"]


def test_goodbye_escape_keeps_mention():
    assert goodbye_text({"text": "Пока, {mention} <3"}, "ru", MENTION, True) == f"Пока, {MENTION} &lt;3"
