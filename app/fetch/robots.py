import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.fetch.policy import FetchPolicy

RobotsFetcher = Callable[[str], Awaitable[tuple[int, str]]]


@dataclass(frozen=True, slots=True)
class RobotsRules:
    parser: RobotFileParser | None
    allow_all: bool
    deny_all: bool
    fetched_at: float

    def allows(self, url: str, user_agent: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all or self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


class RobotsCache:
    def __init__(
        self,
        policy: FetchPolicy,
        fetcher: RobotsFetcher,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.policy = policy
        self.fetcher = fetcher
        self.clock = clock or time.monotonic
        self._cache: dict[str, RobotsRules] = {}

    async def rules_for(self, url: str) -> RobotsRules:
        origin = _origin(url)
        cached = self._cache.get(origin)
        if cached is not None and self.clock() - cached.fetched_at < self.policy.robots_ttl:
            return cached

        rules = await self._load(origin)
        self._cache[origin] = rules
        return rules

    async def _load(self, origin: str) -> RobotsRules:
        try:
            status, body = await self.fetcher(f"{origin}/robots.txt")
        except Exception:
            # unreachable is not the same as absent, so stay on the safe side
            return RobotsRules(None, allow_all=False, deny_all=True, fetched_at=self.clock())

        if status >= 500:
            return RobotsRules(None, allow_all=False, deny_all=True, fetched_at=self.clock())
        if status >= 400:
            return RobotsRules(None, allow_all=True, deny_all=False, fetched_at=self.clock())

        parser = RobotFileParser()
        parser.parse(body.splitlines())
        return RobotsRules(parser, allow_all=False, deny_all=False, fetched_at=self.clock())


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))
