# Deduplication

Three rows describing the same company should become one lead, and two different companies
with similar names should not. This is the part of LeadPipe most worth reading closely.

## Fingerprints

Matching never compares display values. Each normalized lead is reduced to a small set of
comparable keys:

| Fingerprint | Derived from | Suppressed when |
| --- | --- | --- |
| `email` | normalized email | it contains no `@` |
| `domain` | website hostname, `www.` stripped | the URL did not parse |
| `phone` | E.164 phone | it is not E.164 (no leading `+`) |
| `name_slug` | company name, casefolded, punctuation removed, trailing legal suffix dropped | the name is empty |
| `location` | `city|country`, casefolded | both are missing |
| `external_id` | the source's own identifier | the source does not supply one |

Placeholders cannot create matches. `n/a` never becomes a phone fingerprint, `-` never
becomes an email, and an unparseable website yields no domain — so two unrelated companies
that both wrote `n/a` are not merged.

`company_slug` strips one trailing legal suffix (`Oy`, `Oyj`, `AB`, `Ltd`, `GmbH`, `AS`,
`Inc`, and others), so `Nordic Clean Oy` and `Nordic Clean` produce the same slug.

## The rules

Applied in this order; the first one that matches wins.

| # | Rule | Requires | Confidence | Merges automatically |
| --- | --- | --- | --- | --- |
| 1 | `email` | identical email fingerprints | 1.00 | yes |
| 2 | `website` | identical domain fingerprints | 0.95 | yes |
| 3 | `phone` | identical E.164 numbers | 0.90 | yes |
| 4 | `name_location` | identical location **and** name similarity ≥ 0.70 | `min(similarity, 0.80)` | **no** |
| 5 | `external_id` | same source, identical identifier | 1.00 | yes |

A match merges automatically when its confidence reaches the auto-merge threshold of
**0.85**. Rule 4's confidence is capped at **0.80**, which is below that threshold — by
construction, name similarity alone can never merge two companies. It records a candidate
duplicate for review instead.

Rule 5 is checked last and only within one source, because an identifier is only unique in
the system that issued it.

Thresholds live in one place, `MatchPolicy` in `app/deduplication/matcher.py`:

```python
name_similarity_threshold = 0.7  # below this, not even a candidate
name_confidence_cap = 0.8  # deliberately under the auto-merge line
auto_merge_threshold = 0.85
```

## Name similarity

Similarity is Jaccard overlap of word-padded trigrams:

```text
"nordic clean"  →  {"  n", " no", "nor", "ord", "rdi", "dic", "ic ", "  c", " cl", ...}
```

This is the same trigram construction PostgreSQL's `pg_trgm` uses. That parity matters
because the two run in different places:

- the **SQL candidate lookup** narrows millions of leads to a handful using a GIN index and
  `similarity(name_slug, ?) >= 0.7`;
- the **Python matcher** then scores the shortlist and decides.

If the two disagreed about what "similar" means, the database would hand back rows the
matcher rejects, or worse, filter out rows it would have accepted.

## Candidate lookup

Before matching, the repository asks for leads that could plausibly match:

```sql
WHERE email = :email
   OR website_domain = :domain
   OR phone = :phone
   OR (location_key = :location AND similarity(name_slug, :slug) >= 0.7)
```

Capped at 20 candidates, ordered by id. Everything else is an index lookup; the trigram
branch is why `leads.name_slug` carries a GIN index.

## Merging

When records do merge, the lead is rebuilt from **all** of its records rather than patched
in place, so a merged lead never depends on the order the records arrived in.

Each field is taken from the first candidate that has a value, with candidates ranked:

1. higher source `priority`
2. more recently collected
3. more complete (more non-null fields)
4. lowest record id, as a stable tiebreak

`website` and `website_domain` are always taken from the same candidate — they are derived
from one another, and mixing them would produce a lead whose domain does not belong to its
URL.

The origin of every field is recorded, which is what `GET /api/leads/{id}` reports.

## Review instead of guessing

When a match is found but its confidence is below the auto-merge threshold, the record is
kept as its own lead **and** linked to the candidate with `needs_review = true`. Nothing is
silently discarded and nothing is silently merged.

## Worked example

From the bundled fixtures, lead 1 after collecting all three example sources:

```text
Nordic Clean Oy | anna.virtanen@nordicclean.test | +358401234567 | Helsinki FI

  record  1  example_csv        rule=initial        conf=1.00  review=false
  record  2  example_csv        rule=email          conf=1.00  review=false
  record  8  example_csv        rule=website        conf=0.95  review=false
  record 16  example_csv        rule=name_location  conf=0.80  review=true
  record 21  example_api        rule=website        conf=0.95  review=false
  record 28  example_directory  rule=website        conf=0.95  review=false
```

Five records make up this lead, attached by the email and website rules across three
sources. Record 16 is `Nordic Clean Oyj` — a different company in the same city with a very
similar name. It was **not** merged: it became its own lead, and the link was kept only as
a review flag.

The email and street came from `example_api`, which has the highest configured priority;
the CSV row for the same company lists `info@nordicclean.test` and a street without the
building letter.
