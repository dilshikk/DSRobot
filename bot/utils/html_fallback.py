"""
Защита от "can't parse entities" при parse_mode=HTML по умолчанию (issue #35).

Бот создаётся с DefaultBotProperties(parse_mode=HTML), поэтому любой текст с «<» или «&»
(подсказка «/cmd <arg>», правила «Возраст <18», заметка, рассылка) Telegram отклонял.

- HtmlFallbackMiddleware: если HTML по умолчанию не разобрался, запрос повторяется без
  parse_mode, и текст уходит как есть. Явный parse_mode="HTML" не трогаем: такой код сам
  отвечает за экранирование (иначе вместо упоминания пользователь увидел бы сырые теги).
- send_html_or_escaped: для текстов админа с HTML-упоминанием (приветствие, прощание).
"""
from __future__ import annotations

import logging
from typing import Callable

from aiogram import Bot
from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Message

logger = logging.getLogger(__name__)


def is_parse_error(exc: TelegramBadRequest) -> bool:
    return "can't parse entities" in exc.message.lower()


class HtmlFallbackMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            if not is_parse_error(exc) or not isinstance(getattr(method, "parse_mode", None), Default):
                raise
            logger.warning("HTML не разобран в %s, отправляю без разметки: %s", type(method).__name__, exc.message)
            return await make_request(bot, method.model_copy(update={"parse_mode": None}))


async def send_html_or_escaped(bot: Bot, chat_id: int, build: Callable[[bool], str]) -> Message:
    """build(escape) -> HTML-текст. Сначала как есть, при ошибке разметки — с экранированием."""
    try:
        return await bot.send_message(chat_id, build(False), parse_mode="HTML")
    except TelegramBadRequest as exc:
        if not is_parse_error(exc):
            raise
        logger.warning("Некорректный HTML в тексте чата %s, отправляю экранированным: %s", chat_id, exc.message)
        return await bot.send_message(chat_id, build(True), parse_mode="HTML")
