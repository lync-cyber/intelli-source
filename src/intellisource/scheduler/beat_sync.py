"""Celery Beat schedule synchronisation (AC-T100-1/2).

Reads the in-memory `SchedulerManager` state and writes equivalent
`celery_app.conf.beat_schedule` entries so the Celery Beat scheduler can
fire `run_pipeline` tasks for every registered schedule.

Cron string forms supported:
- 5-field crontab string (``"*/5 * * * *"``) — parsed via ``celery.schedules.crontab``
- Bare integer (``"600"``) — interpreted as seconds, mapped to ``timedelta``
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery.schedules import crontab

from intellisource.scheduler.state_machine import SchedulerManager

logger = logging.getLogger(__name__)


def _parse_schedule(cron_expr: str) -> Any:
    """Return a `crontab` or `timedelta` instance for the given expression.

    Accepts a 5-field cron string or a bare positive integer (seconds).
    Raises ``ValueError`` on neither form to surface mis-configured Source
    rows early instead of silently dropping schedules.
    """
    stripped = cron_expr.strip()
    try:
        seconds = int(stripped)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds <= 0:
            raise ValueError(f"schedule seconds must be > 0, got {seconds!r}")
        return timedelta(seconds=seconds)

    parts = stripped.split()
    if len(parts) != 5:
        raise ValueError(
            f"unsupported schedule expression: {cron_expr!r}"
            " (expected 5-field cron or integer seconds)"
        )
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def sync_beat_schedules(
    celery_app: Any, scheduler_manager: SchedulerManager
) -> dict[str, dict[str, Any]]:
    """Project SchedulerManager state onto `celery_app.conf.beat_schedule`.

    Each registered schedule becomes a ``beat_schedule`` entry that fires
    the well-known ``run_pipeline`` Celery task with the pipeline name +
    params from the SchedulerManager record. Returns the resulting mapping
    so callers can assert it in tests.
    """
    beat_schedule: dict[str, dict[str, Any]] = {}
    for entry in scheduler_manager.list_schedules():
        name: str = entry["name"]
        try:
            schedule = _parse_schedule(entry["cron_expr"])
        except ValueError:
            logger.warning(
                "Skipping schedule '%s' — unparseable cron_expr=%r",
                name,
                entry.get("cron_expr"),
            )
            continue

        beat_schedule[name] = {
            "task": "run_pipeline",
            "schedule": schedule,
            "kwargs": {
                "pipeline_name": entry["pipeline_name"],
                "params": entry.get("params") or {},
            },
        }

    celery_app.conf.beat_schedule = beat_schedule
    if not beat_schedule:
        logger.warning(
            "Celery beat_schedule is empty after sync — Beat will not fire any"
            " run_pipeline tasks; check Source.schedule_interval rows"
        )
    return beat_schedule


async def populate_scheduler_from_sources(
    scheduler_manager: SchedulerManager,
    session_factory: Any,
    *,
    pipeline_resolver: Any = None,
) -> int:
    """Populate the SchedulerManager from the DB Source table.

    Each row's ``schedule_interval`` (seconds) is registered as a schedule
    named after the source id. The pipeline name is resolved via
    ``pipeline_resolver(source) -> str`` if provided, otherwise via the
    composition-level ``SOURCE_TYPE_TO_PIPELINE`` mapping. Returns the
    number of schedules registered.
    """
    from sqlalchemy import select

    from intellisource.composition import SOURCE_TYPE_TO_PIPELINE
    from intellisource.storage.models import Source

    registered = 0
    async with session_factory() as session:
        result = await session.execute(select(Source))
        sources = list(result.scalars().all())

    for source in sources:
        interval = getattr(source, "schedule_interval", None)
        if not interval:
            logger.warning(
                "Source %s skipped: schedule_interval=%r (zero or null)",
                getattr(source, "id", "?"),
                interval,
            )
            continue
        if pipeline_resolver is not None:
            pipeline_name = pipeline_resolver(source)
        else:
            pipeline_name = SOURCE_TYPE_TO_PIPELINE.get(
                getattr(source, "type", ""), "scheduled-collect"
            )
        schedule_name = f"source-{source.id}"
        try:
            scheduler_manager.register_schedule(
                name=schedule_name,
                cron_expr=str(interval),
                pipeline_name=pipeline_name,
                params={"source_id": str(source.id)},
            )
            registered += 1
        except ValueError:
            # Already registered (worker restart with stable schedule names) — skip.
            continue

    if registered == 0:
        logger.warning(
            "No Source rows with schedule_interval found — Beat will register"
            " zero scheduled tasks; ingest Source rows or set IS_BEAT_DISABLED=1"
        )
    return registered
