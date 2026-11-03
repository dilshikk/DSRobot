"""
APScheduler-обёртка для отложенных задач (issue #10):
- таймаут капчи (кик не прошедших капчу вовремя),
- периодические recurring_messages (по cron, в часовом поясе чата).

Задачи хранятся в Redis (RedisJobStore), поэтому переживают перезапуск контейнера.
Redis в docker-compose запущен с --appendonly yes, то есть пишет данные на диск.

Важно про сериализацию: задача хранится как ссылка "модуль:функция" + аргументы
(pickle). Поэтому:
- функции задач должны быть объявлены на уровне модуля;
- в аргументах только простые значения (id чата, id пользователя, id бота), а не Bot;
- переименование функции задачи ломает уже сохранённые задачи.

Снятие временного мута/бана отдельной задачей не требуется: его выполняет сам
Telegram по until_date (см. services/moderation_actions.py).
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from bot.config import settings

logger = logging.getLogger(__name__)

JOBS_KEY = "dsrobot:apscheduler.jobs"
RUN_TIMES_KEY = "dsrobot:apscheduler.run_times"
# Пропущенную во время простоя рассылку отправляем, только если опоздали не больше чем на 5 минут.
# Иначе после долгого простоя в чат разом прилетели бы устаревшие объявления.
CRON_MISFIRE_GRACE_SEC = 300

# coalesce: несколько пропущенных запусков одной задачи схлопываются в один.
scheduler = AsyncIOScheduler(timezone=timezone.utc, job_defaults={"coalesce": True, "max_instances": 1})


def _make_jobstore() -> RedisJobStore:
    # Отдельный синхронный клиент: jobstore хранит pickle-байты, а общий клиент
    # из services/cache.py работает с decode_responses=True.
    return RedisJobStore(
        jobs_key=JOBS_KEY,
        run_times_key=RUN_TIMES_KEY,
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password,
    )


def chat_timezone(utc_offset: int) -> timezone:
    return timezone(timedelta(hours=utc_offset))


def build_cron_trigger(cron_expression: str, utc_offset: int = 0) -> CronTrigger:
    """Cron в часовом поясе чата. Бросает ValueError при неверном выражении."""
    return CronTrigger.from_crontab(cron_expression, timezone=chat_timezone(utc_offset))


def schedule_once(func, run_at, *args, job_id: str | None = None, **kwargs) -> None:
    # misfire_grace_time=None: разовая задача выполняется, даже если бот был выключен
    # дольше обычного. Иначе таймаут капчи мог потеряться и участник остался бы
    # ограниченным навсегда.
    scheduler.add_job(func, trigger=DateTrigger(run_date=run_at), args=args, kwargs=kwargs,
                      id=job_id, replace_existing=True, misfire_grace_time=None)


def schedule_cron(func, cron_expression: str, *args, job_id: str | None = None,
                  utc_offset: int = 0, **kwargs) -> None:
    scheduler.add_job(func, trigger=build_cron_trigger(cron_expression, utc_offset), args=args, kwargs=kwargs,
                      id=job_id, replace_existing=True, misfire_grace_time=CRON_MISFIRE_GRACE_SEC)


def remove_job(job_id: str) -> None:
    try:
        scheduler.remove_job(job_id)
    except JobLookupError:
        pass


def start(persistent: bool = True) -> None:
    if scheduler.running:
        return
    if persistent:
        scheduler.add_jobstore(_make_jobstore(), "default")
    scheduler.start()
    logger.info("Планировщик запущен, сохранённых задач: %d", len(scheduler.get_jobs()))
