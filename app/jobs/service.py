from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.models import AppConfig
from app.db.models import CollectionJob, Source
from app.repositories import JobRepository, SourceRepository


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
    source_config = config.source(source_name)
    source = await SourceRepository(session).upsert(
        name=source_config.name,
        type=source_config.type,
        priority=source_config.priority,
        enabled=source_config.enabled,
        config=source_config.options,
    )
    return await JobRepository(session).create(source.id)
