# Telegram Group & Channel Management Bot

Каркас production-ориентированного бота на **aiogram 3 + PostgreSQL + Redis + Docker**,
построенный по архитектуре из ТЗ (Gateway → Application Core → Data Persistence →
Async Workers). Ниже — что реально реализовано, что требует доработки, и как запустить.

## ⚠️ Честно о статусе проекта

Полноценный клон Rose/Combot — это месяцы работы команды. За один проход я собрал:

- **Полную архитектуру и инфраструктуру**: Docker Compose (bot + PostgreSQL + Redis),
  модели БД под все ~40 фич, middleware-слой, систему настроек с кэшем в Redis,
  систему ролей.
- **Рабочую логику** для большинства модулей (см. таблицу ниже) — не заглушки, а
  реальный код, который делает то, что написано (проверено `py_compile`, но **не**
  тестировалось живым запуском — в песочнице нет сети, поэтому `pip install` и запуск
  против настоящего Telegram API я выполнить не мог).
- **Явно помеченные точки расширения** там, где нужен внешний сервис с API-ключом,
  который вы не указывали (anti-NSFW классификатор, конкретный провайдер аналитики и т.п.).

Перед продакшн-использованием: разверните локально, прогоните через реальный чат,
напишите тесты на критичные пути (санкции, капча, антифлуд).

## Статус по пунктам ТЗ

| # | Фича | Статус |
|---|------|--------|
| Roles & permissions hierarchy | ✅ реализовано | `utils/permissions.py`, `filters/roles.py` |
| Custom roles | ✅ реализовано | `handlers/moderation/custom_roles.py` |
| Moderation commands (ban/mute/kick/warn) | ✅ реализовано | `handlers/moderation/moderation_commands.py` |
| Channel users moderation | ✅ базово | `handlers/moderation/channel_moderation.py` |
| Anonymous admins support | ✅ реализовано | `middlewares/chat_context.py` |
| Bot support / help | ✅ реализовано | `handlers/core/start_help.py` |
| Bot clones support | 🟡 CRUD готов, оркестратор процессов — TODO | `handlers/core/clones.py` |
| UTC time settings | ✅ реализовано | `handlers/core/time_settings.py` |
| Langs and lang settings | ✅ базово (ru/en) | `handlers/core/lang_settings.py`, `locales/` |
| Rules | ✅ реализовано | `handlers/welcome/rules.py` |
| Welcome / Goodbye | ✅ реализовано | `handlers/welcome/` |
| Anti-flood | ✅ реализовано | `middlewares/antiflood.py` |
| Anti-spam | ✅ базовая эвристика (дубликаты) | `handlers/moderation/antispam.py` |
| Alphabets | ✅ реализовано | `handlers/misc/alphabets.py` |
| Captcha (math) | ✅ реализовано | `handlers/welcome/captcha.py` |
| Checks settings | ✅ базово (проверка прав бота) | `handlers/chat/checks_settings.py` |
| @Admin | ✅ реализовано | `handlers/chat/admin_tag.py` |
| Blocks (forwards/links/usernames/bots) | ✅ реализовано | `handlers/moderation/blocks.py` |
| Media blocks | ✅ реализовано | `handlers/moderation/media_blocks.py` |
| Anti-NSFW | 🟡 переключатель готов, классификатор изображений — TODO (нужен провайдер) | `handlers/moderation/anti_nsfw.py` |
| Warns settings | ✅ реализовано | `handlers/moderation/warns.py` |
| Night mode | ✅ реализовано | `handlers/moderation/night_mode.py` |
| Tag settings (@all) | ✅ реализовано | `handlers/chat/tag_settings.py` |
| Link settings | ✅ реализовано | `handlers/moderation/link_settings.py` |
| Approve mode | ✅ реализовано | `handlers/moderation/approve_mode.py` |
| Message deletion settings | ✅ реализовано | `handlers/moderation/message_deletion.py` |
| Topics settings | ✅ базово | `handlers/chat/topics_settings.py` |
| Banned words | ✅ реализовано | `handlers/moderation/banned_words.py` |
| Recurring messages | ✅ реализовано (APScheduler cron) | `handlers/chat/recurring_messages.py` |
| Members management | ✅ базово | `handlers/chat/members_management.py` |
| Masked users (маскированные ссылки) | ✅ реализовано | `handlers/moderation/masked_users.py` |
| Discussion group settings | ✅ базово | `handlers/chat/discussion_group.py` |
| Personal commands | ✅ реализовано | `handlers/chat/personal_commands.py` |
| Magic Stickers/GIFs | ✅ реализовано | `handlers/chat/magic_stickers_gifs.py` |
| Max message length | ✅ реализовано | `handlers/moderation/max_message_length.py` |
| Log channel | ✅ реализовано | `handlers/chat/log_channel.py`, `services/moderation_actions.py` |
| Staff group / /report | ✅ реализовано | `handlers/chat/staff_group.py` |
| Group statistics | ✅ базово (сообщения/join/leave/санкции по дням) | `handlers/chat/group_statistics.py` |
| Permissions editor | ✅ базово (мин. роль на команду) | `handlers/chat/permissions_editor.py` |
| /forget, remove user-data | ✅ реализовано | `handlers/chat/privacy.py` |
| User privacy mode | ✅ переключатель | `handlers/chat/privacy.py` |
| Crypto prices | ✅ реализовано (CoinGecko) | `handlers/misc/crypto_prices.py` |

🟡 = работает частично / нужна донастройка с вашей стороны (API-ключ, инфраструктура процессов).

## Архитектурные решения

- **Одна таблица `chat_settings` (JSON)** вместо ~40 отдельных таблиц под каждый toggle
  — см. docstring в `bot/database/models.py`. Структурные данные (варны, роли,
  забаненные слова, рассылки) — в отдельных таблицах.
- **Кэш настроек в Redis** (`services/settings_service.py`) — TTL 5 минут, чтобы не
  ходить в PostgreSQL на каждое сообщение (см. "Chat Context Middleware" в исходном ТЗ).
- **Единая точка применения санкций** (`services/moderation_actions.py`) — и команды,
  и авто-модули (antiflood, antispam, banned_words) идут через неё, что даёт
  консистентный AuditLog и лог-канал "из коробки".

## Запуск

```bash
git clone <ваш-репозиторий>
cd telegram-group-bot
cp .env.example .env
# впишите BOT_TOKEN (получить у @BotFather) и остальные переменные
docker compose up --build
```

Бот поднимется на **long polling** (см. `bot/main.py`). Для продакшна замените на
webhook: добавьте aiohttp web-сервер, `bot.set_webhook(...)` и Nginx с SSL перед ним
(см. блок Nginx в docker-compose — сейчас не включён, добавьте `nginx` сервис при
переходе на webhook).

### Локально без Docker

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# поднимите PostgreSQL и Redis локально, укажите их адреса в .env
python -m bot.main
```

## Как загрузить в свой GitHub

У меня нет сетевого доступа из песочницы, поэтому запушить самостоятельно я не могу.
Сделайте это одной командой у себя:

```bash
cd telegram-group-bot
git init
git add .
git commit -m "Initial commit: Telegram group/channel management bot scaffold"
git branch -M main
git remote add origin https://github.com/<ваш-юзернейм>/<репозиторий>.git
git push -u origin main
```

## Структура проекта

```
bot/
  config.py              # Pydantic-настройки из .env
  main.py                # Точка входа: Dispatcher, middleware, polling
  database/
    models.py             # Все ORM-модели
    engine.py              # Async engine/session
  middlewares/
    chat_context.py         # Роль пользователя + настройки чата
    throttling.py            # Rate limit на команды
    antiflood.py              # Anti-flood фильтр сообщений
  filters/roles.py         # HasRole("admin"|"owner"|...)
  services/
    settings_service.py    # CRUD настроек чата + кэш
    moderation_actions.py    # Единая точка ban/mute/kick/warn
    scheduler.py               # APScheduler (отложенные/cron задачи)
    cache.py                     # Redis-обёртка
  handlers/               # ~40 роутеров, сгруппированных по core/moderation/welcome/chat/misc
  locales/                # ru.json, en.json
docker-compose.yml
Dockerfile
requirements.txt
.env.example
```

## Что стоит сделать дальше (приоритеты)

1. Прогнать через реальный тестовый чат — поймать edge-кейсы Telegram API (права бота,
   лимиты).
2. Alembic-миграции вместо `Base.metadata.create_all` (уже сейчас безопасно для старта,
   но не для эволюции схемы в проде).
3. Подключить провайдера anti-NSFW (Sightengine/AWS Rekognition) — точка расширения
   уже готова в `handlers/moderation/anti_nsfw.py`.
4. Оркестратор процессов для bot-clones (сейчас только хранение токенов в БД).
5. UI-панель настроек через inline-кнопки (`/settings`) — сейчас конфигурация только
   командами.
