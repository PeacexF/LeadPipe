import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

from app.config.models import SourceConfig
from app.domain.models import RawRecord, SourceRef
from app.fetch import Fetcher, FetchError, FetchPolicy
from app.sources.base import CollectedItem, RecordError, SourceError
from app.sources.registry import register

_WHITESPACE = re.compile(r"\s+")


class HtmlOptions(BaseModel):
    url: str
    item_selector: str
    detail_link: str | None = None
    detail_mapping: dict[str, str] = {}
    next_selector: str | None = None
    max_pages: int = 20
    max_items: int | None = None
    headers: dict[str, str] = {}
    parser: str = "lxml"


class HtmlSource:
    def __init__(self, config: SourceConfig, fetcher: Fetcher | None = None) -> None:
        self.config = config
        try:
            self.options = HtmlOptions.model_validate(config.options)
        except ValueError as exc:
            raise SourceError(f"source '{config.name}': {exc}") from exc
        self._owns_fetcher = fetcher is None
        self.fetcher = fetcher or Fetcher(FetchPolicy.from_options(config.options))

    @property
    def name(self) -> str:
        return self.config.name

    async def aclose(self) -> None:
        if self._owns_fetcher:
            await self.fetcher.aclose()

    async def collect(self) -> AsyncIterator[CollectedItem]:
        collected_at = datetime.now(UTC)
        url: str | None = self.options.url
        seen: set[str] = set()
        emitted = 0

        for _ in range(self.options.max_pages):
            if url is None or url in seen:
                return
            seen.add(url)

            soup = BeautifulSoup(await self._load(url), self.options.parser)
            for node in soup.select(self.options.item_selector):
                yield await self._to_record(node, url, collected_at)
                emitted += 1
                if self.options.max_items and emitted >= self.options.max_items:
                    return

            url = self._next_url(soup, url)

    async def _load(self, url: str) -> str:
        try:
            response = await self.fetcher.get(url, headers=self.options.headers)
        except FetchError as exc:
            raise SourceError(f"source '{self.name}': {exc}") from exc
        if response.status_code >= 400:
            raise SourceError(f"source '{self.name}': HTTP {response.status_code} for {url}")
        return response.text

    def _next_url(self, soup: BeautifulSoup, current: str) -> str | None:
        if not self.options.next_selector:
            return None
        link = soup.select_one(self.options.next_selector)
        href = link.get("href") if isinstance(link, Tag) else None
        return urljoin(current, str(href)) if href else None

    async def _to_record(self, node: Tag, url: str, collected_at: datetime) -> CollectedItem:
        try:
            fields = {
                target: extract(node, selector) for target, selector in self.config.mapping.items()
            }
            source_url = url
            raw: dict[str, Any] = {"listing_html": str(node)[:2000]}

            detail_url = self._detail_url(node, url)
            if detail_url is not None:
                try:
                    detail = BeautifulSoup(await self._load(detail_url), self.options.parser)
                except SourceError as exc:
                    # a blocked or broken detail page loses one record, not the run
                    return RecordError(str(exc), {"url": detail_url, **raw})
                for target, selector in self.options.detail_mapping.items():
                    value = extract(detail, selector)
                    if value is not None:
                        fields[target] = value
                source_url = detail_url
                raw["detail_url"] = detail_url

            return RawRecord(
                source=SourceRef(name=self.name, url=source_url),
                fields=fields,
                raw=raw,
                collected_at=collected_at,
            )
        except Exception as exc:  # malformed markup must not end the collection
            return RecordError(str(exc), {"listing_html": str(node)[:500]})

    def _detail_url(self, node: Tag, url: str) -> str | None:
        if not self.options.detail_link:
            return None
        href = extract(node, self.options.detail_link)
        return urljoin(url, href) if href else None


def extract(node: Tag | BeautifulSoup, spec: str) -> str | None:
    """`.selector` for text, `.selector@attr` for an attribute, `@attr` for this node."""
    selector, _, attribute = spec.rpartition("@")
    if not _:
        selector, attribute = spec, ""

    target: Tag | BeautifulSoup | None = node
    if selector:
        found = node.select_one(selector)
        target = found if isinstance(found, Tag) else None
    if target is None:
        return None

    if attribute:
        value = target.get(attribute) if isinstance(target, Tag) else None
        if isinstance(value, list):
            value = " ".join(value)
        return _clean(value)
    return _clean(target.get_text(" ", strip=True))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    # browsers collapse runs of whitespace, so extracted text should match what a reader sees
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


register("html")(HtmlSource)
