"""
Antispam: эвристики против дубликатов сообщений (одно и то же сообщение подряд N раз).
База CAS и правила для новичков — в spam_guard.py (issue #14).
Проверка вызывается из bot/middlewares/moderation_pipeline.py. Ответы — на языке чата (issue #12).

issue #49:
- первое сообщение серии тоже считается: при пороге 3 мут на 3-м одинаковом сообщении, а не на 4-м;
- при муте удаляются все копии серии, включая ту, за которую выдан мут;
- порог и длительность мута настраиваются командой /setantispam;
- счётчик создаётся атомарно с TTL (см. cache.incr_with_ttl).
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services.cache import get_json, incr_with_ttl, redis, set_json
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import MAX_MUTE_MINUTES, apply_sanction
from bot.services.settings_service import update_settings
from bot.utils.i18n import t, toggle_text
from bot.utils.parsing import bounded_int
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_by_id_safely, message_text

router = Router(name="antispam")

DEFAULT_THRESHOLD = 3
DEFAULT_MUTE_MINUTES = 30
MIN_THRESHOLD = 2
MAX_THRESHOLD = 20
# Сколько секунд помним предыдущее сообщение и счётчик повторов.
DUPLICATE_WINDOW_SEC = 30


def antispam_limits(cfg: dict) -> tuple[int, int]:
    """(порог повторов, минуты мута) из настроек чата с безопасными значениями по умолчанию."""
    threshold = bounded_int(cfg.get("duplicate_threshold"), DEFAULT_THRESHOLD, MIN_THRESHOLD, MAX_THRESHOLD)
    minutes = bounded_int(cfg.get("mute_minutes"), DEFAULT_MUTE_MINUTES, 1, MAX_MUTE_MINUTES)
    return threshold, minutes


def parse_antispam_args(args: str | None) -> tuple[int, int] | None:
    """"5" -> (5, 30); "5 60" -> (5, 60). Неверный ввод -> None."""
    parts = (args or "").split()
    if not 1 <= len(parts) <= 2 or not all(p.isdigit() for p in parts):
        return None
    threshold = int(parts[0])
    minutes = int(parts[1]) if len(parts) == 2 else DEFAULT_MUTE_MINUTES
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD or not 1 <= minutes <= MAX_MUTE_MINUTES:
        return None
    return threshold, minutes


async def check_duplicate_spam(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("antispam", {})
    text = message_text(message)
    if not text or not cfg.get("enabled") or is_privileged(chat_user_role) or message.from_user is None:
        return False

    chat_id = message.chat.id
    base = f"{chat_id}:{message.from_user.id}"
    last_key, count_key, ids_key = f"lastmsg:{base}", f"dupcount:{base}", f"dupids:{base}"

    prev = await redis.get(last_key)
    await redis.set(last_key, text, ex=DUPLICATE_WINDOW_SEC)
    if prev != text:
        # Новая серия: счётчик начинается с этого сообщения (его номер — 1).
        await redis.delete(count_key, ids_key)

    threshold, mute_minutes = antispam_limits(cfg)
    count = await incr_with_ttl(count_key, DUPLICATE_WINDOW_SEC)
    ids = [*(await get_json(ids_key) or []), message.message_id][-threshold:]
    if count < threshold:
        await set_json(ids_key, ids, ex=DUPLICATE_WINDOW_SEC)
        return False

    await redis.delete(count_key, ids_key, last_key)
    for message_id in ids:
        # О нехватке прав предупреждаем один раз — по текущему сообщению.
        await delete_by_id_safely(message.bot, chat_id, message_id, notify=message_id == message.message_id)

    # Проверки из moderation_pipeline не получают handler data, язык берём из кэша.
    lang = await get_chat_lang(chat_id)
    await apply_sanction(message.bot, chat_id, message.from_user.id, "mute",
                         t(lang, "antispam_reason"), 0, duration_minutes=mute_minutes, lang=lang)
    return True


@router.message(Command("antispam"), HasRole("admin"))
async def toggle_antispam(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("antispam", {}).get("enabled", True)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {"enabled": new_state})
    await message.answer(toggle_text(lang, "feature_antispam", new_state))


@router.message(Command("setantispam"), HasRole("admin"))
async def set_antispam(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """/setantispam ПОВТОРОВ [МИНУТ_МУТА]"""
    parsed = parse_antispam_args(command.args)
    if parsed is None:
        await message.answer(t(lang, "antispam_usage", min=MIN_THRESHOLD, max=MAX_THRESHOLD,
                               max_minutes=MAX_MUTE_MINUTES))
        return
    threshold, minutes = parsed
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "antispam", {
            "enabled": True, "duplicate_threshold": threshold, "mute_minutes": minutes,
        })
    await message.answer(t(lang, "antispam_set", threshold=threshold, minutes=minutes))
