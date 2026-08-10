# Adding a source

Most new sources need no code: if the data is a CSV file, a JSON API or an HTML listing,
add YAML and you are done — see [configuration](configuration.md).

Write an adapter when the *shape* of the source is new: a different file format, a paginated
protocol the API adapter cannot express, a vendor SDK.

## The contract

An adapter satisfies this protocol (`app/sources/base.py`):

```python
class Source(Protocol):
    config: SourceConfig

    @property
    def name(self) -> str: ...

    def collect(self) -> AsyncIterator[CollectedItem]: ...

    async def aclose(self) -> None: ...
```

It is a `Protocol`, not a base class — there is nothing to inherit, and your adapter is
whatever you say it is as long as it yields the right things.

`collect()` yields `CollectedItem`, which is either:

| Yielded | Meaning | Effect on the run |
| --- | --- | --- |
| `RawRecord` | one company | normalized, validated, deduplicated, stored |
| `RecordError` | this item is unusable | counted in `errors`, logged with its reason, run continues |

Raising `SourceError` means the *source* is unusable — file missing, endpoint down, config
wrong. That fails the job. The distinction matters: one malformed row must never cost you
the other nineteen.

A `RawRecord` carries four things:

```python
RawRecord(
    source=SourceRef(name=self.name, url=public_url),  # url may be None
    fields={"company_name": "...", "email": "..."},  # already mapped to lead fields
    raw={...},  # the untouched original
    collected_at=collected_at,
)
```

`fields` uses lead field names, translated through `self.config.mapping`. `raw` is stored
verbatim in `source_records.raw`, which is what makes the pipeline re-runnable against
historical data. Do not normalize anything yourself — that is the next stage's job, and
doing it here means your source normalizes differently from every other source.

## A worked example: JSON Lines

One JSON object per line. Roughly a hundred lines of adapter.

### 1. Options

Type-specific config keys are validated by a Pydantic model, so a bad config fails at
startup with a useful message:

```python
# app/sources/jsonl_source.py
from pydantic import BaseModel


class JsonlOptions(BaseModel):
    path: Path
    encoding: str = "utf-8"
    external_id_field: str | None = None
```

### 2. The adapter

```python
class JsonlSource:
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        try:
            self.options = JsonlOptions.model_validate(config.options)
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
        with path.open(encoding=self.options.encoding) as handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    yield RecordError(f"line {number}: {exc}", {"line": line[:200]})
                    continue
                yield self._to_record(item, collected_at)

    async def aclose(self) -> None:
        return None

    def _to_record(self, item: Any, collected_at: datetime) -> CollectedItem:
        if not isinstance(item, dict):
            return RecordError("line is not an object", {"value": repr(item)[:200]})

        fields = {target: _text(item.get(source)) for target, source in self.config.mapping.items()}
        if self.options.external_id_field:
            fields["external_id"] = _text(item.get(self.options.external_id_field))

        return RawRecord(
            source=SourceRef(name=self.name),
            fields=fields,
            raw=item,
            collected_at=collected_at,
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None
```

Note what is **not** there: no lowercasing of emails, no phone parsing, no deduplication
awareness, no database. An adapter reads and maps. Nothing else.

### 3. Register it

```python
register("jsonl")(JsonlSource)
```

The type name is what `type:` means in YAML. Import the module in `app/sources/__init__.py`
so the registration runs:

```python
from app.sources.jsonl_source import JsonlSource
```

Without that import the type is not registered, and the error says so:

```text
unknown source type 'jsonl' (registered: api, csv, html)
```

### 4. Configure it

```yaml
sources:
  - name: partner_feed
    type: jsonl
    priority: 20
    path: ./data/partners.jsonl
    external_id_field: id
    mapping:
      company_name: name
      email: email
      city: city
      country: country
```

```bash
uv run leadpipe sources -c config.yaml
uv run leadpipe collect -c config.yaml --source partner_feed
```

### 5. Test it

Adapters are tested without a database — build one from a `SourceConfig` and drain
`collect()`:

```python
async def test_yields_a_record_per_line(tmp_path: Path) -> None:
    file = tmp_path / "partners.jsonl"
    file.write_text('{"id": "1", "name": "Nordic Clean Oy"}\n')

    source = JsonlSource(
        SourceConfig(
            name="partners",
            type="jsonl",
            path=str(file),
            external_id_field="id",
            mapping={"company_name": "name"},
        )
    )

    records = [item async for item in source.collect()]

    assert len(records) == 1
    assert records[0].fields["company_name"] == "Nordic Clean Oy"
```

Cover at least: a good record, a malformed one (a `RecordError`, not an exception), a
missing file (a `SourceError`), and an unmapped field staying empty.

## If your source makes HTTP requests

Do not reach for `httpx` directly. Build a `Fetcher` from the source options and you
inherit, for free:

```python
self.fetcher = fetcher or Fetcher(FetchPolicy.from_options(config.options))
```

- `robots.txt` checked and cached per host
- per-domain rate limiting and a concurrency cap
- retries with backoff on 429 and 5xx
- response size limits, redirect limits
- refusal to connect to private or loopback addresses unless explicitly allowed
- a User-Agent that identifies LeadPipe and your contact address

Accept an optional `fetcher` argument like `ApiSource` and `HtmlSource` do — it is what
lets tests inject an `httpx.MockTransport` and keeps the suite off the network entirely.

Close what you own:

```python
async def aclose(self) -> None:
    if self._owns_fetcher:
        await self.fetcher.aclose()
```

## Checklist

- [ ] Options model validates type-specific keys
- [ ] `SourceError` for an unusable source, `RecordError` for an unusable item
- [ ] `raw` holds the untouched payload
- [ ] `source_url` set when the record has a public page
- [ ] No normalization inside the adapter
- [ ] `register("type")` called, module imported in `app/sources/__init__.py`
- [ ] Tests cover a good record, a bad record and a missing source
- [ ] `make check` passes
