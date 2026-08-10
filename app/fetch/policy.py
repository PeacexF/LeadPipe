from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from app import __version__


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    timeout: float = 10.0
    connect_timeout: float = 5.0
    max_response_bytes: int = 5_000_000
    max_redirects: int = 5
    retries: int = 2
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    requests_per_second: float = 1.0
    max_concurrency: int = 4
    respect_robots: bool = True
    robots_ttl: float = 3600.0
    # only for self-hosted or fixture endpoints; keeps SSRF protection on by default
    allow_private_hosts: bool = False
    contact: str | None = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> FetchPolicy:
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in options.items() if key in known})

    @property
    def user_agent(self) -> str:
        agent = f"LeadPipe/{__version__}"
        return f"{agent} (+{self.contact})" if self.contact else agent

    @property
    def min_interval(self) -> float:
        return 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0
