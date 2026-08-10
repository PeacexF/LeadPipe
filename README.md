# LeadPipe

A configurable Python service for collecting, normalizing, validating and deduplicating
publicly available business leads from multiple sources.

Built as a reusable automation template for small-business data collection workflows.

```text
Sources
   ↓
Collection
   ↓
Normalization
   ↓
Validation
   ↓
Deduplication
   ↓
PostgreSQL
   ↓
CSV / JSON / API
```

---

## The problem

A small business wants a list of potential B2B customers. The data exists across several
public directories, but every source spells things differently:

```text
Nordic Clean Oy          NORDIC CLEAN OY          Nordic Clean
www.nordicclean.test     https://nordicclean.test/    nordicclean.test
+358 40 123 4567         040-1234567                  (blank)
Finland                  FI                           Suomi
```

Three rows, one company. Multiply that across a few thousand records and manual cleanup
stops being viable.

LeadPipe collects from configured sources, normalizes the values into one schema,
validates what it can, works out which records describe the same company, and keeps a
full record of where every field came from.

---

## What it does

- **Collects** from configurable sources — no source is hardcoded.
- **Normalizes** company names, emails, URLs, phone numbers (to E.164) and countries
  (to ISO-3166 alpha-2).
- **Validates** with three outcomes — `valid`, `invalid`, `unknown` — so a *missing*
  email is never confused with a *broken* one. Bad records are flagged and kept, not
  silently dropped.
- **Deduplicates** using ordered rules, merging field by field with a documented
  precedence, and flags uncertain matches for review instead of guessing.
- **Preserves provenance** — every collected record is stored immutably, and you can
  always ask which source supplied which field.
- **Runs collections as background jobs** through a Postgres-backed queue, safe to run
  with several workers.
- **Exports** to CSV and JSON, streamed so table size does not become memory size.
- **Serves a REST API** for leads, jobs, sources and exports.

---

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
git clone https://github.com/PeacexF/LeadPipe && cd LeadPipe
cp .env.example .env

uv sync
docker compose up -d postgres
uv run alembic upgrade head

uv run leadpipe collect
```

That runs the bundled example source and prints:

```text
Source: example_csv
  Collected          20
  Valid              17
  Invalid             3
  Unknown             0
  Duplicates          5
  New leads          15
  Needs review        1
  Errors              0
```

Twenty rows in, fifteen leads out. Export them:

```bash
uv run leadpipe export --format csv --out leads.csv
uv run leadpipe export --format json --city Helsinki
```

### Through the API

```bash
uv run leadpipe serve          # http://localhost:8000/docs
uv run leadpipe worker         # in a second terminal
```

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"source":"example_csv"}'
```

```json
{ "id": 1, "source": "example_csv", "status": "pending", "attempts": 0 }
```

The API returns `202 Accepted` immediately — collection happens in the worker, never
inside the request. Poll it:

```bash
curl http://localhost:8000/api/jobs/1
```

```json
{
  "id": 1,
  "status": "completed",
  "result": {
    "collected": 20, "valid": 17, "invalid": 3,
    "duplicates": 5, "new_leads": 15, "errors": 0
  }
}
```

```bash
curl "http://localhost:8000/api/export?format=csv" -o leads.csv
```

---

## Seeing deduplication work

The bundled dataset is deliberately dirty — duplicate companies, mixed capitalization,
inconsistent URLs and phone formats, invalid emails, and near-miss names. Ask any lead
where it came from:

```bash
curl http://localhost:8000/api/leads/1
```

```text
Nordic Clean Oy | info@nordicclean.test | +358401234567

  rule=initial        conf=1.00  review=false  record=1
  rule=email          conf=1.00  review=false  record=2
  rule=website        conf=0.95  review=false  record=8
  rule=name_location  conf=0.80  review=true   record=16
```

Four source records. Three were merged automatically by three different rules. The
fourth — a company with a very similar name in the same city — was **not** merged; it was
flagged for review and kept as its own lead.

Re-running a collection is idempotent: records are keyed per source, so the same input
converges on the same leads rather than duplicating them.

---

## Configuration

Sources are configured, not coded:

```yaml
defaults:
  region: FI

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
      phone: phone
      city: city
      country: country
```

`priority` decides which source wins when two disagree about a field. Values support
`${ENV_VAR}` and `${ENV_VAR:-default}` interpolation, so credentials stay out of version
control.

Runtime settings come from the environment — see `.env.example`.

---

## API

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness |
| `GET` | `/api/leads` | Keyset pagination, filterable |
| `GET` | `/api/leads/{id}` | Includes full provenance |
| `GET` | `/api/jobs` | Newest first, filter by status and source |
| `GET` | `/api/jobs/{id}` | Includes run statistics |
| `POST` | `/api/jobs` | Enqueues a collection, returns `202` |
| `GET` | `/api/sources` | Configured sources |
| `GET` | `/api/export` | `format=csv\|json`, streamed |

Leads and exports share the same filters: `source`, `country`, `city`,
`validation_status`. Page size is capped server-side.

`POST /api/jobs` requires an `X-API-Key` header when `LEADPIPE_API_KEY` is set; reads
stay open. Interactive documentation is at `/docs`.

---

## CLI

```bash
uv run leadpipe collect  --source example_csv   # run a collection now
uv run leadpipe enqueue  example_csv            # queue one for a worker
uv run leadpipe worker                          # process queued jobs
uv run leadpipe export   --format csv           # export leads
uv run leadpipe sources                         # list configured sources
uv run leadpipe serve                           # run the API
```

The CLI and the API are thin adapters over the same pipeline — neither owns any logic.

---

## How it is put together

```text
app/
├── domain/          value types shared across layers
├── normalization/   pure functions: names, emails, urls, phones, locations
├── validation/      per-field tri-state validation
├── deduplication/   fingerprints, match rules, merge policy
├── sources/         source adapters and the registry
├── pipeline/        collect → normalize → validate → dedup → persist
├── jobs/            postgres-backed queue and worker
├── repositories/    database access
├── exports/         streaming CSV and JSON writers
└── api/             FastAPI application
```

Normalization, validation and deduplication are pure functions with no database and no
I/O, which is why they are the fastest and most thoroughly tested part of the system.

### Storage

Three tables carry the interesting part:

```text
source_records          leads                 lead_merges
  raw payload    ─┐       merged canonical      lead_id
  normalized      ├──▶    values                source_record_id
  fingerprints    │       first_seen_at         rule
  lead_id ────────┘       last_seen_at          confidence
                                                needs_review
```

`source_records` is immutable and holds one row per source per sighting, including the
untouched original payload. `leads` is derived from it. `lead_merges` records *why* each
link exists.

Keeping these separate is what makes provenance answerable, merges explainable, and
re-runs idempotent — and because the raw payloads are retained, the pipeline can be
re-run against historical data when normalization rules change.

### Deduplication rules

Applied in order; the first match wins:

| Rule | Confidence | Merges automatically |
| --- | --- | --- |
| Exact email | 1.00 | yes |
| Normalized website domain | 0.95 | yes |
| Phone number (E.164) | 0.90 | yes |
| Company name + location | ≤ 0.80 | **no** — flagged for review |
| Source-specific identifier | 1.00 | yes |

Name matching uses trigram similarity, implemented to match PostgreSQL's `pg_trgm` so the
in-memory matcher and the SQL candidate lookup agree on what "similar" means. Because it
is inherently fuzzy, it is capped below the auto-merge threshold — it never merges records
on its own.

Placeholder values cannot create matches: emails need an `@`, phones need to be valid
E.164, and unparseable websites yield no domain. Two unrelated companies both listing
`n/a` will not be merged.

When records do merge, each field is taken from the best candidate — non-null over null,
then higher source priority, then more recent, then the more complete record — and the
origin of every field is recorded.

---

## Development

```bash
make check       # lint, typecheck, test
make test
make format
```

Integration tests start a throwaway PostgreSQL container automatically, or use
`TEST_DATABASE_URL` if you would rather point them at your own. Migrations run against
that container on every test run, so the schema is verified rather than assumed.

The test suite does not touch the network or any external website.

---

## Status

Development

### Limitations

- Website matching uses the hostname, not the registrable domain, so
  `shop.example.com` and `example.com` are treated as different companies.
- Company-name matching never merges on its own by design; those pairs need review.
- The queue is single-database and intended for a modest number of workers, not a
  distributed workflow platform.
- Collection is deliberately limited to legitimate, publicly accessible sources. There is
  no support for bypassing access controls, anti-bot measures or authentication.

---

## License

[MIT](LICENSE).
