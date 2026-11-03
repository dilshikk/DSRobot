"""aiogram-фильтры для проверки роли отправителя. Roles hierarchy + custom roles."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot.utils.permissions import role_at_least


class HasRole(BaseFilter):
    """Использование: @router.message(HasRole("admin")) — пропускает admin/owner/developer."""

    def __init__(self, minimum: str = "admin") -> None:
        self.minimum = minimum

    async def __call__(self, message: Message, chat_user_role: str = "member", **kwargs) -> bool:
        # chat_user_role прокидывается ChatContextMiddleware
        return role_at_least(chat_user_role, self.minimum)
