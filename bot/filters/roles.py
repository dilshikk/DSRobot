"""aiogram-фильтры для проверки роли отправителя. Roles hierarchy + custom roles."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.services.roles import get_command_min_roles
from bot.utils.permissions import can_run_command, command_name


class HasRole(BaseFilter):
    """
    Использование: @router.message(HasRole("admin")) — пропускает admin/owner/developer.

    issue #11: учитывает редактор прав (/setcmdperm) и права custom-ролей (/setrole).
    chat_user_role и chat_user_permissions прокидывает ChatContextMiddleware.
    """

    def __init__(self, minimum: str = "admin") -> None:
        self.minimum = minimum

    async def __call__(
        self,
        event: TelegramObject,
        chat_user_role: str = "member",
        chat_user_permissions: frozenset[str] = frozenset(),
        **kwargs: object,
    ) -> bool:
        command = command_name(getattr(event, "text", None))
        chat = getattr(event, "chat", None)
        override = None
        if command and chat is not None and chat.type != "private":
            override = (await get_command_min_roles(chat.id)).get(command)
        return can_run_command(
            chat_user_role, self.minimum,
            command=command, custom_permissions=chat_user_permissions, override=override,
        )
