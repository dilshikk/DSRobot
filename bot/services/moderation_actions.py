"""
Единая точка применения санкций (ban/mute/kick/warn/unmute/unban), используется
и командами модерации, и авто-модулями (antiflood, antispam, banned_words, anti_nsfw).
Пишет в AuditLog и, если настроен log_channel, шлёт туда уведомление —
Log channel feature.

issue #9:
- пользовательский ввод (reason) экранируется перед отправкой в HTML-лог;
- ошибки Telegram больше не глушатся молча: они логируются, а apply_sanction
  возвращает понятный текст ошибки, чтобы команда могла сообщить админу;
- если Telegram отклонил действие, в AuditLog ничего не пишется (санкции не было).

issue #12: текст ошибки возвращается на языке чата (аргумент lang).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ChatPermissions

from bot.database import SessionFactory
from bot.database.models import AuditLog, Chat
from bot.services.user_service import ensure_chat_user, upsert_user
from bot.utils.i18n import t

logger = logging.getLogger(__name__)

MUTED_PERMISSIONS = ChatPermissions(can_send_messages=False)
# Запасной вариант, если права чата по умолчанию получить не удалось. Раньше здесь не было
# голосовых, кружков, опросов и превью ссылок, и после /unmute они оставались запрещены (issue #38).
UNMUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True,
)


async def chat_default_permissions(bot: Bot, chat_id: int) -> ChatPermissions:
    """Права обычного участника этого чата: снятие ограничений не даёт больше, чем всем остальным."""
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError as exc:
        logger.warning("Cannot get default permissions of chat %s: %s", chat_id, exc)
        return UNMUTED_PERMISSIONS
    return chat.permissions or UNMUTED_PERMISSIONS

# Telegram ограничивает сообщение 4096 символами — не даём длинной причине сломать лог.
MAX_REASON_LENGTH = 1000
DEFAULT_MUTE_MINUTES = 60
MAX_MUTE_MINUTES = 525600


def parse_auto_action(args: str | None, actions: tuple[str, ...]) -> dict | None:
    """"mute 30" -> {"action": "mute", "mute_minutes": 30}; минуты допустимы только у mute."""
    parts = (args or "").lower().split()
    action = parts[0] if parts else ""
    minutes = parts[1] if len(parts) > 1 else str(DEFAULT_MUTE_MINUTES)
    if (
        action not in actions or len(parts) > 2 or (len(parts) == 2 and action != "mute")
        or not minutes.isdigit() or not 1 <= int(minutes) <= MAX_MUTE_MINUTES
    ):
        return None
    values: dict = {"action": action}
    if action == "mute":
        values["mute_minutes"] = int(minutes)
    return values

# Оставлено для обратной совместимости импортов.
NO_RIGHTS_ERROR = t("ru", "sanction_no_rights")


def _describe_bad_request(exc: TelegramBadRequest, lang: str) -> str:
    text = exc.message.lower()
    if "not enough rights" in text or "have no rights" in text:
        return t(lang, "sanction_no_rights")
    if "administrator" in text or "chat owner" in text:
        return t(lang, "sanction_admin")
    if "user not found" in text or "participant_id_invalid" in text:
        return t(lang, "sanction_user_not_found")
    return t(lang, "sanction_rejected", error=escape(exc.message))


async def _call_telegram(
    bot: Bot, chat_id: int, user_id: int, action: str, until: datetime | None, lang: str,
) -> str | None:
    """Выполняет действие в Telegram. Возвращает текст ошибки или None при успехе."""
    try:
        if action == "ban":
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        elif action == "mute":
            await bot.restrict_chat_member(chat_id, user_id, MUTED_PERMISSIONS, until_date=until)
        elif action == "unmute":
            await bot.restrict_chat_member(chat_id, user_id, await chat_default_permissions(bot, chat_id))
        elif action == "unban":
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        # action == "warn" не требует вызова Telegram API — только счётчик в БД
    except TelegramForbiddenError as exc:
        logger.warning("Sanction %s for user %s in chat %s forbidden: %s", action, user_id, chat_id, exc)
        return t(lang, "sanction_forbidden")
    except TelegramBadRequest as exc:
        logger.warning("Sanction %s for user %s in chat %s rejected: %s", action, user_id, chat_id, exc)
        return _describe_bad_request(exc, lang)
    except TelegramAPIError as exc:
        logger.error("Sanction %s for user %s in chat %s failed: %s", action, user_id, chat_id, exc)
        return t(lang, "sanction_failed")
    return None


async def apply_sanction(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action: str,
    reason: str = "",
    actor_user_id: int = 0,
    duration_minutes: int | None = None,
    lang: str = "ru",
) -> str | None:
    """Применяет санкцию. Возвращает текст ошибки для админа или None при успехе."""
    until = None
    if duration_minutes:
        until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

    error = await _call_telegram(bot, chat_id, user_id, action, until, lang)
    if error:
        return error

    reason = (reason or "")[:MAX_REASON_LENGTH]

    async with SessionFactory() as session:
        session.add(AuditLog(chat_id=chat_id, target_user_id=user_id, actor_user_id=actor_user_id,
                              action=action, reason=reason))

        # Цель санкции могла ни разу не писать в чат (санкция по id / reply на старое
        # сообщение) — гарантируем наличие User (FK) и ChatUser с warns=0 (issue #4).
        await upsert_user(session, user_id)
        cu = await ensure_chat_user(session, chat_id, user_id)

        if action == "warn":
            cu.warns = (cu.warns or 0) + 1
        elif action == "mute":
            cu.muted_until = until
        elif action == "ban":
            cu.banned_until = until
        elif action in ("unmute", "unban"):
            cu.muted_until = None
            cu.banned_until = None

        await session.commit()

        chat = await session.get(Chat, chat_id)

    if chat and chat.log_channel_id:
        await _send_to_log_channel(bot, chat.log_channel_id, chat_id, user_id, action, reason, actor_user_id)
    return None


async def _send_to_log_channel(
    bot: Bot, log_channel_id: int, chat_id: int, user_id: int, action: str, reason: str, actor_user_id: int,
) -> None:
    # Всё, что может прийти от пользователя, экранируется: иначе "<" или "&" в причине
    # ломают HTML-разметку, и Telegram отвечает "can't parse entities".
    text = (
        f"\U0001f6e1 <b>{escape(action.upper())}</b>\n"
        f"Chat: <code>{chat_id}</code>\nUser: <code>{user_id}</code>\n"
        f"By: <code>{actor_user_id or 'auto'}</code>\n"
        f"Reason: {escape(reason) if reason else '—'}"
    )
    try:
        await bot.send_message(log_channel_id, text, parse_mode="HTML")
    except TelegramAPIError as exc:
        logger.warning("Failed to write %s for chat %s to log channel %s: %s",
                       action, chat_id, log_channel_id, exc)
