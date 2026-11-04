"""
Централизованная конфигурация бота.
Все настройки читаются из переменных окружения (.env).
"""
from __future__ import annotations

from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_ids(raw: str) -> set[int]:
    """'1, 2,abc' -> {1, 2}. Мусор пропускается."""
    return {int(part) for part in (p.strip() for p in raw.split(",")) if part.isdigit()}


class Settings(BaseSettings):
    # env_ignore_empty: пустое значение (SUPPORT_CHAT_ID=) = значение по умолчанию, а не ошибка парсинга int.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True,
    )

    # Telegram
    bot_token: str
    bot_id: int | None = None
    support_chat_id: int | None = None
    # issue #94: false — апдейты, накопленные во время простоя (входы, сообщения), обрабатываются
    # после перезапуска: новички получают капчу, спам модерируется. true — выбрасываются.
    drop_pending_updates: bool = False

    # Roles (issue #11)
    # Telegram id через запятую, кто получает роль developer во всех чатах. Пусто = никто.
    developer_user_ids: str = ""

    # Clones (issue #6)
    # Fernet-ключ для шифрования токенов клонов. Без него клоны отключены.
    clone_encryption_key: str | None = None
    # Telegram id через запятую, кому разрешено создавать клоны. Пусто = никому.
    clone_allowed_user_ids: str = ""
    max_clones_per_user: int = 1

    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # Misc
    default_lang: str = "ru"
    log_level: str = "INFO"
    sentry_dsn: str | None = None
    crypto_api_url: str = "https://api.coingecko.com/api/v3/simple/price"
    # Combot Anti-Spam: база известных спамеров (issue #14). Ключ не нужен.
    cas_api_url: str = "https://api.cas.chat/check"
    # Anti-NSFW: локальная модель NudeNet (issue #14). false — модель не загружается
    # (например, на слабом сервере), /antinsfw тогда ничего не удаляет.
    nsfw_enabled: bool = True

    @property
    def clone_allowed_ids(self) -> set[int]:
        return _parse_ids(self.clone_allowed_user_ids)

    @property
    def developer_ids(self) -> set[int]:
        return _parse_ids(self.developer_user_ids)

    @property
    def database_url(self) -> str:
        # Экранируем учётные данные: пароль может содержать @, :, / и т.п.
        return (
            f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:{quote(self.postgres_password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{quote(self.redis_password, safe='')}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()  # type: ignore[call-arg]
