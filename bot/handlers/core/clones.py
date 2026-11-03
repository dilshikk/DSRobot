"""
Клоны бота (issue #6).

/addclone <token>  — зарегистрировать своего бота как клон (только в личке);
/myclones          — список своих клонов;
/delclone <id|@username> — удалить клон.

Безопасность:
- токен в БД хранится только зашифрованным (bot/services/clone_crypto.py);
- сообщение с токеном сразу удаляется из чата, в том числе если токен по ошибке
  отправили в группу;
- создавать клоны могут только пользователи из CLONE_ALLOWED_USER_IDS, не больше
  MAX_CLONES_PER_USER на человека;
- токен проверяется через getMe до сохранения.

Клоны запускаются в том же процессе при старте (bot/services/clone_runner.py).
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

router = Router(name="clones")
logger = logging.getLogger(__name__)

RESTART_NOTE = "Изменение вступит в силу после перезапуска основного бота."


async def _delete_token_message(message: Message) -> bool:
    try:
        await message.delete()
        return True
    except TelegramAPIError:
        logger.warning("Не удалось удалить сообщение с токеном клона в чате %s", message.chat.id)
        return False


@router.message(Command("addclone"))
async def add_clone(message: Message, command: CommandObject) -> None:
    token = (command.args or "").strip()

    # Токен никогда не должен оставаться в истории чата.
    deleted = await _delete_token_message(message) if token else True

    if message.chat.type != "private" or message.from_user is None:
        # В группе не отвечаем, чтобы не светить команду. Токен уже удалён выше.
        return

    warn = "" if deleted else "\n\n\u26a0\ufe0f Удалите сообщение с токеном вручную."
    user_id = message.from_user.id

    if not clone_crypto.is_configured():
        await message.answer("Клоны отключены: администратор бота не задал ключ шифрования." + warn)
        return
    if user_id not in settings.clone_allowed_ids:
        await message.answer("Создание клонов недоступно для вашего аккаунта." + warn)
        return
    if not token:
        await message.answer("Использование: /addclone &lt;токен от @BotFather&gt;")
        return
    if token == settings.bot_token:
        await message.answer("Это токен основного бота." + warn)
        return

    token_hash = clone_crypto.token_fingerprint(token)
    async with SessionFactory() as session:
        active_count = await session.scalar(
            select(func.count()).select_from(BotClone)
            .where(BotClone.owner_user_id == user_id, BotClone.is_active.is_(True))
        )
        if (active_count or 0) >= settings.max_clones_per_user:
            await message.answer(f"Достигнут лимит клонов: {settings.max_clones_per_user}." + warn)
            return
        if await session.scalar(select(BotClone.id).where(BotClone.token_hash == token_hash)):
            await message.answer("Этот бот уже зарегистрирован как клон." + warn)
            return

    try:
        me = await fetch_bot_identity(token)
    except Exception:
        logger.exception("Не удалось проверить токен клона")
        await message.answer("Telegram сейчас недоступен, попробуйте позже." + warn)
        return
    if me is None:
        await message.answer("Токен недействителен. Проверьте его в @BotFather." + warn)
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
            await message.answer("Этот бот уже зарегистрирован как клон." + warn)
            return

    await message.answer(f"\u2705 Клон @{me.username} сохранён. {RESTART_NOTE}" + warn)


@router.message(Command("myclones"))
async def list_clones(message: Message) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    async with SessionFactory() as session:
        rows = (await session.execute(
            select(BotClone).where(BotClone.owner_user_id == message.from_user.id).order_by(BotClone.id)
        )).scalars().all()
    if not rows:
        await message.answer("У вас нет клонов.")
        return
    lines = [
        f"#{c.id} @{c.bot_username or '???'} — {'активен' if c.is_active else 'выключен'}"
        for c in rows
    ]
    await message.answer("\n".join(lines) + "\n\nУдалить: /delclone &lt;номер или @username&gt;")


@router.message(Command("delclone"))
async def delete_clone(message: Message, command: CommandObject) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    arg = (command.args or "").strip().lstrip("#@")
    if not arg:
        await message.answer("Использование: /delclone &lt;номер или @username&gt; (см. /myclones)")
        return

    condition = BotClone.id == int(arg) if arg.isdigit() else func.lower(BotClone.bot_username) == arg.lower()
    async with SessionFactory() as session:
        row = (await session.execute(
            select(BotClone).where(BotClone.owner_user_id == message.from_user.id, condition)
        )).scalar_one_or_none()
        if row is None:
            await message.answer("Клон не найден среди ваших.")
            return
        username = row.bot_username
        await session.delete(row)
        await session.commit()

    await message.answer(
        f"Клон @{username or '???'} удалён, токен стёрт из базы. {RESTART_NOTE}\n"
        "Рекомендуем также перевыпустить токен в @BotFather (/revoke)."
    )
