import asyncio
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from urllib.parse import urljoin, urlsplit

import httpx

from app.fetch.errors import (
    FetchError,
    HttpStatusError,
    ResponseTooLarge,
    RobotsDisallowed,
    TooManyRedirects,
)
from app.fetch.limits import DomainThrottle
from app.fetch.policy import FetchPolicy
from app.fetch.robots import RobotsCache
from app.fetch.urls import Resolver, ensure_safe_url, system_resolver
from app.telemetry import get_logger

logger = get_logger(__name__)

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class FetchResponse:
    url: str
    status_code: int
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self.resolver = resolver
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.policy.timeout, connect=self.policy.connect_timeout),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=self.policy.max_concurrency),
            headers={"User-Agent": self.policy.user_agent},
        )
        self._throttle = DomainThrottle(self.policy.min_interval)
        self._semaphore = asyncio.Semaphore(self.policy.max_concurrency)
        self._robots = RobotsCache(self.policy, self._fetch_robots)

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get(self, url: str, headers: Mapping[str, str] | None = None) -> FetchResponse:
        target = await ensure_safe_url(url, self.policy, self.resolver)
        crawl_delay = await self._check_robots(target)

        async with self._semaphore:
            return await self._get_with_redirects(target, headers, crawl_delay)

    async def _check_robots(self, url: str) -> float | None:
        if not self.policy.respect_robots:
            return None
        rules = await self._robots.rules_for(url)
        if not rules.allows(url, self.policy.user_agent):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        return rules.crawl_delay(self.policy.user_agent)

    async def _get_with_redirects(
        self, url: str, headers: Mapping[str, str] | None, crawl_delay: float | None
    ) -> FetchResponse:
        seen = 0
        current = url
        while True:
            response = await self._request(current, headers, crawl_delay)
            if response.status_code not in REDIRECT_STATUSES:
                return response

            location = response.headers.get("location")
            if not location:
                return response

            seen += 1
            if seen > self.policy.max_redirects:
                raise TooManyRedirects(
                    f"more than {self.policy.max_redirects} redirects from {url}"
                )

            # every hop is re-validated: a safe url can redirect to an unsafe one
            current = await ensure_safe_url(urljoin(current, location), self.policy, self.resolver)
            crawl_delay = await self._check_robots(current)

    async def _request(
        self, url: str, headers: Mapping[str, str] | None, crawl_delay: float | None
    ) -> FetchResponse:
        last: Exception | None = None
        for attempt in range(self.policy.retries + 1):
            await self._throttle.wait(_host(url), crawl_delay)
            try:
                response = await self._read(url, headers)
            except (httpx.TransportError, httpx.ProtocolError) as exc:
                last = exc
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                last = HttpStatusError(response.status_code, url)

            if attempt < self.policy.retries:
                await asyncio.sleep(self._backoff(attempt))
                logger.warning("retrying request", url=url, reason=str(last))

        raise FetchError(f"giving up on {url}: {last}") from last

    async def _read(self, url: str, headers: Mapping[str, str] | None) -> FetchResponse:
        async with self._client.stream("GET", url, headers=dict(headers or {})) as response:
            declared = response.headers.get("content-length")
            if declared and int(declared) > self.policy.max_response_bytes:
                raise ResponseTooLarge(f"{url} declares {declared} bytes")

            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > self.policy.max_response_bytes:
                    # abort mid-stream rather than buffer the whole body
                    raise ResponseTooLarge(f"{url} exceeded {self.policy.max_response_bytes} bytes")
            return FetchResponse(
                url=str(response.url),
                status_code=response.status_code,
                content=bytes(chunks),
                headers=dict(response.headers),
            )

    async def _fetch_robots(self, url: str) -> tuple[int, str]:
        await self._throttle.wait(_host(url))
        response = await self._read(url, None)
        return response.status_code, response.text

    def _backoff(self, attempt: int) -> float:
        delay = min(self.policy.backoff_base * 2**attempt, self.policy.backoff_max)
        return float(delay * (0.5 + 0.5 * random.random()))


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""
