from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import __version__
from app.api.deps import (
    ConfigDep,
    FactoryDep,
    FilterDep,
    LimitDep,
    SessionDep,
    require_api_key,
)
from app.api.schemas import (
    DeletionResult,
    Health,
    JobCreate,
    JobOut,
    LeadDetail,
    LeadOut,
    Page,
    Ready,
    SourceOut,
    SuppressionCreate,
    SuppressionOut,
)
from app.db.health import check_readiness
from app.db.models import JobStatus
from app.domain.filters import LeadFilter
from app.exports import CONTENT_TYPES, FORMATS, export_leads
from app.jobs.service import enqueue
from app.repositories import (
    JobRepository,
    LeadRepository,
    SourceRepository,
    SuppressionRepository,
)

router = APIRouter()
api = APIRouter(prefix="/api")


@router.get("/health", response_model=Health, tags=["health"])
async def health() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/health/ready", response_model=Ready, tags=["health"])
async def ready(session: SessionDep, response: Response) -> Ready:
    # Readiness: the database answers and the schema is at the expected revision
    result = await check_readiness(session)
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Ready(
        status="ok" if result.ready else "not ready",
        database=result.database,
        migrations_current=result.migrations_current,
        applied_revision=result.applied_revision,
        expected_revision=result.expected_revision,
        detail=result.detail,
    )


@api.get("/leads", response_model=Page[LeadOut], tags=["leads"])
async def list_leads(
    session: SessionDep,
    filters: FilterDep,
    limit: LimitDep,
    cursor: Annotated[int, Query(ge=0, description="Leads with an id above this.")] = 0,
) -> Page[LeadOut]:
    rows = await LeadRepository(session).page(filters, limit=limit, after_id=cursor)
    items = [LeadOut.of(row) for row in rows]
    return Page(
        items=items,
        limit=limit,
        next_cursor=items[-1].id if len(items) == limit else None,
    )


@api.get("/leads/{lead_id}", response_model=LeadDetail, tags=["leads"])
async def get_lead(lead_id: int, session: SessionDep) -> LeadDetail:
    repo = LeadRepository(session)
    rows = await repo.page(limit=1, after_id=lead_id - 1)
    if not rows or rows[0].lead.id != lead_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
    provenance = await repo.provenance(lead_id)
    return LeadDetail.detail(rows[0].lead, rows[0].sources, list(provenance))


@api.delete(
    "/leads/{lead_id}",
    response_model=DeletionResult,
    dependencies=[Depends(require_api_key)],
    tags=["leads"],
)
async def delete_lead(
    lead_id: int,
    session: SessionDep,
    suppress: Annotated[
        bool, Query(description="Also block this lead from being collected again.")
    ] = True,
) -> DeletionResult:
    # Erase a lead and every record it was built from
    leads = LeadRepository(session)
    lead = await leads.get(lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")

    added = []
    if suppress:
        added = await SuppressionRepository(session).add_for_lead(
            lead.email, lead.website_domain, reason=f"lead {lead_id} deleted"
        )

    deleted = await leads.delete(lead_id)
    await session.commit()
    return DeletionResult(deleted=deleted, suppressed=[SuppressionOut.of(entry) for entry in added])


@api.get("/suppressions", response_model=list[SuppressionOut], tags=["suppressions"])
async def list_suppressions(session: SessionDep) -> list[SuppressionOut]:
    entries = await SuppressionRepository(session).list_all()
    return [SuppressionOut.of(entry) for entry in entries]


@api.post(
    "/suppressions",
    response_model=SuppressionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
    tags=["suppressions"],
)
async def create_suppression(payload: SuppressionCreate, session: SessionDep) -> SuppressionOut:
    entry = await SuppressionRepository(session).add(payload.kind, payload.value, payload.reason)
    await session.commit()
    return SuppressionOut.of(entry)


@api.delete(
    "/suppressions/{suppression_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
    tags=["suppressions"],
)
async def delete_suppression(suppression_id: int, session: SessionDep) -> None:
    removed = await SuppressionRepository(session).remove(suppression_id)
    await session.commit()
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "suppression not found")


@api.get("/jobs", response_model=Page[JobOut], tags=["jobs"])
async def list_jobs(
    session: SessionDep,
    limit: LimitDep,
    cursor: Annotated[int | None, Query(description="Jobs with an id below this.")] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    source: str | None = None,
) -> Page[JobOut]:
    rows = await JobRepository(session).page(
        limit=limit, before_id=cursor, status=job_status, source=source
    )
    items = [JobOut.of(job, name, result) for job, name, result in rows]
    return Page(
        items=items,
        limit=limit,
        next_cursor=items[-1].id if len(items) == limit else None,
    )


@api.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
async def get_job(job_id: int, session: SessionDep) -> JobOut:
    row = await JobRepository(session).detail(job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobOut.of(*row)


@api.post(
    "/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
    tags=["jobs"],
)
async def create_job(
    payload: JobCreate, session: SessionDep, config: ConfigDep, response: Response
) -> JobOut:
    try:
        job = await enqueue(session, config, payload.source)
    except KeyError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"unknown source: {payload.source}"
        ) from exc
    await session.commit()
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return JobOut.of(job, payload.source, None)


@api.get("/sources", response_model=list[SourceOut], tags=["sources"])
async def list_sources(session: SessionDep, config: ConfigDep) -> list[SourceOut]:
    stored = {source.name: source for source in await SourceRepository(session).list_all()}
    return [
        SourceOut.of(stored[item.name])
        if item.name in stored
        else SourceOut(name=item.name, type=item.type, priority=item.priority, enabled=item.enabled)
        for item in config.sources
    ]


@api.get("/export", tags=["export"])
async def export(
    filters: FilterDep,
    factory: FactoryDep,
    export_format: Annotated[str, Query(alias="format")] = "csv",
) -> StreamingResponse:
    if export_format not in FORMATS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"format must be one of: {', '.join(FORMATS)}"
        )
    return StreamingResponse(
        _stream(factory, export_format, filters),
        media_type=CONTENT_TYPES[export_format],
        headers={"Content-Disposition": f'attachment; filename="leads.{export_format}"'},
    )


async def _stream(
    factory: async_sessionmaker[AsyncSession], export_format: str, filters: LeadFilter
) -> AsyncIterator[str]:
    # its own session: the response body outlives the request handler
    async with factory() as session:
        async for chunk in export_leads(session, export_format, filters):
            yield chunk


router.include_router(api)
