"""
Клоны бота (issue #6).

/addclone ТОКЕН  — зарегистрировать своего бота как клон (только в личке);
/myclones          — список своих клонов;
/delclone НОМЕР|@username — удалить клон.

Безопасность:
- токен в БД хранится только зашифрованным (bot/services/clone_crypto.py);
- сообщение с токеном сразу удаляется из чата, в том числе если токен по ошибке
  отправили в группу;
- создавать клоны могут только пользователи из CLONE_ALLOWED_USER_IDS, не больше
  MAX_CLONES_PER_USER на человека;
- токен проверяется через getMe до сохранения.

Клоны запускаются в том же процессе при старте (bot/services/clone_runner.py).
Команды работают только в личке, поэтому ответы — на языке Telegram-клиента пользователя (issue #12).
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from bot.config import settings
from bot.database import SessionFactory
from bot.database.models import BotClone
from bot.services import clone_crypto
from bot.services.clone_runner import fetch_bot_identity
from bot.utils.i18n import t

router = Router(name="clones")
logger = logging.getLogger(__name__)


async def _delete_token_message(message: Message) -> bool:
    try:
        await message.delete()
        return True
    except TelegramAPIError:
        logger.warning("Не удалось удалить сообщение с токеном клона в чате %s", message.chat.id)
        return False


def with_token_warning(lang: str, text: str, deleted: bool) -> str:
    """Если сообщение с токеном удалить не удалось, к любому ответу добавляем предупреждение."""
    return text if deleted else f"{text}\n\n{t(lang, 'clone_delete_token_manually')}"


def clones_list_text(lang: str, clones: list[BotClone]) -> str:
    if not clones:
        return t(lang, "clones_empty")
    lines = [
        t(lang, "clone_line", id=c.id, username=c.bot_username or "???",
          state=t(lang, "clone_active" if c.is_active else "clone_inactive"))
        for c in clones
    ]
    return "\n".join(lines) + "\n\n" + t(lang, "clones_delete_hint")


@router.message(Command("addclone"))
async def add_clone(message: Message, command: CommandObject, lang: str = "ru") -> None:
    token = (command.args or "").strip()

    # Токен никогда не должен оставаться в истории чата.
    deleted = await _delete_token_message(message) if token else True

    if message.chat.type != "private" or message.from_user is None:
        # В группе не отвечаем, чтобы не светить команду. Токен уже удалён выше.
        return

    async def reply(key: str, **kwargs: object) -> None:
        await message.answer(with_token_warning(lang, t(lang, key, **kwargs), deleted))

    user_id = message.from_user.id

    if not clone_crypto.is_configured():
        await reply("clone_disabled")
        return
    if user_id not in settings.clone_allowed_ids:
        await reply("clone_not_allowed")
        return
    if not token:
        await message.answer(t(lang, "addclone_usage"))
        return
    if token == settings.bot_token:
        await reply("clone_main_token")
        return

    token_hash = clone_crypto.token_fingerprint(token)
    async with SessionFactory() as session:
        active_count = await session.scalar(
            select(func.count()).select_from(BotClone)
            .where(BotClone.owner_user_id == user_id, BotClone.is_active.is_(True))
        )
        if (active_count or 0) >= settings.max_clones_per_user:
            await reply("clone_limit", limit=settings.max_clones_per_user)
            return
        if await session.scalar(select(BotClone.id).where(BotClone.token_hash == token_hash)):
            await reply("clone_exists")
            return

    try:
        me = await fetch_bot_identity(token)
    except Exception:
        logger.exception("Не удалось проверить токен клона")
        await reply("clone_telegram_unavailable")
        return
    if me is None:
        await reply("clone_invalid_token")
        return

    async with SessionFactory() as session:
        session.add(BotClone(
            owner_user_id=user_id,
            bot_id=me.id,
            bot_username=me.username or "",
            token_encrypted=clone_crypto.encrypt_token(token),
            token_hash=token_hash,
        ))
        try:
            await session.commit()
        except IntegrityError:
            # Гонка: тот же токен добавили параллельно.
            await session.rollback()
            await reply("clone_exists")
            return

    await reply("clone_saved", username=me.username or "???")


@router.message(Command("myclones"))
async def list_clones(message: Message, lang: str = "ru") -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    async with SessionFactory() as session:
        rows = (await session.execute(
            select(BotClone).where(BotClone.owner_user_id == message.from_user.id).order_by(BotClone.id)
        )).scalars().all()
    await message.answer(clones_list_text(lang, list(rows)))


@router.message(Command("delclone"))
async def delete_clone(message: Message, command: CommandObject, lang: str = "ru") -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    arg = (command.args or "").strip().lstrip("#@")
    if not arg:
        await message.answer(t(lang, "delclone_usage"))
        return

    condition = BotClone.id == int(arg) if arg.isdigit() else func.lower(BotClone.bot_username) == arg.lower()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(BotClone).where(BotClone.owner_user_id == message.from_user.id, condition)
        )).scalar_one_or_none()
        if row is None:
            await message.answer(t(lang, "clone_not_found"))
            return
        username = row.bot_username
        await session.delete(row)
        await session.commit()

    await message.answer(t(lang, "clone_deleted", username=username or "???"))
