import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config.models import SourceConfig
from app.domain.models import RawRecord
from app.fetch import Fetcher, FetchPolicy
from app.sources import RecordError, SourceError, build_source
from app.sources.api_source import dig

MAPPING = {
    "company_name": "name",
    "email": "contact.email",
    "phone": "contact.phone",
    "city": "address.city",
}

PAGE_ONE = {
    "meta": {"next": "page2.json"},
    "data": [
        {
            "id": "A-1",
            "name": "Example Oy",
            "contact": {"email": "contact@example.com", "phone": "+358401234567"},
            "address": {"city": "Helsinki"},
        }
    ],
}
PAGE_TWO = {"meta": {"next": None}, "data": [{"id": "A-2", "name": "Second Oy"}]}


def make_config(**extra: Any) -> SourceConfig:
    return SourceConfig.model_validate(
        {
            "name": "test_api",
            "type": "api",
            "url": "https://directory.test/page1.json",
            "items_path": "data",
            "mapping": MAPPING,
            **extra,
        }
    )


def build(handler: Any, **extra: Any) -> Any:
    fetcher = Fetcher(
        policy=FetchPolicy(requests_per_second=0, retries=0, respect_robots=False),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["93.184.216.34"],
    )
    source = build_source(make_config(**extra))
    source.fetcher = fetcher  # type: ignore[attr-defined]
    source._owns_fetcher = True  # type: ignore[attr-defined]
    return source


def json_response(payload: Any) -> httpx.Response:
    return httpx.Response(200, text=json.dumps(payload))


async def collect(source: Any) -> list[Any]:
    try:
        return [item async for item in source.collect()]
    finally:
        await source.aclose()


async def test_reads_and_maps_nested_fields() -> None:
    items = await collect(build(lambda request: json_response({"data": PAGE_ONE["data"]})))

    assert len(items) == 1
    record = items[0]
    assert isinstance(record, RawRecord)
    assert record.fields == {
        "company_name": "Example Oy",
        "email": "contact@example.com",
        "phone": "+358401234567",
        "city": "Helsinki",
    }
    assert record.raw["id"] == "A-1"
    assert record.source.url == "https://directory.test/page1.json"


async def test_external_id_is_carried() -> None:
    items = await collect(
        build(lambda request: json_response({"data": PAGE_ONE["data"]}), external_id_field="id")
    )
    assert isinstance(items[0], RawRecord)
    assert items[0].fields["external_id"] == "A-1"


async def test_follows_the_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(PAGE_TWO if request.url.path.endswith("page2.json") else PAGE_ONE)

    items = await collect(build(handler, next_path="meta.next"))
    names = [item.fields["company_name"] for item in items if isinstance(item, RawRecord)]
    assert names == ["Example Oy", "Second Oy"]


async def test_pagination_stops_at_max_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.path.removeprefix("/page").removesuffix(".json"))
        return json_response(
            {"meta": {"next": f"page{page + 1}.json"}, "data": [{"name": f"Company {page}"}]}
        )

    items = await collect(build(handler, next_path="meta.next", max_pages=3))
    assert len(items) == 3


async def test_a_self_referencing_next_link_does_not_loop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"meta": {"next": "page1.json"}, "data": [{"name": "Endless"}]})

    items = await collect(build(handler, next_path="meta.next", max_pages=100))
    assert len(items) == 1


async def test_page_param_pagination_stops_on_an_empty_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(dict(request.url.params).get("page", 1))
        rows = [{"name": f"Company {page}"}] if page <= 2 else []
        return json_response({"data": rows})

    items = await collect(build(handler, page_param="page"))
    names = [item.fields["company_name"] for item in items if isinstance(item, RawRecord)]
    assert names == ["Company 1", "Company 2"]


async def test_a_bad_item_is_reported_without_ending_collection() -> None:
    payload = {"data": [PAGE_ONE["data"][0], "not-an-object", {"name": "Third Oy"}]}
    items = await collect(build(lambda request: json_response(payload)))

    assert len(items) == 3
    assert isinstance(items[1], RecordError)
    assert sum(isinstance(item, RawRecord) for item in items) == 2


async def test_invalid_json_fails_the_source() -> None:
    with pytest.raises(SourceError, match="invalid JSON"):
        await collect(build(lambda request: httpx.Response(200, text="{oops")))


async def test_http_error_fails_the_source() -> None:
    with pytest.raises(SourceError, match="HTTP 404"):
        await collect(build(lambda request: httpx.Response(404, text="{}")))


async def test_wrong_shape_fails_the_source() -> None:
    with pytest.raises(SourceError, match="expected a list"):
        await collect(build(lambda request: json_response({"data": {"not": "a list"}})))


async def test_missing_items_path_yields_nothing() -> None:
    items = await collect(build(lambda request: json_response({"other": []})))
    assert items == []


async def test_url_is_required() -> None:
    config = SourceConfig.model_validate({"name": "broken", "type": "api"})
    with pytest.raises(SourceError):
        build_source(config)


async def test_robots_disallow_fails_the_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return json_response(PAGE_ONE)

    fetcher = Fetcher(
        policy=FetchPolicy(requests_per_second=0, retries=0),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["93.184.216.34"],
    )
    source = build_source(make_config())
    source.fetcher = fetcher  # type: ignore[attr-defined]

    with pytest.raises(SourceError, match=r"robots\.txt disallows"):
        await collect(source)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("contact.email", "a@example.com"),
        ("contact", {"email": "a@example.com"}),
        ("contact.missing", None),
        ("missing.deep", None),
        ("name", "Example"),
    ],
)
def test_dig(path: str, expected: Any) -> None:
    payload = {"name": "Example", "contact": {"email": "a@example.com"}}
    assert dig(payload, path) == expected


def test_shipped_fixture_files_are_valid_json() -> None:
    for name in ("companies_api.json", "companies_api_page2.json"):
        payload = json.loads(Path("examples/data", name).read_text())
        assert isinstance(payload["data"], list)
        assert payload["data"]
