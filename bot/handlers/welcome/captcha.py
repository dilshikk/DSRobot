"""
Captcha (1 mode: math) на inline-кнопках.

Поток: новый участник -> restrict (нельзя писать) -> бот присылает пример с кнопками
вариантов ответа -> участник нажимает кнопку -> unrestrict + удаление сообщения капчи
+ приветствие. Если не ответил за timeout_sec или исчерпал попытки -> кик
(настраивается kick_on_fail).

Почему кнопки, а не текстовый ответ (issue #3): после restrict(can_send_messages=False)
участник физически не может отправить сообщение с ответом, поэтому текстовую капчу
пройти было невозможно. Нажатие inline-кнопки доступно и ограниченному участнику.

Таймаут (issue #10): задача хранится в Redis и переживает перезапуск, а в аргументах
хранит bot_id — кикает тот бот (основной или клон), который выдал капчу.

Все тексты — на языке чата (issue #12). Для кнопок язык прокидывает
CallbackContextMiddleware, для таймаута он читается из кэша (services/chat_lang.py).

Запуск капчи вызывается из welcome/service_events.py (issue #1).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from bot.database import SessionFactory
from bot.filters.roles import HasRole
from bot.handlers.welcome.welcome import greet_members
from bot.services.bot_registry import get_bot
from bot.services.cache import get_json, redis, set_json
from bot.services.chat_lang import get_chat_lang
from bot.services.moderation_actions import apply_sanction
from bot.services.scheduler import remove_job, schedule_once
from bot.services.settings_service import get_settings, update_settings
from bot.utils.i18n import t
from bot.utils.telegram import delete_by_id_safely, is_rights_error, notify_missing_rights

router = Router(name="captcha")
logger = logging.getLogger(__name__)

RESTRICTED = ChatPermissions(can_send_messages=False)
UNRESTRICTED = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
)
CALLBACK_PREFIX = "cap"
OPTIONS_COUNT = 4
MAX_ATTEMPTS = 3
# Состояние капчи живёт заметно дольше таймаута: если бот был выключен, задача таймаута
# выполнится после старта и должна ещё увидеть состояние. Иначе она решит, что капча
# пройдена, и участник останется ограниченным навсегда (issue #10).
STATE_GRACE_SEC = 3 * 24 * 3600


def _state_key(chat_id: int, user_id: int) -> str:
    return f"captcha:{chat_id}:{user_id}"


def _msg_key(chat_id: int, user_id: int) -> str:
    return f"captchamsg:{chat_id}:{user_id}"


def _job_id(chat_id: int, user_id: int) -> str:
    return f"captcha_timeout:{chat_id}:{user_id}"


def _build_options(answer: int) -> list[int]:
    options = {answer}
    while len(options) < OPTIONS_COUNT:
        candidate = answer + random.randint(-5, 5)
        if candidate > 0:
            options.add(candidate)
    shuffled = list(options)
    random.shuffle(shuffled)
    return shuffled


def _keyboard(user_id: int, options: list[int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(value), callback_data=f"{CALLBACK_PREFIX}:{user_id}:{value}")
        for value in options
    ]])


async def _cleanup(bot: Bot, chat_id: int, user_id: int) -> None:
    """Удаляет состояние капчи, её сообщение и отложенный таймаут."""
    msg_id = await redis.get(_msg_key(chat_id, user_id))
    await redis.delete(_state_key(chat_id, user_id), _msg_key(chat_id, user_id))
    if msg_id:
        await delete_by_id_safely(bot, chat_id, int(msg_id))
    remove_job(_job_id(chat_id, user_id))


@router.message(Command("captcha"), HasRole("admin"))
async def toggle_captcha(message: Message, chat_settings: dict, lang: str = "ru") -> None:
    was_enabled = chat_settings.get("captcha", {}).get("mode") != "off"
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "captcha", {"mode": "off" if was_enabled else "math"})
    await message.answer(t(lang, "captcha_disabled" if was_enabled else "captcha_enabled"))


async def start_captcha(
    bot: Bot, chat_id: int, chat_settings: dict, members: list[User], lang: str = "ru",
) -> list[int]:
    """Запускает капчу для участников. Возвращает id тех, кому капча реально выдана."""
    cfg = chat_settings.get("captcha", {})
    if cfg.get("mode", "math") == "off":
        return []
    timeout = int(cfg.get("timeout_sec", 120))
    started: list[int] = []

    for member in members:
        if member.is_bot:
            continue
        try:
            await bot.restrict_chat_member(chat_id, member.id, RESTRICTED)
        except TelegramBadRequest as exc:
            # Без прав ограничения капча бессмысленна: участник и так может писать.
            logger.warning("Captcha skipped for %s in chat %s: %s", member.id, chat_id, exc)
            if is_rights_error(exc):
                await notify_missing_rights(bot, chat_id, "rights_action_captcha", lang=lang)
            continue
        except TelegramAPIError as exc:
            logger.warning("Captcha skipped for %s in chat %s: %s", member.id, chat_id, exc)
            continue

        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
        ttl = timeout + STATE_GRACE_SEC
        await set_json(_state_key(chat_id, member.id), {"answer": answer, "attempts": 0}, ex=ttl)

        sent = await bot.send_message(
            chat_id,
            t(lang, "captcha_prompt", mention=member.mention_html(), question=f"{a} + {b} = ?", timeout=timeout),
            parse_mode="HTML",
            reply_markup=_keyboard(member.id, _build_options(answer)),
        )
        await redis.set(_msg_key(chat_id, member.id), sent.message_id, ex=ttl)

        run_at = datetime.now(timezone.utc) + timedelta(seconds=timeout)
        schedule_once(
            captcha_timeout, run_at=run_at,
            chat_id=chat_id, user_id=member.id,
            kick=bool(cfg.get("kick_on_fail", True)),
            bot_id=bot.id,
            job_id=_job_id(chat_id, member.id),
        )
        started.append(member.id)

    return started


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def check_captcha_answer(callback: CallbackQuery, lang: str = "ru") -> None:
    if callback.message is None or callback.data is None:
        return await callback.answer()

    try:
        _, target_id_raw, value_raw = callback.data.split(":")
        target_id, value = int(target_id_raw), int(value_raw)
    except ValueError:
        return await callback.answer()

    # Кнопки капчи может нажимать только тот, для кого она создана.
    if callback.from_user.id != target_id:
        return await callback.answer(t(lang, "captcha_not_for_you"), show_alert=True)

    chat_id = callback.message.chat.id
    key = _state_key(chat_id, target_id)
    state = await get_json(key)
    if state is None:
        return await callback.answer(t(lang, "captcha_expired"), show_alert=True)

    bot = callback.bot
    if value == state["answer"]:
        try:
            await bot.restrict_chat_member(chat_id, target_id, UNRESTRICTED)
        except TelegramAPIError as exc:
            logger.warning("Cannot lift captcha restriction for %s in chat %s: %s", target_id, chat_id, exc)
            return await callback.answer(t(lang, "captcha_unrestrict_failed"), show_alert=True)
        await _cleanup(bot, chat_id, target_id)
        await callback.answer(t(lang, "captcha_passed"))
        # Приветствие откладывалось до прохождения капчи (см. service_events.py).
        async with SessionFactory() as session:
            chat_settings = await get_settings(session, chat_id)
        try:
            await greet_members(bot, chat_id, chat_settings, [callback.from_user], lang=lang)
        except Exception:
            # Ошибка приветствия не должна отменять успешное прохождение капчи.
            logger.exception("Welcome after captcha failed for %s in chat %s", target_id, chat_id)
        return

    attempts = int(state.get("attempts", 0)) + 1
    if attempts >= MAX_ATTEMPTS:
        await _cleanup(bot, chat_id, target_id)
        await callback.answer(t(lang, "captcha_no_attempts"), show_alert=True)
        await apply_sanction(bot, chat_id, target_id, "kick", t(lang, "captcha_failed_reason"), 0, lang=lang)
        return

    ttl = await redis.ttl(key)
    await set_json(key, {**state, "attempts": attempts}, ex=ttl if ttl and ttl > 0 else 60)
    await callback.answer(t(lang, "captcha_wrong", left=MAX_ATTEMPTS - attempts), show_alert=True)


async def captcha_timeout(chat_id: int, user_id: int, kick: bool = True, bot_id: int | None = None) -> None:
    """Функция задачи. Хранится в Redis по ссылке "модуль:имя" — не переименовывайте."""
    bot = get_bot(bot_id)
    if bot is None:
        logger.warning("Таймаут капчи в чате %s: бот %s не запущен, пропускаю", chat_id, bot_id)
        return
    state = await get_json(_state_key(chat_id, user_id))
    if state is None:
        return  # уже прошёл капчу
    await _cleanup(bot, chat_id, user_id)
    if kick:
        lang = await get_chat_lang(chat_id)
        await apply_sanction(bot, chat_id, user_id, "kick", t(lang, "captcha_timeout_reason"), 0, lang=lang)
