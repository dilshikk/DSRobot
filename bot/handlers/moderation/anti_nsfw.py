"""
Anti-NSFW (issue #14): непристойные картинки удаляет локальная модель NudeNet
(bot/services/nsfw.py), без внешних сервисов и ключей.

Проверяются фото, статичные стикеры и картинки-файлы; у видео, GIF, кружков и
анимированных стикеров — превью. Проверка вызывается из moderation_pipeline.
Ответы — на языке чата (issue #12).

Настройки чата (раздел anti_nsfw):
- enabled — /antinsfw (по умолчанию выкл.);
- threshold — /nsfwlevel: с какой уверенности модели (в %) картинка считается непристойной;
- action — /nsfwaction: что делать с автором, кроме удаления сообщения.
Если модель недоступна или ошиблась с форматом, сообщение пропускается: сбой не блокирует чат.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.services import nsfw
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import (
    DEFAULT_MUTE_MINUTES, MAX_MUTE_MINUTES, apply_sanction, parse_auto_action,
)
from bot.services.settings_service import update_settings
from bot.utils.i18n import t, toggle_text
from bot.utils.parsing import bounded_int, parse_int
from bot.utils.permissions import is_privileged
from bot.utils.telegram import delete_message_safely

router = Router(name="anti_nsfw")

NSFW_ACTIONS = ("delete", "warn", "mute", "kick", "ban")
DEFAULT_THRESHOLD = 60
MIN_THRESHOLD = 30
MAX_THRESHOLD = 95
# GIF модель не читает: у таких файлов проверяется превью, если оно есть.
IMAGE_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")


def nsfw_threshold(cfg: dict) -> int:
    return bounded_int(cfg.get("threshold"), DEFAULT_THRESHOLD, MIN_THRESHOLD, MAX_THRESHOLD)


def nsfw_action(cfg: dict) -> str:
    action = cfg.get("action", "delete")
    return action if action in NSFW_ACTIONS else "delete"


def nsfw_media(message: Message) -> nsfw.Media | None:
    """Картинка, которую нужно проверить, или None."""
    if message.photo:
        return message.photo[-1]
    sticker = message.sticker
    if sticker is not None:
        return sticker.thumbnail if (sticker.is_animated or sticker.is_video) else sticker
    for media in (message.animation, message.video, message.video_note):
        if media is not None:
            return media.thumbnail
    document = message.document
    if document is not None:
        return document if document.mime_type in IMAGE_MIME_TYPES else document.thumbnail
    return None


def nsfw_toggle_text(lang: str, enabled: bool, available: bool) -> str:
    text = toggle_text(lang, "feature_anti_nsfw", enabled)
    return f"{text}\n{t(lang, 'nsfw_unavailable')}" if enabled and not available else text


async def check_nsfw(message: Message, chat_settings: dict, chat_user_role: str) -> bool:
    cfg = chat_settings.get("anti_nsfw", {})
    if not cfg.get("enabled") or is_privileged(chat_user_role) or message.from_user is None:
        return False
    media = nsfw_media(message)
    if media is None:
        return False
    score = await nsfw.media_score(message.bot, media)
    if score is None or score * 100 < nsfw_threshold(cfg):
        return False

    await delete_message_safely(message)
    action = nsfw_action(cfg)
    # Пост от имени канала: from_user — служебный бот Telegram, наказывать некого.
    if action != "delete" and message.sender_chat is None and not message.from_user.is_bot:
        lang = await get_chat_lang(message.chat.id)
        minutes = None
        if action == "mute":
            minutes = bounded_int(cfg.get("mute_minutes"), DEFAULT_MUTE_MINUTES, 1, MAX_MUTE_MINUTES)
        await apply_sanction(message.bot, message.chat.id, message.from_user.id, action,
                             t(lang, "nsfw_reason"), 0, minutes, lang=lang)
    return True


@router.message(Command("antinsfw"), HasRole("admin"))
async def toggle_nsfw(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    new_state = not chat_settings.get("anti_nsfw", {}).get("enabled", False)
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "anti_nsfw", {"enabled": new_state})
    await message.answer(nsfw_toggle_text(lang, new_state, nsfw.available()))


@router.message(Command("nsfwaction"), HasRole("admin"))
async def set_nsfw_action(message: Message, command: CommandObject, lang: str = "ru") -> None:
    """/nsfwaction delete | warn | kick | ban | mute [МИНУТ]"""
    values = parse_auto_action(command.args, NSFW_ACTIONS)
    if values is None:
        await message.answer(t(lang, "nsfw_action_usage"))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "anti_nsfw", values)
    await message.answer(t(lang, "nsfw_action_set", action=values["action"]))


@router.message(Command("nsfwlevel"), HasRole("admin"))
async def set_nsfw_level(message: Message, command: CommandObject, chat_settings: dict,
                         lang: str = "ru") -> None:
    """/nsfwlevel ПРОЦЕНТ — с какой уверенности модели удалять картинку."""
    level = parse_int(command.args, MIN_THRESHOLD, MAX_THRESHOLD)
    if level is None:
        current = nsfw_threshold(chat_settings.get("anti_nsfw", {}))
        await message.answer(t(lang, "nsfw_level_usage", min=MIN_THRESHOLD, max=MAX_THRESHOLD, level=current))
        return
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "anti_nsfw", {"threshold": level})
    await message.answer(t(lang, "nsfw_level_set", level=level))
