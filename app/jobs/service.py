from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.models import AppConfig
from app.db.models import CollectionJob, JobStatus, Source
from app.repositories import JobRepository, SourceRepository

ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


async def sync_sources(session: AsyncSession, config: AppConfig) -> Sequence[Source]:
    repo = SourceRepository(session)
    return [
        await repo.upsert(
            name=source.name,
            type=source.type,
            priority=source.priority,
            enabled=source.enabled,
            config=source.options,
        )
        for source in config.sources
    ]


async def enqueue(session: AsyncSession, config: AppConfig, source_name: str) -> CollectionJob:
    source = await _upsert_source(session, config, source_name)
    return await JobRepository(session).create(source.id)


async def enqueue_if_idle(
    session: AsyncSession, config: AppConfig, source_name: str
) -> CollectionJob | None:
    """
    Queue a job unless one is already waiting or running for this source.

    Locks the source row first, so two schedulers cannot both pass the check.
    """
    source = await _upsert_source(session, config, source_name)
    await session.execute(select(Source.id).where(Source.id == source.id).with_for_update())

    active = await session.scalar(
        select(CollectionJob.id)
        .where(
            CollectionJob.source_id == source.id,
            CollectionJob.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if active is not None:
        return None
    return await JobRepository(session).create(source.id)


async def _upsert_source(session: AsyncSession, config: AppConfig, source_name: str) -> Source:
    source_config = config.source(source_name)
    return await SourceRepository(session).upsert(
        name=source_config.name,
        type=source_config.type,
        priority=source_config.priority,
        enabled=source_config.enabled,
        config=source_config.options,
    )
