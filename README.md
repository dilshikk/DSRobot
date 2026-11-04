# Telegram Group & Channel Management Bot

Каркас production-ориентированного бота на **aiogram 3 + PostgreSQL + Redis + Docker**,
построенный по архитектуре из ТЗ (Gateway → Application Core → Data Persistence →
Async Workers). Ниже — что реально реализовано, что требует доработки, и как запустить.

## Функционал

| Функционал | Статус |
|------------|--------|
| Roles & permissions hierarchy | ✅ |
| Custom roles | ✅ |
| Moderation commands (ban/mute/kick/warn) | ✅ |
| Channel users moderation | ✅ |
| Anonymous admins support | ✅ |
| Bot support / help | ✅ |
| Bot clones support | 🟡 |
| UTC time settings | ✅ |
| Langs and lang settings | ✅ |
| Rules | ✅ |
| Welcome / Goodbye | ✅ |
| Anti-flood | ✅ |
| Anti-spam | ✅ |
| Alphabets | ✅ |
| Captcha (math) | ✅ |
| Checks settings | ✅ |
| @Admin tag | ✅ |
| Blocks (forwards/links/usernames/bots) | ✅ |
| Media blocks | ✅ |
| Anti-NSFW | ✅ |
| Warns settings | ✅ |
| Night mode | ✅ |
| Tag settings (@all) | ✅ |
| Link settings | ✅ |
| Approve mode | ✅ |
| Message deletion settings | ✅ |
| Topics settings | ✅ |
| Banned words | ✅ |
| Recurring messages | ✅ |
| Members management | ✅ |
| Masked users | ✅ |
| Discussion group settings | ✅ |
| Personal commands | ✅ |
| Magic Stickers/GIFs | ✅ |
| Max message length | ✅ |
| Log channel | ✅ |
| Staff group /report | ✅ |
| Group statistics | ✅ |
| Permissions editor | ✅ |
| /forget, user data removal | ✅ |
| User privacy mode | ✅ |
| Crypto prices | ✅ |

🟡 = работает частично / нужна донастройка (API-ключ, инфраструктура процессов).

### Антиспам

Команды: `/antispam`, `/setantispam ПОВТОРОВ [МИНУТЫ]`, `/cas on|off`, `/newcomers delete|warn|kick|ban|off|mute [МИНУТЫ]`

- Дубликаты одинаковых сообщений → мут
- Проверка по базе CAS (Combot Anti-Spam)
- Строгая проверка первых сообщений новичков

### Anti-NSFW

Команды: `/antinsfw`, `/nsfwlevel ПРОЦЕНТ`, `/nsfwaction delete|warn|kick|ban|mute [МИНУТЫ]`

- Локальная модель NudeNet (работает на CPU, без ключей)
- Проверка фото, стикеров и картинок
- Оценка кэшируется в Redis

## Команды бота

### Core

| Команда | Описание | Роль |
|---------|----------|------|
| `/start` | Запуск бота, показ помощи | member |
| `/help` | Основные разделы команд | member |
| `/commands` | Полный список команд | member |
| `/addclone <token>` | Регистрация клона бота | member |
| `/myclones` | Список клонированных ботов | member |
| `/delclone <id>` | Удаление клона | member |
| `/setlang <lang>` | Язык бота в чате | admin |
| `/setutc <offset>` | Часовой пояс чата | admin |

### Moderation

| Команда | Описание | Роль |
|---------|----------|------|
| `/ban [reason]` | Забанить пользователя | admin |
| `/unban` | Разбанить пользователя | admin |
| `/kick [reason]` | Удалить (может вернуться) | admin |
| `/mute [dur] [reason]` | Отключить сообщения | admin |
| `/unmute` | Вернуть права на сообщения | admin |
| `/warn [reason]` | Предупреждение | admin |
| `/unwarn` | Снять предупреждение | admin |
| `/setwarnlimit <num>` | Лимит предупреждений | admin |
| `/setwarnaction <ban\|kick\|mute>` | Авто-действие при лимите | admin |
| `/promote` | Повысить до админа | owner |
| `/demote` | Понизить админа | owner |
| `/addrole <name> <perms>` | Создать кастомную роль | admin |
| `/setrole <role>` | Назначить роль | admin |
| `/unsetrole` | Снять роль | admin |
| `/delrole <name>` | Удалить роль | admin |
| `/setcmdperm <cmd> <role>` | Мин. роль для команды | owner |
| `/antispam` | Вкл/выкл антиспам | admin |
| `/setantispam <repeats> [min]` | Настройка антиспама | admin |
| `/cas on\|off` | Проверка по базе CAS | admin |
| `/newcomers <action> [min]` | Действие для новичков | admin |
| `/setflood <msgs> <sec> [action] [min]` | Anti-flood настройка | admin |
| `/floodoff` | Выключить anti-flood | admin |
| `/addword <word>` | Добавить в чёрный список | admin |
| `/delword <word>` | Удалить из чёрного списка | admin |
| `/words` | Список запрещённых слов | admin |
| `/wordmode <word\|substring>` | Режим поиска слов | admin |
| `/wordaction <delete\|warn\|kick\|ban\|mute>` | Действие за слова | admin |
| `/linkaction <delete\|warn\|ban\|mute\|off>` | Действие на ссылки | admin |
| `/allowlink <domain>` | Белый список доменов | admin |
| `/denylink <domain>` | Удалить из белого списка | admin |
| `/linkadmins on\|off` | Ссылки админов | admin |
| `/block <type>` | Включить блокировку | admin |
| `/unblock <type>` | Выключить блокировку | admin |
| `/blockmedia <type>` | Блокировка медиа | admin |
| `/unblockmedia <type>` | Разблокировка медиа | admin |
| `/maskedlinks` | Фильтр замаскированных ссылок | admin |
| `/antinsfw` | Вкл/выкл Anti-NSFW | admin |
| `/nsfwlevel <percent>` | Порог NSFW | admin |
| `/nsfwaction <delete\|warn\|kick\|ban\|mute>` | Действие за NSFW | admin |
| `/cleanservice` | Удаление service-сообщений | admin |
| `/delcommands <sec>` | Автоудаление команд | admin |
| `/setmaxlen <chars>` | Макс. длина сообщения | admin |
| `/nightmode <start> <end>\|off` | Ночной режим | admin |
| `/approve` | Одобрить пользователя | admin |
| `/unapprove` | Снять одобрение | admin |
| `/approvemode` | Вкл/выкл режим одобрения | admin |
| `/banchannel` | Забанить канал | admin |
| `/setalphabet <types>\|off` | Фильтр алфавитов | admin |

### Welcome

| Команда | Описание | Роль |
|---------|----------|------|
| `/setrules <text>` | Правила чата | admin |
| `/rules` | Показать правила | member |
| `/setwelcome <text>` | Приветствие | admin |
| `/welcomeoff` | Выключить приветствие | admin |
| `/welcomeclean on\|off` | Удаление старого приветствия | admin |
| `/setgoodbye <text>` | Прощание | admin |
| `/goodbyeoff` | Выключить прощание | admin |
| `/captcha` | Вкл/выкл капчу | admin |
| `/captchatimeout <sec>` | Таймаут капчи | admin |
| `/captchakick on\|off` | Исключение при провале капчи | admin |

### Chat

| Команда | Описание | Роль |
|---------|----------|------|
| `/addnote #trigger text` | Создать заметку | admin |
| `/delnote #trigger` | Удалить заметку | admin |
| `/notes` | Список заметок | member |
| `/admin` | @упоминание админов | member |
| `/admincooldown <sec>` | Кулдаун /admin | admin |
| `/stats [today\|week\|month]` | Статистика группы | admin |
| `/members` | Количество участников | admin |
| `/inactive [days]` | Неактивные участники | admin |
| `/forget` | Удалить данные (этот чат) | member |
| `/forgetme` | Удалить данные (все чаты) | member |
| `/addrecurring <cron> text` | Регулярное сообщение | admin |
| `/delrecurring <id>` | Удалить рассылку | admin |
| `/recurring` | Список рассылок | member |
| `/report` | Отчёт в staff-группу | member |
| `/tagall [text]` | @упоминание всех | admin |
| `/checkperms` | Проверка прав бота | member |
| `/addmagic keyword` | Magic sticker/GIF | admin |
| `/delmagic keyword` | Удалить magic response | admin |
| `/linkdiscussion <id>` | Discussion group | owner |
| `/setlogchannel <id>` | Лог-канал | owner |
| `/newtopic <name>` | Создать тему (forum) | admin |
| `/closetopic` | Закрыть тему | admin |
| `/locktopic <type>` | Заблокировать в теме | admin |
| `/unlocktopic <type>` | Разблокировать в теме | admin |
| `/topiclocks` | Локи в теме | admin |

### Misc

| Команда | Описание | Роль |
|---------|----------|------|
| `/price <coin>` | Цена криптовалюты | member |
| `/whoami` | Текущая роль / анонимность | member |

## Архитектурные решения

- **Одна таблица `chat_settings` (JSONB)** вместо ~40 отдельных таблиц под каждый toggle
  — см. docstring в `bot/database/models.py`. Структурные данные (варны, роли,
  забаненные слова, рассылки) — в отдельных таблицах.
- **Кэш настроек в Redis** (`services/settings_service.py`) — TTL 5 минут, чтобы не
  ходить в PostgreSQL на каждое сообщение (см. "Chat Context Middleware" в исходном ТЗ).
- **Единая точка применения санкций** (`services/moderation_actions.py`) — и команды,
  и авто-модули (antiflood, antispam, banned_words, anti_nsfw) идут через неё, что даёт
  консистентный AuditLog и лог-канал "из коробки".

## Запуск

```bash
git clone https://github.com/dilshikk/DSRobot.git
cd DSRobot
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

Схема БД обновляется автоматически при старте (Alembic). Вручную: `alembic upgrade head`.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest                    # все 40+ тестов
pytest tests/test_foo.py  # конкретный тест
pytest -v                 # подробный вывод
```

PostgreSQL и Redis для тестов не нужны: `tests/conftest.py` подменяет их InMemory-заглушками.

## CI

GitHub Actions (`.github/workflows/ci.yml`) запускает:
- `ruff check` — проверка критических ошибок (E9, F63, F7, F82)
- `pytest -q` — тесты
- `docker build` — проверка сборки Docker

## Структура проекта

```
bot/
  config.py                    # Pydantic-настройки из .env
  main.py                      # Точка входа: Dispatcher, middleware, polling
  database/
    models.py                   # Все ORM-модели
    engine.py                   # Async engine/session, запуск Alembic
    legacy.py                   # Миграция старых данных
    migrations/                 # Alembic-ревизии
  middlewares/
    chat_context.py             # Роль пользователя + настройки чата
    throttling.py               # Rate limit на команды
    antiflood.py                # Anti-flood фильтр сообщений
    moderation_pipeline.py      # Модерация сообщений
    callback_context.py         # Контекст для callback-кнопок
  filters/
    roles.py                    # HasRole("admin"|"owner"|...)
  services/
    settings_service.py         # CRUD настроек чата + кэш
    moderation_actions.py       # Единая точка ban/mute/kick/warn
    scheduler.py                # APScheduler (отложенные/cron задачи)
    cache.py                    # Redis-обёртка
    cas.py                      # Проверка по базе Combot Anti-Spam
    nsfw.py                     # Anti-NSFW: локальная модель NudeNet
    roles.py                    # Иерархия ролей
    user_service.py             # Сервис пользователей
    privacy_service.py          # GDPR-данные
    recurring.py                # Регулярные сообщения
    triggers.py                 # Триггеры-ответы
    bot_registry.py             # Реестр ботов-клонов
    chat_binding.py             # Привязка каналов
    chat_lang.py                # Язык чата
    clone_crypto.py             # Шифрование токенов клонов
    clone_runner.py             # Запуск клонов
    moderation_targets.py       # Цели модерации
  handlers/                     # ~82 команды, сгруппированные по категориям
    core/                       # start, help, clones, lang, time
    moderation/                 # ban, mute, warn, spam, blocks, nsfw
    welcome/                    # rules, welcome, goodbye, captcha
    chat/                       # stats, members, notes, recurring, topics
    misc/                       # crypto, alphabets
  locales/
    ru.json                     # Русский язык
    en.json                     # English
  utils/
    i18n.py                     # Интернационализация
    parsing.py                  # Парсинг текста
    permissions.py              # Проверка прав
    telegram.py                 # Telegram API утилиты
    text_match.py               # Сравнение текстов
    text_template.py            # Шаблоны текста
    html_fallback.py            # Fallback для HTML

tests/                          # 40+ тестов (pytest)
docker-compose.yml
docker-compose.dev.yml
Dockerfile
requirements.txt
requirements-dev.txt
alembic.ini
.env.example
.github/workflows/ci.yml
```

## Что стоит сделать дальше (приоритеты)

1. Прогнать через реальный тестовый чат — поймать edge-кейсы Telegram API (права бота,
   лимиты).
2. Оркестратор процессов для bot-clones (сейчас только хранение токенов в БД).
3. UI-панель настроек через inline-кнопки (`/settings`) — сейчас конфигурация только
   командами.
