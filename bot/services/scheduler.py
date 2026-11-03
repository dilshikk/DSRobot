"""
APScheduler-обёртка для отложенных задач:
- автоматическое размутивание/разбан по истечении срока,
- отложенный постинг / рассылки,
- периодические recurring_messages (по cron),
- таймаут капчи (кик не прошедших капчу вовремя).
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

scheduler = AsyncIOScheduler()


def schedule_once(func, run_at, *args, job_id: str | None = None, **kwargs) -> None:
    scheduler.add_job(func, trigger=DateTrigger(run_date=run_at), args=args, kwargs=kwargs,
                       id=job_id, replace_existing=True, misfire_grace_time=3600)


def schedule_cron(func, cron_expression: str, *args, job_id: str | None = None, **kwargs) -> None:
    scheduler.add_job(func, trigger=CronTrigger.from_crontab(cron_expression), args=args, kwargs=kwargs,
                       id=job_id, replace_existing=True)


def start() -> None:
    if not scheduler.running:
        scheduler.start()
