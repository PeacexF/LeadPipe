from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionJob, CollectionJobResult, JobStatus, Source


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: int) -> CollectionJob | None:
        return await self.session.get(CollectionJob, job_id)

    async def create(self, source_id: int) -> CollectionJob:
        job = CollectionJob(source_id=source_id, status=JobStatus.PENDING)
        self.session.add(job)
        await self.session.flush()
        return job

    async def page(
        self,
        limit: int = 50,
        before_id: int | None = None,
        status: JobStatus | None = None,
        source: str | None = None,
    ) -> list[tuple[CollectionJob, str, CollectionJobResult | None]]:
        stmt = (
            select(CollectionJob, Source.name, CollectionJobResult)
            .join(Source, Source.id == CollectionJob.source_id)
            .outerjoin(CollectionJobResult, CollectionJobResult.job_id == CollectionJob.id)
            .order_by(CollectionJob.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(CollectionJob.id < before_id)
        if status is not None:
            stmt = stmt.where(CollectionJob.status == status)
        if source is not None:
            stmt = stmt.where(Source.name == source)
        return list((await self.session.execute(stmt)).all())  # type: ignore[arg-type]

    async def detail(
        self, job_id: int
    ) -> tuple[CollectionJob, str, CollectionJobResult | None] | None:
        stmt = (
            select(CollectionJob, Source.name, CollectionJobResult)
            .join(Source, Source.id == CollectionJob.source_id)
            .outerjoin(CollectionJobResult, CollectionJobResult.job_id == CollectionJob.id)
            .where(CollectionJob.id == job_id)
        )
        row = (await self.session.execute(stmt)).first()
        return None if row is None else (row[0], row[1], row[2])

    async def list_for_source(self, source_id: int) -> Sequence[CollectionJob]:
        stmt = (
            select(CollectionJob)
            .where(CollectionJob.source_id == source_id)
            .order_by(CollectionJob.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def mark_running(self, job: CollectionJob) -> CollectionJob:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self.session.flush()
        return job

    async def mark_finished(
        self, job: CollectionJob, status: JobStatus, error: str | None = None
    ) -> CollectionJob:
        job.status = status
        job.error = error
        job.finished_at = datetime.now(UTC)
        await self.session.flush()
        return job

    async def save_results(
        self,
        job_id: int,
        collected: int = 0,
        valid: int = 0,
        invalid: int = 0,
        duplicates: int = 0,
        new_leads: int = 0,
        errors: int = 0,
    ) -> CollectionJobResult:
        result = await self.session.scalar(
            select(CollectionJobResult).where(CollectionJobResult.job_id == job_id)
        )
        if result is None:
            result = CollectionJobResult(job_id=job_id)
            self.session.add(result)
        result.collected = collected
        result.valid = valid
        result.invalid = invalid
        result.duplicates = duplicates
        result.new_leads = new_leads
        result.errors = errors
        await self.session.flush()
        return result
