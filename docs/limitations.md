# Limitations

Known gaps, in the order they are most likely to bite. Most are deliberate; the ones that
are not are marked.

## Matching

**Website matching uses the hostname, not the registrable domain.** There is no Public
Suffix List, so `shop.example.com` and `example.com` are different companies, and
`example.co.uk` is handled by luck rather than by rule. Adding a PSL dependency would fix
it; the current behaviour errs towards not merging, which is the safer direction.

**Company-name matching never merges on its own.** By design — see
[deduplication](deduplication.md) — but it means genuine duplicates whose only shared
signal is a similar name stay separate until someone reviews them.

**There is no review workflow.** Candidate duplicates are recorded with `needs_review` and
exposed in the lead's provenance, but nothing in the API lets you confirm or reject one.
You can see the decision; you cannot act on it without SQL.

**Merges cannot be undone through the API.** `lead_merges` records why each link exists, so
the information is there, but unmerging is a manual operation.

**Country normalization uses a fixed alias table.** Roughly twenty countries, biased towards
the Nordics and Western Europe. Anything else passes through unchanged, which means
`Suomi` normalizes and `Հայաստան` does not.

## Validation

**Email validation is syntax only.** No MX lookup, no mailbox probing — deliberately, since
probing strangers' mail servers to see whether an address exists is the kind of behaviour
this project avoids. A syntactically perfect address at a dead domain validates as `valid`.

**Phone validation depends on the region hint.** A national-format number from a source with
no `region` configured stays as written and does not become a phone fingerprint, so it
cannot match.

## Collection

**Every run is a full run.** There is no incremental or delta collection: a scheduled job
re-reads the whole source. That is cheap for a CSV and wasteful for a large directory.
Idempotency means the result is correct either way.

**No JavaScript rendering.** The HTML adapter parses server-rendered markup. A directory
that builds its listing client-side needs its underlying API configured as an `api` source
instead.

**No authenticated sources.** Static headers can be configured, so a simple bearer token
works, but there is no OAuth flow, no session handling and no credential refresh.

**Unrecognised configuration keys are ignored.** An adapter validates the keys it knows;
a typo like `max_page` instead of `max_pages` silently does nothing rather than failing at
startup. *Not deliberate — a known rough edge.*

## Queue and scale

**One database, one queue.** `SELECT ... FOR UPDATE SKIP LOCKED` is correct and safe for
several workers against one PostgreSQL instance. It is not a distributed workflow engine:
no fan-out across a cluster, no priorities, no dependencies between jobs, no dead-letter
queue beyond the `failed` status.

**Polling, not notification.** Idle workers poll every second, so a queued job waits up to a
second before it starts. `LISTEN`/`NOTIFY` would remove that; nothing needs it yet.

**A collection runs single-threaded within a job.** Records are processed one at a time, and
each one costs a candidate lookup. Fine for thousands of records per source, not tuned for
millions.

**Schedules live in the worker process.** Every worker runs the scheduler and ticks are
deduplicated by row locking, so nothing double-fires — but a source can only be scheduled
by cron in configuration, not from the API.

## API and exports

**A single shared API key.** No users, no roles, no per-key scoping, no rate limiting.
Reads are entirely unauthenticated. Adequate behind a private network or a gateway that
provides those things; not adequate as a public, multi-tenant API.

**Cursor pagination is forward-only.** Keyset by id, which is what makes large exports
cheap, but there is no page count, no total, and no jumping to a page.

**Two export formats.** CSV and JSON, both streamed. No Excel, no Parquet, no direct CRM
integration.

**Suppression matches emails and domains only.** A company that reappears under a different
address and a different domain is not recognised as previously erased.

## Observability

**Logs, no metrics.** Structured logs cover everything that happens, and job results are
queryable through the API, but there is no `/metrics` endpoint and no tracing.

**No alerting.** A source that has silently returned zero records for a week shows up in
`GET /api/jobs`; nothing tells you about it.
