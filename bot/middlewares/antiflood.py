"""
Anti-flood middleware: считает сообщения пользователя в окне (Redis INCR+EXPIRE)
и применяет действие (mute/kick/ban) при превышении порога из chat_settings.

issue #7:
- мут срочный: длительность берётся из antiflood.mute_minutes (по умолчанию 30 минут);
- санкция применяется ОДИН раз на серию: флаг antiflood_punished:{chat}:{user}
  ставится атомарно (SET NX), поэтому нет повторных вызовов Telegram API,
  дублей в AuditLog и спама в лог-канал;
- каждое сообщение сверх лимита удаляется (а не просто «застревает» в чате).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, TelegramObject

from bot.services.cache import incr_with_ttl, redis
from bot.services.moderation_actions import apply_sanction
from bot.utils.permissions import is_privileged

logger = logging.getLogger(__name__)

FLOOD_ACTIONS = ("mute", "kick", "ban")
DEFAULT_MAX_MESSAGES = 7
DEFAULT_PER_SECONDS = 8
DEFAULT_MUTE_MINUTES = 30
# Сколько секунд после наказания не наказываем повторно (сообщения, которые уже «в полёте»).
MIN_PUNISHED_TTL = 60


def _int_setting(cfg: dict, key: str, default: int) -> int:
    try:
        value = int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


async def _delete_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as exc:
        logger.warning("Anti-flood: cannot delete message %s in chat %s: %s",
                       message.message_id, message.chat.id, exc)


class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user or event.chat.type == "private":
            return await handler(event, data)

        cfg = (data.get("chat_settings") or {}).get("antiflood", {})
        role = data.get("chat_user_role", "member")
        if not cfg.get("enabled") or is_privileged(role) or data.get("is_anonymous_admin"):
            return await handler(event, data)

        chat_id, user_id = event.chat.id, event.from_user.id
        max_messages = _int_setting(cfg, "max_messages", DEFAULT_MAX_MESSAGES)
        per_seconds = _int_setting(cfg, "per_seconds", DEFAULT_PER_SECONDS)

        count = await incr_with_ttl(f"antiflood:{chat_id}:{user_id}", per_seconds)
        if count <= max_messages:
            return await handler(event, data)

        await _delete_quietly(event)

        # SET NX атомарен: даже при параллельной обработке апдейтов наказание будет одно.
        punished_key = f"antiflood_punished:{chat_id}:{user_id}"
        is_first = await redis.set(punished_key, 1, ex=max(per_seconds, MIN_PUNISHED_TTL), nx=True)
        if is_first:
            action = cfg.get("action", "mute")
            if action not in FLOOD_ACTIONS:
                action = "mute"
            duration = _int_setting(cfg, "mute_minutes", DEFAULT_MUTE_MINUTES) if action == "mute" else None
            try:
                await apply_sanction(
                    bot=data["bot"], chat_id=chat_id, user_id=user_id, action=action,
                    reason="Anti-flood: превышен лимит сообщений", actor_user_id=0,
                    duration_minutes=duration,
                )
            except Exception:
                logger.exception("Anti-flood sanction failed for user %s in chat %s", user_id, chat_id)

        return None  # флуд дальше в хендлеры не пропускаем
