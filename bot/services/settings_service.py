"""
CRUD для ChatSettings с мёрджем DEFAULTS и кэшированием в Redis
(чтобы не ходить в PostgreSQL при каждом сообщении — см. архитектуру Middleware Layer).
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Chat, ChatSettings
from bot.services.cache import get_json, set_json

CACHE_TTL = 300  # секунд


def _merge_defaults(data: dict) -> dict:
    merged = copy.deepcopy(ChatSettings.DEFAULTS)
    for section, values in data.items():
        merged.setdefault(section, {})
        if isinstance(values, dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


async def get_settings(session: AsyncSession, chat_id: int) -> dict:
    cached = await get_json(f"chat_settings:{chat_id}")
    if cached is not None:
        return cached

    row = await session.get(ChatSettings, chat_id)
    data = _merge_defaults(row.data if row else {})
    await set_json(f"chat_settings:{chat_id}", data, ex=CACHE_TTL)
    return data


async def update_settings(session: AsyncSession, chat_id: int, section: str, values: dict[str, Any]) -> dict:
    row = await session.get(ChatSettings, chat_id)
    if row is None:
        row = ChatSettings(chat_id=chat_id, data={})
        session.add(row)
    row.data.setdefault(section, {})
    row.data[section] = {**row.data[section], **values}
    await session.commit()

    merged = _merge_defaults(row.data)
    await set_json(f"chat_settings:{chat_id}", merged, ex=CACHE_TTL)
    return merged


async def get_or_create_chat(session: AsyncSession, chat_id: int, title: str = "", type_: str = "group") -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(id=chat_id, title=title, type=type_)
        session.add(chat)
        session.add(ChatSettings(chat_id=chat_id, data={}))
        await session.commit()
    return chat
