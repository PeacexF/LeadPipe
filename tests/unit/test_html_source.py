from pathlib import Path
from typing import Any

import httpx
import pytest
from bs4 import BeautifulSoup

from app.config.models import SourceConfig
from app.domain.models import RawRecord
from app.fetch import Fetcher, FetchPolicy
from app.sources import RecordError, SourceError, build_source
from app.sources.html_source import extract

LISTING = """
<ul class="listing">
  <li class="company">
    <h2 class="company-name">   Example   Oy   </h2>
    <a class="profile" href="companies/example.html">Profile</a>
    <span class="website"><a href="http://www.example.test/?utm_source=x">example.test</a></span>
    <span class="email"><a href="mailto:INFO@example.test">info</a></span>
    <span class="phone">+358 (0)40 123 4567</span>
    <span class="city">Helsinki</span>
  </li>
  <li class="company">
    <h2 class="company-name">Sparse Oy</h2>
    <span class="city">Turku</span>
  </li>
</ul>
<a class="next" href="page2.html">Next</a>
"""

DETAIL = """
<h1 class="company-name">Example Oy</h1>
<dd class="contact-name">Anna   Virtanen</dd>
<dd class="street">Mannerheimintie 12</dd>
<dd class="country">Finland</dd>
"""

PAGE_TWO = """
<ul class="listing">
  <li class="company"><h2 class="company-name">Second Page Oy</h2></li>
</ul>
"""

MAPPING = {
    "company_name": ".company-name",
    "website": ".website a@href",
    "email": ".email a@href",
    "phone": ".phone",
    "city": ".city",
}


def make_config(**extra: Any) -> SourceConfig:
    return SourceConfig.model_validate(
        {
            "name": "test_html",
            "type": "html",
            "url": "https://directory.test/index.html",
            "item_selector": "li.company",
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
    return source


def site(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("page2.html"):
        return httpx.Response(200, text=PAGE_TWO)
    if "companies/" in path:
        return httpx.Response(200, text=DETAIL)
    return httpx.Response(200, text=LISTING)


async def collect(source: Any) -> list[Any]:
    try:
        return [item async for item in source.collect()]
    finally:
        await source.aclose()


async def test_reads_listing_fields() -> None:
    items = await collect(build(site))
    record = items[0]

    assert isinstance(record, RawRecord)
    assert record.fields["company_name"] == "Example Oy"
    assert record.fields["website"] == "http://www.example.test/?utm_source=x"
    assert record.fields["email"] == "mailto:INFO@example.test"
    assert record.fields["phone"] == "+358 (0)40 123 4567"
    assert record.fields["city"] == "Helsinki"


async def test_missing_selectors_yield_none_not_errors() -> None:
    items = await collect(build(site))
    sparse = items[1]

    assert isinstance(sparse, RawRecord)
    assert sparse.fields["company_name"] == "Sparse Oy"
    assert sparse.fields["website"] is None
    assert sparse.fields["email"] is None
    assert sparse.fields["phone"] is None


async def test_detail_page_fields_are_merged_in() -> None:
    items = await collect(
        build(
            site,
            detail_link="a.profile@href",
            detail_mapping={
                "contact_name": ".contact-name",
                "address": ".street",
                "country": ".country",
            },
        )
    )
    record = items[0]

    assert isinstance(record, RawRecord)
    assert record.fields["contact_name"] == "Anna Virtanen"
    assert record.fields["address"] == "Mannerheimintie 12"
    assert record.fields["country"] == "Finland"
    assert record.source.url == "https://directory.test/companies/example.html"


async def test_items_without_a_detail_link_are_still_collected() -> None:
    items = await collect(build(site, detail_link="a.profile@href"))

    assert all(isinstance(item, RawRecord) for item in items)
    assert items[1].fields["company_name"] == "Sparse Oy"  # type: ignore[union-attr]


async def test_pagination_follows_the_next_link() -> None:
    items = await collect(build(site, next_selector="a.next"))
    names = [item.fields["company_name"] for item in items if isinstance(item, RawRecord)]
    assert names == ["Example Oy", "Sparse Oy", "Second Page Oy"]


async def test_max_items_stops_collection() -> None:
    items = await collect(build(site, next_selector="a.next", max_items=2))
    assert len(items) == 2


async def test_blocked_detail_page_costs_one_record_not_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /companies/\n")
        return site(request)

    fetcher = Fetcher(
        policy=FetchPolicy(requests_per_second=0, retries=0),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["93.184.216.34"],
    )
    source = build_source(make_config(detail_link="a.profile@href"))
    source.fetcher = fetcher  # type: ignore[attr-defined]

    items = await collect(source)

    assert len(items) == 2
    assert isinstance(items[0], RecordError)
    assert "robots.txt disallows" in items[0].message
    assert isinstance(items[1], RawRecord)


async def test_broken_page_fails_the_source() -> None:
    with pytest.raises(SourceError, match="HTTP 500"):
        await collect(build(lambda request: httpx.Response(500, text="oops")))


async def test_malformed_markup_does_not_crash() -> None:
    broken = '<ul class="listing"><li class="company"><h2 class="company-name">Unclosed Oy'
    items = await collect(build(lambda request: httpx.Response(200, text=broken)))

    assert len(items) == 1
    assert isinstance(items[0], RawRecord)
    assert items[0].fields["company_name"] == "Unclosed Oy"


async def test_required_options_are_validated() -> None:
    with pytest.raises(SourceError):
        build_source(SourceConfig.model_validate({"name": "broken", "type": "html"}))


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (".company-name", "Example Oy"),
        (".website a@href", "http://example.test"),
        ("@class", "company"),
        (".missing", None),
        (".missing@href", None),
        (".company-name@href", None),
    ],
)
def test_extract(spec: str, expected: str | None) -> None:
    html = (
        '<li class="company"><h2 class="company-name">Example Oy</h2>'
        '<span class="website"><a href="http://example.test">site</a></span></li>'
    )
    node = BeautifulSoup(html, "lxml").select_one("li.company")
    assert node is not None
    assert extract(node, spec) == expected


def test_shipped_fixture_site_parses() -> None:
    root = Path("examples/data/directory")
    listing = BeautifulSoup((root / "index.html").read_text(), "lxml")

    assert len(listing.select("li.company")) == 5
    assert listing.select_one("a.next") is not None
    assert len(BeautifulSoup((root / "page2.html").read_text(), "lxml").select("li.company")) == 3
