import asyncio
import time
from collections.abc import Callable


class DomainThrottle:
    # One request per host per interval, awaited rather than dropped

    def __init__(self, min_interval: float, clock: Callable[[], float] | None = None) -> None:
        self.min_interval = min_interval
        self.clock = clock or time.monotonic
        self._next_allowed: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, min_interval: float | None = None) -> float:
        interval = max(self.min_interval, min_interval or 0.0)
        if interval <= 0:
            return 0.0

        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self.clock()
            earliest = self._next_allowed.get(host, 0.0)
            delay = max(0.0, earliest - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_allowed[host] = self.clock() + interval
            return delay
