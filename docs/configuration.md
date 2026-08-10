# Configuration

LeadPipe has two layers of configuration, and they answer different questions.

| Layer | File | Answers | Changes when |
| --- | --- | --- | --- |
| Sources | YAML, `CONFIG_PATH` | *what* to collect | you add or tune a source |
| Runtime | environment / `.env` | *where* it runs | you deploy it somewhere else |

No source is compiled into the application. Adding a directory is a YAML edit, unless it
needs a new *type* of adapter — see [adding a source](adding-a-source.md).

## Source configuration

```yaml
defaults:
  region: FI          # region hint for parsing national phone numbers

sources:
  - name: example_csv
    type: csv
    enabled: true
    priority: 0
    path: ./examples/data/companies.csv
    external_id_field: id
    mapping:
      company_name: name
      email: email
      city: city
      country: country
```

### Keys every source accepts

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | string | required | Unique; identifies the source everywhere — jobs, provenance, filters |
| `type` | string | required | Registered adapter type: `csv`, `api`, `html` |
| `enabled` | bool | `true` | Disabled sources are skipped by `collect` and never scheduled |
| `priority` | int | `0` | Higher wins when two sources disagree about a field |
| `region` | string | `defaults.region` | ISO country code used to parse national phone numbers |
| `mapping` | map | `{}` | `lead_field: source_field` |
| `schedule` | object | none | See [scheduling](#scheduling) |

Anything else is passed through to the adapter, which validates the keys it knows. Keys no
adapter recognises are ignored, so check a new source with `leadpipe sources` and a first
run rather than assuming a typo would have been reported.

### Mapping

Keys are lead fields, values are source fields. Recognised lead fields:

`company_name`, `contact_name`, `website`, `email`, `phone`, `address`, `city`, `country`

Unmapped fields stay empty; the raw payload is stored regardless, so nothing is lost by
mapping only part of a source.

### `csv`

| Key | Default | Meaning |
| --- | --- | --- |
| `path` | required | File path, relative to the working directory |
| `delimiter` | `,` | Single character |
| `encoding` | `utf-8` | File encoding |
| `external_id_field` | none | Column holding the source's own identifier |
| `source_url_field` | none | Column holding the record's public URL |

Mapping values are column names. A column named in `mapping` but absent from the header is
a source error — the run fails rather than silently collecting empty fields.

### `api`

| Key | Default | Meaning |
| --- | --- | --- |
| `url` | required | First page |
| `headers` | `{}` | Extra request headers |
| `items_path` | none | Dotted path to the list of items (`data`, `result.items`) |
| `next_path` | none | Dotted path to the next page URL, absolute or relative |
| `page_param` | none | Query parameter to increment when the payload has no next link |
| `start_page` | `1` | First value for `page_param` |
| `max_pages` | `20` | Hard stop; also guards against pagination loops |
| `external_id_field` | none | Field holding the source's own identifier |
| `source_url_field` | none | Field holding the record's public URL |

Mapping values are dotted paths into each item: `contact.email`, `address.city`.

### `html`

| Key | Default | Meaning |
| --- | --- | --- |
| `url` | required | First listing page |
| `item_selector` | required | CSS selector for one result |
| `detail_link` | none | `selector@attribute` pointing at a per-company page |
| `detail_mapping` | `{}` | Mapping applied to the detail page |
| `next_selector` | none | CSS selector for the next-page link |
| `max_pages` | `20` | Hard stop |
| `max_items` | none | Stop after this many records |
| `headers` | `{}` | Extra request headers |
| `parser` | `lxml` | BeautifulSoup parser |

Mapping values are CSS selectors, optionally with `@attribute`:

```yaml
mapping:
  company_name: ".company-name"
  website: ".website a@href"
  email: ".email a@href"      # mailto: is stripped during normalization
```

Detail pages are only fetched when `detail_link` is set, and each one is subject to the
same robots and rate limits as the listing.

### Fetch policy

`api` and `html` sources accept these alongside their own keys.

| Key | Default | Meaning |
| --- | --- | --- |
| `requests_per_second` | `1.0` | Per-domain throttle |
| `max_concurrency` | `4` | Parallel requests |
| `timeout` | `10.0` | Read timeout, seconds |
| `connect_timeout` | `5.0` | Connect timeout, seconds |
| `retries` | `2` | Retries on 429/5xx and connection errors |
| `backoff_base` / `backoff_max` | `0.5` / `8.0` | Retry backoff, seconds |
| `max_response_bytes` | `5_000_000` | Responses above this are rejected, not truncated |
| `max_redirects` | `5` | Each hop is re-checked against the safety rules |
| `respect_robots` | `true` | See [legal](legal.md) |
| `robots_ttl` | `3600.0` | How long a `robots.txt` is cached |
| `allow_private_hosts` | `false` | Permits private and loopback addresses |
| `contact` | none | Appended to the User-Agent as `(+contact)` |

`allow_private_hosts` exists for self-hosted endpoints and the bundled fixtures. Leave it
off for anything on the public internet: it is what stops a configured URL from reaching
`169.254.169.254` or an internal service.

Setting `contact` to an email or URL is good manners and makes you contactable if a site
operator objects.

## Scheduling

```yaml
schedule:
  enabled: true
  cron: "30 6 * * 1"
  timezone: Europe/Helsinki
```

Standard five-field POSIX cron: minute, hour, day-of-month, month, day-of-week. Day-of-week
counts **Sunday as 0**, and `7` is also Sunday, so the example above runs on Mondays.
Names (`mon`, `sun`) work too and are unambiguous.

Invalid expressions fail when the configuration loads, not at the first tick that never
comes.

A schedule only queues a job; the worker runs it. If the previous run for that source is
still pending or running, the tick is skipped rather than piling up.

## Environment variables

`.env` is the single source of truth for runtime settings; `.env.example` lists them all.

| Variable | Default | Used by |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://leadpipe:leadpipe@localhost:5432/leadpipe` | everything |
| `CONFIG_PATH` | `examples/configs/csv.yaml` | API, CLI, worker |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | `leadpipe serve` |
| `LEADPIPE_API_KEY` | unset | API writes; unset means no authentication |
| `CORS_ORIGINS` | empty | API; comma-separated, empty disables CORS |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | `50` / `200` | API pagination |
| `RETENTION_DAYS` | unset | `leadpipe purge` |
| `LOG_LEVEL` | `INFO` | everything |
| `LOG_FORMAT` | `console` | `console` for humans, `json` for log shippers |
| `TEST_DATABASE_URL` | unset | integration tests; unset starts a throwaway container |

The API and the CLI resolve `CONFIG_PATH` the same way, so a source the API accepts is a
source the worker can run.

## Interpolation

Any string in the YAML may reference the environment:

```yaml
url: ${DIRECTORY_URL}/companies
headers:
  Authorization: Bearer ${DIRECTORY_TOKEN}
timeout: ${DIRECTORY_TIMEOUT:-10}
```

`${VAR}` is required — loading fails with a clear error if it is unset. `${VAR:-default}`
falls back. Credentials therefore never need to be committed.

## Validation

Configuration is validated when it loads, and the process refuses to start otherwise.
Duplicate source names, unknown adapter types, unparseable cron expressions and malformed
adapter options are all startup errors.

```bash
uv run leadpipe sources          # what is configured, and how
uv run leadpipe sources -c examples/configs/all.yaml
```
