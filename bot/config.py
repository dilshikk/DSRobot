"""
Централизованная конфигурация бота.
Все настройки читаются из переменных окружения (.env).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str
    bot_id: int | None = None
    support_chat_id: int | None = None

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

    # Misc
    default_lang: str = "ru"
    log_level: str = "INFO"
    sentry_dsn: str | None = None
    crypto_api_url: str = "https://api.coingecko.com/api/v3/simple/price"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()  # type: ignore[call-arg]
