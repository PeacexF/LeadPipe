import csv
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.main import create_app
from app.config import load_config
from app.db.models import JobStatus
from app.pipeline import run_collection
from app.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CONFIG = load_config(Path("examples/configs/csv.yaml"))


def build_client(factory: async_sessionmaker[AsyncSession], **overrides: object) -> AsyncClient:
    settings = Settings(database_url="postgresql+asyncpg://unused/unused", **overrides)  # type: ignore[arg-type]
    app = create_app(settings=settings, config=CONFIG, session_factory=factory)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(loop_scope="session")
async def client(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async with build_client(factory) as instance:
        yield instance


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await run_collection(session, CONFIG, "example_csv")
        await session.commit()


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_list_leads_paginates(client: AsyncClient, seeded: None) -> None:
    first = await client.get("/api/leads", params={"limit": 10})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 10
    assert body["next_cursor"] is not None

    second = await client.get("/api/leads", params={"limit": 10, "cursor": body["next_cursor"]})
    page = second.json()
    assert len(page["items"]) == 5
    assert page["next_cursor"] is None

    ids = [item["id"] for item in body["items"] + page["items"]]
    assert ids == sorted(ids)
    assert len(set(ids)) == 15


async def test_limit_is_capped(factory: async_sessionmaker[AsyncSession], seeded: None) -> None:
    async with build_client(factory, max_page_size=3) as client:
        response = await client.get("/api/leads", params={"limit": 500})
        assert response.json()["limit"] == 3
        assert len(response.json()["items"]) == 3


async def test_invalid_limit_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/leads", params={"limit": 0})).status_code == 422


async def test_lead_filters(client: AsyncClient, seeded: None) -> None:
    helsinki = await client.get("/api/leads", params={"city": "Helsinki", "limit": 100})
    assert {item["city"] for item in helsinki.json()["items"]} == {"Helsinki"}

    invalid = await client.get("/api/leads", params={"validation_status": "invalid", "limit": 100})
    assert {item["validation_status"] for item in invalid.json()["items"]} == {"invalid"}

    unknown_source = await client.get("/api/leads", params={"source": "nope"})
    assert unknown_source.json()["items"] == []


async def test_lead_detail_exposes_provenance(client: AsyncClient, seeded: None) -> None:
    listing = await client.get("/api/leads", params={"limit": 100})
    lead = next(
        item for item in listing.json()["items"] if item["email"] == "info@nordicclean.test"
    )

    response = await client.get(f"/api/leads/{lead['id']}")
    assert response.status_code == 200
    body = response.json()

    assert body["company_name"] == "Nordic Clean Oy"
    assert body["sources"] == ["example_csv"]
    assert len(body["provenance"]) >= 3
    assert {item["rule"] for item in body["provenance"]} <= {
        "initial",
        "email",
        "website",
        "phone",
        "name_location",
    }
    assert "metadata" in body


async def test_missing_lead_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/leads/999999")).status_code == 404


async def test_create_job_enqueues_without_running_it(client: AsyncClient) -> None:
    response = await client.post("/api/jobs", json={"source": "example_csv"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == JobStatus.PENDING.value
    assert response.headers["Location"] == f"/api/jobs/{body['id']}"

    fetched = await client.get(f"/api/jobs/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["source"] == "example_csv"
    assert fetched.json()["result"] is None


async def test_create_job_rejects_unknown_source(client: AsyncClient) -> None:
    response = await client.post("/api/jobs", json={"source": "carrier-pigeon"})
    assert response.status_code == 400
    assert "unknown source" in response.json()["detail"]


async def test_create_job_validates_payload(client: AsyncClient) -> None:
    assert (await client.post("/api/jobs", json={})).status_code == 422
    assert (await client.post("/api/jobs", json={"source": ""})).status_code == 422


async def test_api_key_guards_mutating_endpoints(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with build_client(factory, leadpipe_api_key="s3cret") as client:
        assert (await client.post("/api/jobs", json={"source": "example_csv"})).status_code == 401
        assert (
            await client.post(
                "/api/jobs", json={"source": "example_csv"}, headers={"X-API-Key": "wrong"}
            )
        ).status_code == 401

        allowed = await client.post(
            "/api/jobs", json={"source": "example_csv"}, headers={"X-API-Key": "s3cret"}
        )
        assert allowed.status_code == 202

        # reads stay open
        assert (await client.get("/api/leads")).status_code == 200


async def test_jobs_listing_is_newest_first(client: AsyncClient) -> None:
    for _ in range(3):
        await client.post("/api/jobs", json={"source": "example_csv"})

    response = await client.get("/api/jobs", params={"limit": 100})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == sorted(ids, reverse=True)

    filtered = await client.get("/api/jobs", params={"status": "pending", "source": "example_csv"})
    assert filtered.status_code == 200
    assert all(item["status"] == "pending" for item in filtered.json()["items"])


async def test_missing_job_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/jobs/999999")).status_code == 404


async def test_sources_listing(client: AsyncClient) -> None:
    response = await client.get("/api/sources")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["example_csv"]
    assert response.json()[0]["type"] == "csv"


async def test_csv_export_streams(client: AsyncClient, seeded: None) -> None:
    response = await client.get("/api/export", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 15
    assert rows[0]["sources"] == "example_csv"


async def test_json_export_and_filters(client: AsyncClient, seeded: None) -> None:
    response = await client.get("/api/export", params={"format": "json", "city": "Helsinki"})
    assert response.status_code == 200
    body = json.loads(response.text)
    assert body != []
    assert {item["city"] for item in body} == {"Helsinki"}


async def test_unknown_export_format_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/export", params={"format": "xlsx"})
    assert response.status_code == 400


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in ("/health", "/api/leads", "/api/leads/{lead_id}", "/api/jobs", "/api/export"):
        assert path in paths
