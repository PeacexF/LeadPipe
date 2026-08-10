from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionJob, CollectionJobResult, JobStatus


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
