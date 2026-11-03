"""
ORM-модели.

Дизайн-решение: вместо ~40 отдельных таблиц под каждый чекбокс-фичу
(anti-flood, night-mode, max-message-length, link-settings и т.д.) используется
одна таблица `chat_settings` с колонкой JSONB `data`. Это резко упрощает
добавление новых toggle-настроек (не нужна миграция под каждую фичу) и
соответствует тому, как устроены реальные боты такого класса (Rose, Combot).

Структурные данные, которые не являются простыми toggle-флагами
(варны, роли, забаненные слова, рассылки и т.п.), хранятся в отдельных таблицах.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Базовые сущности
# --------------------------------------------------------------------------- #

class Chat(Base):
    """Группа или канал, где работает бот."""
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram chat_id
    title: Mapped[str] = mapped_column(String(255), default="")
    type: Mapped[str] = mapped_column(String(32), default="group")  # group/supergroup/channel
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    utc_offset: Mapped[int] = mapped_column(Integer, default=0)  # UTC time settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    discussion_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    staff_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    settings: Mapped["ChatSettings"] = relationship(back_populates="chat", uselist=False, cascade="all, delete-orphan")


class ChatSettings(Base):
    """Единый JSON-блоб под все toggle/числовые настройки чата (см. docstring модуля)."""
    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    chat: Mapped["Chat"] = relationship(back_populates="settings")

    # Значения по умолчанию, применяются при первом создании записи (см. services/settings.py)
    DEFAULTS = {
        "welcome": {"enabled": True, "text": "Добро пожаловать, {mention}!", "clean_old": True},
        "goodbye": {"enabled": False, "text": "{mention} покинул(а) чат."},
        "rules": {"text": ""},
        "captcha": {"mode": "math", "timeout_sec": 120, "kick_on_fail": True},
        "antiflood": {"enabled": True, "max_messages": 7, "per_seconds": 8, "action": "mute"},
        "antispam": {"enabled": True},
        "anti_nsfw": {"enabled": False},
        "night_mode": {"enabled": False, "start_hour": 23, "end_hour": 7},
        "blocks": {"forwards": False, "links": False, "usernames": False, "bots": False, "inline": False},
        "media_blocks": {"photo": False, "video": False, "sticker": False, "gif": False, "voice": False, "document": False},
        "link_settings": {"action": "delete", "allow_admins": True, "whitelist": []},
        "approve_mode": {"enabled": False},
        "message_deletion": {"delete_service_messages": True, "delete_commands_after_sec": 0},
        "warns": {"max_warns": 3, "action": "ban"},
        "banned_words": {"action": "delete"},
        "tag_admin": {"cooldown_sec": 300},
        "tag_all": {"enabled": False},
        "max_message_length": {"enabled": False, "limit": 4000},
        "topics": {"enabled": False},
        "alphabets": {"enabled": False, "allowed": ["cyrillic", "latin"]},
        "privacy": {"user_privacy_mode": True},
    }


class ChatUser(Base):
    """Связь пользователь-чат: роль, статус, дата вступления, счётчик варнов."""
    __tablename__ = "chat_users"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_chat_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32), default="member")  # owner/admin/custom/member/muted/banned
    custom_role_id: Mapped[int | None] = mapped_column(ForeignKey("custom_roles.id"), nullable=True)
    warns: Mapped[int] = mapped_column(Integer, default=0)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)  # approve_mode
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user_id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_global_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- #
# Роли и права
# --------------------------------------------------------------------------- #

class CustomRole(Base):
    """Кастомные роли (например 'Модератор чатов', 'Саппорт')."""
    __tablename__ = "custom_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)  # {"ban": true, "mute": true, "pin": false, ...}


class CommandPermission(Base):
    """Общий редактор прав команд: какая роль может вызывать какую команду."""
    __tablename__ = "command_permissions"
    __table_args__ = (UniqueConstraint("chat_id", "command", name="uq_chat_command"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    command: Mapped[str] = mapped_column(String(64))
    min_role: Mapped[str] = mapped_column(String(32), default="admin")


# --------------------------------------------------------------------------- #
# Модерация
# --------------------------------------------------------------------------- #

class SanctionType(str, enum.Enum):
    warn = "warn"
    mute = "mute"
    ban = "ban"
    kick = "kick"
    unmute = "unmute"
    unban = "unban"


class AuditLog(Base):
    """Лог всех санкций — основа для /log канала и статистики."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    target_user_id: Mapped[int] = mapped_column(BigInteger)
    actor_user_id: Mapped[int] = mapped_column(BigInteger)  # кто выполнил (0 = бот/авто)
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BannedWord(Base):
    __tablename__ = "banned_words"
    __table_args__ = (UniqueConstraint("chat_id", "word", name="uq_chat_word"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    word: Mapped[str] = mapped_column(String(255))


# --------------------------------------------------------------------------- #
# Контент и интерактив
# --------------------------------------------------------------------------- #

class RecurringMessage(Base):
    """Повторяющиеся сообщения / отложенный постинг."""
    __tablename__ = "recurring_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    cron_expression: Mapped[str] = mapped_column(String(64))  # например "0 9 * * *"
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PersonalCommand(Base):
    """Пользовательские команды-триггеры (#заметки), а также magic sticker/gif ответы."""
    __tablename__ = "personal_commands"
    __table_args__ = (UniqueConstraint("chat_id", "trigger", name="uq_chat_trigger"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(128))
    response_type: Mapped[str] = mapped_column(String(16), default="text")  # text/sticker/gif/photo
    response_content: Mapped[str] = mapped_column(Text)  # текст или file_id
    created_by: Mapped[int] = mapped_column(BigInteger)


class TopicSettings(Base):
    """Настройки форум-топиков супергруппы."""
    __tablename__ = "topic_settings"
    __table_args__ = (UniqueConstraint("chat_id", "topic_id", name="uq_chat_topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    topic_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255), default="")
    locked_features: Mapped[dict] = mapped_column(JSON, default=dict)


class GroupStat(Base):
    """Ежедневная агрегированная статистика чата (сообщения, вступления, санкции)."""
    __tablename__ = "group_stats"
    __table_args__ = (UniqueConstraint("chat_id", "date", name="uq_chat_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"))
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    messages_count: Mapped[int] = mapped_column(Integer, default=0)
    joins_count: Mapped[int] = mapped_column(Integer, default=0)
    leaves_count: Mapped[int] = mapped_column(Integer, default=0)
    sanctions_count: Mapped[int] = mapped_column(Integer, default=0)


class BotClone(Base):
    """Список токенов клонов бота, запущенных под одной кодовой базой."""
    __tablename__ = "bot_clones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger)
    token: Mapped[str] = mapped_column(String(128), unique=True)
    bot_username: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
