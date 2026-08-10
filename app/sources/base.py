from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config.models import SourceConfig
from app.domain.models import RawRecord


class SourceError(Exception):
    """Unusable source: bad configuration, missing input, unreachable endpoint."""


@dataclass(frozen=True, slots=True)
class RecordError:
    message: str
    raw: Mapping[str, Any] = field(default_factory=dict)


CollectedItem = RawRecord | RecordError


class Source(Protocol):
    config: SourceConfig

    @property
    def name(self) -> str: ...

    def collect(self) -> Iterator[CollectedItem]: ...
