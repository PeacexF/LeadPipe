import csv
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config.models import SourceConfig
from app.domain.models import RawRecord, SourceRef
from app.sources.base import CollectedItem, RecordError, SourceError
from app.sources.registry import register


class CsvOptions(BaseModel):
    path: Path
    delimiter: str = ","
    encoding: str = "utf-8"
    external_id_field: str | None = None
    source_url_field: str | None = None


class CsvSource:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        try:
            self.options = CsvOptions.model_validate(config.options)
        except ValueError as exc:
            raise SourceError(f"source '{config.name}': {exc}") from exc

    @property
    def name(self) -> str:
        return self.config.name

    async def collect(self) -> AsyncIterator[CollectedItem]:
        path = self.options.path
        if not path.is_file():
            raise SourceError(f"source '{self.name}': file not found: {path}")

        collected_at = datetime.now(UTC)
        with path.open(encoding=self.options.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.options.delimiter)
            missing = set(self.config.mapping.values()) - set(reader.fieldnames or [])
            if missing:
                raise SourceError(
                    f"source '{self.name}': columns not in file: {', '.join(sorted(missing))}"
                )
            for row in reader:
                yield self._to_record(row, collected_at)

    async def aclose(self) -> None:
        return None

    def _to_record(self, row: dict[str, Any], collected_at: datetime) -> CollectedItem:
        if None in row:
            return RecordError("row has more columns than the header", _printable(row))
        try:
            fields = {
                target: _clean(row.get(column)) for target, column in self.config.mapping.items()
            }
            if self.options.external_id_field:
                fields["external_id"] = _clean(row.get(self.options.external_id_field))
            source_url = (
                _clean(row.get(self.options.source_url_field))
                if self.options.source_url_field
                else None
            )
            return RawRecord(
                source=SourceRef(name=self.name, url=source_url),
                fields=fields,
                raw=_printable(row),
                collected_at=collected_at,
            )
        except Exception as exc:  # one bad row must not end the collection
            return RecordError(str(exc), _printable(row))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _printable(row: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items() if key is not None}


register("csv")(CsvSource)
