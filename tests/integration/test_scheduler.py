import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import load_config
from app.config.models import AppConfig, ScheduleConfig
from app.db.models import CollectionJob, JobStatus
from app.jobs import CollectionScheduler, queue
from app.jobs.service import enqueue_if_idle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def config_with_schedule(cron: str = "0 9 * * *", enabled: bool = True) -> AppConfig:
    config = load_config(Path("examples/configs/csv.yaml"))
    config.sources[0].schedule = ScheduleConfig(enabled=enabled, cron=cron)
    return config


CONFIG = load_config(Path("examples/configs/csv.yaml"))


async def jobs_for(session: AsyncSession) -> int:
    return (await session.scalars(select(func.count()).select_from(CollectionJob))).one()


async def test_scheduler_registers_one_job_per_scheduled_source(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule())
    assert scheduler.configure() == ["example_csv"]
    assert [job.id for job in scheduler.scheduler.get_jobs()] == ["collect:example_csv"]


async def test_nothing_is_registered_without_schedules(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule(enabled=False))
    assert scheduler.configure() == []
    scheduler.start()
    assert not scheduler.scheduler.running


async def test_firing_queues_a_job(factory: async_sessionmaker[AsyncSession]) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule())

    job_id = await scheduler.fire("example_csv")

    assert job_id is not None
    async with factory() as session:
        job = await session.get(CollectionJob, job_id)
        assert job is not None
        assert job.status is JobStatus.PENDING
        assert await jobs_for(session) == 1


async def test_a_tick_is_skipped_while_a_job_is_pending(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule())

    first = await scheduler.fire("example_csv")
    second = await scheduler.fire("example_csv")

    assert first is not None
    assert second is None
    async with factory() as session:
        assert await jobs_for(session) == 1


async def test_a_tick_is_skipped_while_a_job_is_running(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule())
    await scheduler.fire("example_csv")

    async with factory() as session:
        claimed = await queue.claim(session, "worker")
        await session.commit()
    assert claimed is not None

    assert await scheduler.fire("example_csv") is None
    async with factory() as session:
        assert await jobs_for(session) == 1


async def test_the_next_tick_queues_again_once_the_job_finishes(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    scheduler = CollectionScheduler(factory, config_with_schedule())
    first = await scheduler.fire("example_csv")

    async with factory() as session:
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == first)
            .values(status=JobStatus.COMPLETED)
        )
        await session.commit()

    second = await scheduler.fire("example_csv")

    assert second is not None
    assert second != first


async def test_concurrent_schedulers_queue_only_one_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    config = config_with_schedule()

    async def tick() -> int | None:
        async with factory() as session:
            job = await enqueue_if_idle(session, config, "example_csv")
            await session.commit()
            return job.id if job else None

    results = await asyncio.gather(*(tick() for _ in range(5)))

    assert sum(result is not None for result in results) == 1
    async with factory() as session:
        assert await jobs_for(session) == 1
