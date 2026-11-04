# Внесение вклада в DSRobot

## Настройка разработки

1. `cp .env.example .env` — заполнить переменные
2. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` — полный стек
3. `pip install -r requirements-dev.txt` — зависимости для разработки

## Запуск тестов

```bash
pytest                    # все тесты
pytest tests/test_foo.py  # конкретный тест
pytest -v                 # подробный вывод
```

**Важно:** PostgreSQL и Redis НЕ нужны — `conftest.py` подменяет их InMemory-заглушками.

## Проверка кода

```bash
ruff check --select E9,F63,F7,F82 bot tests
python -m compileall -q bot tests
```

## Миграции

1. Все изменения ORM-моделей (`bot/database/models.py`) требуют Alembic-ревизии.
2. **Обязательно:** после создания ревизии обновите `tests/test_migrations.py`:
   - Добавьте новый revision ID в список `REVISIONS`
   - Убедитесь, что `test_revisions_cover_every_model_table` проходит
3. Не редактируйте `0001_baseline` — только добавляйте новые ревизии.
4. Запуск: `alembic upgrade head`

## CI/Непрерывная интеграция

GitHub Actions запускает:
- `ruff check` — только критические ошибки (E9, F63, F7, F82)
- `pytest -q` — тесты
- `docker build` — проверка сборки

## Стиль кода

- Python 3.12+
- aiogram 3.x patterns: `@router.message(Command("..."))`
- Outer middleware для модерации, inner для throttling
- Ответы на языке чата через `t(lang, key)`
