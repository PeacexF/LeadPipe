# Legal and ethical posture

Lead collection is a domain where the interesting engineering constraints are legal ones.
This page describes what LeadPipe does about them.

**This is not legal advice.** It documents the software's behaviour and the decisions built
into it. Whether a given collection is lawful depends on your jurisdiction, your purpose
and the sources you configure — that assessment is the operator's, and the tool cannot make
it for you.

## What this is for

Collecting **publicly available business contact information** — company names, business
addresses, switchboard numbers, `info@`-style addresses published by companies so they can
be contacted — for B2B outreach.

## What it will not do

These are absent by design, not unimplemented:

| Not supported | Why |
| --- | --- |
| Bypassing logins, paywalls or access controls | Data behind an access control is not public |
| Defeating CAPTCHAs, or anti-bot fingerprint evasion | An operator saying "no automated access" is an answer |
| Ignoring `robots.txt` | It is the machine-readable form of that answer |
| Rotating identities to appear as many visitors | The point of the User-Agent is to be identifiable |
| Consumer/personal profiles, or special-category data | Out of scope for B2B contact data |
| Email verification by SMTP probing | Validation is syntax only; probing mailboxes is abusive |

## Collection behaviour

- **`robots.txt` is fetched, parsed and obeyed** for every HTTP source, per host, cached for
  an hour. A disallowed URL is not fetched: the record is rejected with a reason and the run
  continues. In the bundled fixtures, `/private/` is disallowed and the collection reports
  one rejected record for exactly this reason.
- **`Crawl-delay` is honoured** where a site publishes one.
- **Requests are throttled per domain**, defaulting to one request per second, with a
  concurrency cap. Politeness is the default; going faster is an explicit config change.
- **The client identifies itself** as `LeadPipe/<version>`, and appends your contact when
  `contact` is configured. Setting it means a site operator who wants you to stop can find
  you.
- **Requests to private, loopback and link-local addresses are refused** unless the source
  explicitly opts in, on every redirect hop as well as the first request.
- **Response sizes and redirect chains are capped**, so a source cannot be used to exhaust
  the collector.

`respect_robots` can be turned off in configuration, because a self-hosted endpoint or your
own fixtures need it. Turning it off for a site you do not control is a decision you are
making, and this documentation will not pretend otherwise.

## Lawful basis, in practice

Under the GDPR, business contact data about identifiable people (a named employee, a
personal work address) is still personal data. B2B outreach is commonly conducted under
**legitimate interest**, which requires that you can articulate the interest, that
processing is necessary for it, and that it does not override the individual's rights.

What the software gives you towards that:

| Obligation | What LeadPipe provides |
| --- | --- |
| Know where data came from | Every field's source record is retained and queryable |
| Data minimisation | Only mapped fields are extracted; nothing is inferred or enriched |
| Storage limitation | `leadpipe purge --days N` / `RETENTION_DAYS` |
| Right to erasure | `DELETE /api/leads/{id}`, cascading to raw records |
| Suppression after erasure | Deleted contacts are blocked from re-collection |
| Right of access / portability | Per-lead provenance, CSV and JSON export |
| Not leaking data further | Contact fields are redacted from all logs |

What it does not provide, and you must: a lawful-basis assessment, a privacy notice to the
people whose data you hold, a route for objections, and a check of each source's terms of
use. A directory being publicly readable does not by itself grant permission to
systematically copy it.

## Erasure that actually erases

Deleting a lead removes the merged record **and** every `source_record` it was built from,
including the untouched original payloads, and the merge history that links them. Nothing
is soft-deleted, and there is no copy left in the logs.

Deletion also adds the lead's email address and website domain to the suppression list, so
the next collection cannot bring it back:

```bash
curl -X DELETE "http://localhost:8000/api/leads/1"
# {"deleted": true, "suppressed": [{"kind": "email", ...}, {"kind": "domain", ...}]}
```

The next run reports the blocked records rather than storing them:

```text
example_csv  collected=20  new=0  duplicates=17  suppressed=3
```

Suppressed records are never written to the database at all — the check happens after
normalization and before persistence, so erasure does not depend on a later cleanup.

Both keys are suppressed because either alone is insufficient: one company can appear with
a website and no email in one source, and an email and no website in another.

Suppression can also be used pre-emptively, for an opt-out request from someone who is not
in the database yet:

```bash
uv run leadpipe suppress "info@example.test"
uv run leadpipe suppress --kind domain "example.test"
uv run leadpipe suppressions
uv run leadpipe suppress --remove "info@example.test"
```

Values are normalized on entry, so `  INFO@Example.TEST ` and `https://www.example.test/x`
match the addresses and domains as stored.

## Operator checklist

- [ ] Check each source's terms of use before configuring it
- [ ] Set `contact` on HTTP sources so you are reachable
- [ ] Leave `respect_robots` on and `allow_private_hosts` off for public sites
- [ ] Keep `requests_per_second` low enough to be unnoticeable
- [ ] Set `RETENTION_DAYS` to something you can justify
- [ ] Route opt-out requests into the suppression list, not a spreadsheet
- [ ] Be able to answer "where did you get this?" — the API already can
