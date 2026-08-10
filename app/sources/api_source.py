import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel

from app.config.models import SourceConfig
from app.domain.models import RawRecord, SourceRef
from app.fetch import Fetcher, FetchError, FetchPolicy
from app.sources.base import CollectedItem, RecordError, SourceError
from app.sources.registry import register


class ApiOptions(BaseModel):
    url: str
    headers: dict[str, str] = {}
    items_path: str | None = None
    next_path: str | None = None
    page_param: str | None = None
    start_page: int = 1
    max_pages: int = 20
    external_id_field: str | None = None
    source_url_field: str | None = None


class ApiSource:
    def __init__(self, config: SourceConfig, fetcher: Fetcher | None = None) -> None:
        self.config = config
        try:
            self.options = ApiOptions.model_validate(config.options)
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
        url: str | None = self._first_url()
        seen: set[str] = set()

        for _ in range(self.options.max_pages):
            if url is None or url in seen:
                return
            seen.add(url)

            payload = await self._load(url)
            items = self._items(payload, url)
            for item in items:
                yield self._to_record(item, url, collected_at)

            url = self._next_url(payload, url, len(items))

    def _first_url(self) -> str:
        if self.options.page_param is None:
            return self.options.url
        return _with_param(self.options.url, self.options.page_param, self.options.start_page)

    async def _load(self, url: str) -> Any:
        try:
            response = await self.fetcher.get(url, headers=self.options.headers)
        except FetchError as exc:
            raise SourceError(f"source '{self.name}': {exc}") from exc

        if response.status_code >= 400:
            raise SourceError(f"source '{self.name}': HTTP {response.status_code} for {url}")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise SourceError(f"source '{self.name}': invalid JSON from {url}: {exc}") from exc

    def _items(self, payload: Any, url: str) -> list[Any]:
        items = dig(payload, self.options.items_path) if self.options.items_path else payload
        if items is None:
            return []
        if not isinstance(items, list):
            raise SourceError(
                f"source '{self.name}': expected a list at "
                f"'{self.options.items_path or '(root)'}' in {url}"
            )
        return items

    def _next_url(self, payload: Any, current: str, count: int) -> str | None:
        if self.options.next_path:
            follow = dig(payload, self.options.next_path)
            return urljoin(current, str(follow)) if follow else None
        if self.options.page_param and count:
            page = _param_value(current, self.options.page_param, self.options.start_page)
            return _with_param(current, self.options.page_param, page + 1)
        return None

    def _to_record(self, item: Any, url: str, collected_at: datetime) -> CollectedItem:
        if not isinstance(item, Mapping):
            return RecordError("item is not an object", {"value": repr(item)[:200]})
        try:
            fields = {
                target: _text(dig(item, path)) for target, path in self.config.mapping.items()
            }
            if self.options.external_id_field:
                fields["external_id"] = _text(dig(item, self.options.external_id_field))
            source_url = (
                _text(dig(item, self.options.source_url_field))
                if self.options.source_url_field
                else url
            )
            return RawRecord(
                source=SourceRef(name=self.name, url=source_url),
                fields=fields,
                raw=dict(item),
                collected_at=collected_at,
            )
        except Exception as exc:
            return RecordError(str(exc), {"value": repr(item)[:200]})


def dig(payload: Any, path: str) -> Any:
    # Walk a dotted path, so nested API shapes can be mapped from config
    value = payload
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, dict | list):
        return None
    text = str(value).strip()
    return text or None


def _with_param(url: str, param: str, value: int) -> str:
    parts = urlsplit(url)
    query = [(key, item) for key, item in parse_qsl(parts.query) if key != param]
    query.append((param, str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _param_value(url: str, param: str, default: int) -> int:
    for key, value in parse_qsl(urlsplit(url).query):
        if key == param:
            try:
                return int(value)
            except ValueError:
                return default
    return default


register("api")(ApiSource)
