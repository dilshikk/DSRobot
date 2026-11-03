"""Общие настройки тестов.

bot.config создаёт Settings() при импорте и требует переменные окружения.
Задаём безопасные фиктивные значения ДО импорта модулей бота. Подключений к
PostgreSQL/Redis при импорте не происходит: движок и клиент создаются лениво.
"""
import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
