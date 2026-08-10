import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.cron import build_trigger
from app.config.models import AppConfig, SourceConfig
from app.jobs.service import enqueue_if_idle

logger = logging.getLogger(__name__)


def trigger_for(source: SourceConfig) -> CronTrigger:
    if source.schedule is None:
        raise ValueError(f"source '{source.name}' has no schedule")
    return build_trigger(source.schedule.cron, source.schedule.timezone)


def next_run(source: SourceConfig, after: datetime) -> datetime | None:
    fire_time = trigger_for(source).get_next_fire_time(None, after)
    return fire_time if isinstance(fire_time, datetime) else None


class CollectionScheduler:
    # Turns cron entries into queued jobs. It never runs a pipeline itself

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config
        self.scheduler = scheduler or AsyncIOScheduler()

    def configure(self) -> list[str]:
        scheduled = []
        for source in self.config.scheduled_sources():
            self.scheduler.add_job(
                self.fire,
                trigger=trigger_for(source),
                args=[source.name],
                id=f"collect:{source.name}",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduled.append(source.name)
            logger.info(
                "scheduled source=%s cron=%s tz=%s",
                source.name,
                source.schedule.cron if source.schedule else "",
                source.schedule.timezone if source.schedule else "",
            )
        return scheduled

    async def fire(self, source_name: str) -> int | None:
        async with self.session_factory() as session:
            job = await enqueue_if_idle(session, self.config, source_name)
            await session.commit()

        if job is None:
            logger.info("source=%s already queued or running, skipping tick", source_name)
            return None
        logger.info("job=%s source=%s queued by schedule", job.id, source_name)
        return job.id

    def start(self) -> None:
        if self.scheduler.get_jobs():
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
