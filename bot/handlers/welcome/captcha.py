"""
Captcha (1 mode: math).
Поток: новый участник -> restrict (нельзя писать) -> бот присылает пример -> участник
отвечает -> unrestrict. Если не ответил за timeout_sec -> кик (настраивается kick_on_fail).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message

from bot.filters.roles import HasRole
from bot.services.cache import get_json, redis, set_json
from bot.services.moderation_actions import apply_sanction
from bot.services.scheduler import schedule_once
from bot.services.settings_service import update_settings
from bot.database import SessionFactory

router = Router(name="captcha")

_bot_ref: Bot | None = None
RESTRICTED = ChatPermissions(can_send_messages=False)
UNRESTRICTED = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
)


def bind_bot(bot: Bot) -> None:
    """Вызывается один раз при старте (main.py), чтобы отложенный kick-джоб знал, каким Bot пользоваться."""
    global _bot_ref
    _bot_ref = bot


@router.message(Command("captcha"), HasRole("admin"))
async def toggle_captcha(message: Message, chat_settings: dict) -> None:
    new_state = chat_settings.get("captcha", {}).get("mode") != "off"
    async with SessionFactory() as session:
        await update_settings(session, message.chat.id, "captcha", {"mode": "off" if new_state else "math"})
    await message.answer(f"Captcha: {'выключена' if new_state else 'включена (math)'}")


@router.message(F.new_chat_members)
async def start_captcha(message: Message, chat_settings: dict) -> None:
    cfg = chat_settings.get("captcha", {})
    if cfg.get("mode", "math") == "off":
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue
        try:
            await message.bot.restrict_chat_member(message.chat.id, member.id, RESTRICTED)
        except Exception:
            continue  # бот без прав ограничения — пропускаем капчу

        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
        key = f"captcha:{message.chat.id}:{member.id}"
        await set_json(key, {"answer": answer}, ex=cfg.get("timeout_sec", 120))

        sent = await message.answer(
            f"\U0001f510 {member.mention_html()}, решите пример, чтобы получить доступ: <b>{a} + {b} = ?</b>",
            parse_mode="HTML",
        )
        await redis.set(f"captchamsg:{message.chat.id}:{member.id}", sent.message_id, ex=cfg.get("timeout_sec", 120))

        if cfg.get("kick_on_fail", True):
            run_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.get("timeout_sec", 120))
            schedule_once(
                _captcha_timeout, run_at=run_at,
                chat_id=message.chat.id, user_id=member.id,
                job_id=f"captcha_timeout:{message.chat.id}:{member.id}",
            )


@router.message(F.text.regexp(r"^\d+$"))
async def check_captcha_answer(message: Message, chat_settings: dict) -> None:
    key = f"captcha:{message.chat.id}:{message.from_user.id}"
    data = await get_json(key)
    if data is None:
        return

    if int(message.text) == data["answer"]:
        await message.bot.restrict_chat_member(message.chat.id, message.from_user.id, UNRESTRICTED)
        await redis.delete(key)
        await message.answer("\u2705 Проверка пройдена, добро пожаловать!")
        try:
            await message.delete()
        except Exception:
            pass
    # неверный ответ — молча ждём следующей попытки либо истечения timeout


async def _captcha_timeout(chat_id: int, user_id: int) -> None:
    if _bot_ref is None:
        return
    key = f"captcha:{chat_id}:{user_id}"
    data = await get_json(key)
    if data is None:
        return  # уже прошёл капчу
    await redis.delete(key)
    await apply_sanction(_bot_ref, chat_id, user_id, "kick", "Капча не пройдена вовремя", 0)
