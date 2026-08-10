# Example sources and fixtures

The bundled data is deliberately dirty. Every row exists to trigger something specific in
the pipeline, so a first run demonstrates the behaviour rather than just succeeding.

Nothing here touches the public internet: `.test` is a reserved TLD, and the HTTP fixtures
are served locally by the `fixtures` container in `docker-compose.yml`.

```text
configs/       csv.yaml, api.yaml, html.yaml — one source each
               all.yaml — all three, used by docker compose
data/          companies.csv, companies_api*.json, directory/, private/, robots.txt
```

## What a full run produces

```bash
docker compose up -d
for s in example_csv example_api example_directory; do
  curl -s -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' \
    -d "{\"source\":\"$s\"}" > /dev/null
done
```

| Source | Collected | Valid | Invalid | Duplicates | New leads | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| `example_csv` | 20 | 17 | 3 | 5 | 15 | 0 |
| `example_api` | 7 | 7 | 0 | 3 | 4 | 1 |
| `example_directory` | 7 | 6 | 1 | 3 | 4 | 1 |

**34 collected records, 23 leads.** Running all three again produces `new_leads=0` and
leaves the count at 23.

## `companies.csv` — 20 rows

CSV source, priority 0.

| Rows | Designed to trigger |
| --- | --- |
| C-001, C-002 | Same company twice: `Nordic Clean Oy` / `NORDIC CLEAN OY`, `www.` vs `https://` vs trailing slash, `+358 40 123 4567` vs `040-1234567`, `Finland` vs `FI`, upper-case email. Merged by the **email** rule |
| C-008 | `Nordic Clean` — no legal suffix, no email, no phone, same domain. Merged by the **website** rule |
| C-016 | `Nordic Clean Oyj` — a *different* company, same city, very similar name. Matched by **name_location** at 0.80, below the auto-merge line: kept as its own lead and flagged for review |
| C-017 | `Nordic Clean Oy` in Turku, different domain. Same name, different location, so no match at all — a separate company |
| C-003, C-011 | `Helsinki Facility Services Ltd` / `Helsinki Facility Services`, different URL paths, shouted email. Merged by **email** |
| C-004 | URL carrying `?utm_source=&utm_medium=` — tracking parameters stripped during normalization |
| C-005, C-019 | National phone formats (`03 123 4567`, `019 555 7777`) parsed to E.164 using the `FI` region default |
| C-006 | `not-an-email` — the lead is stored and marked **invalid**, not dropped |
| C-007 | No website at all — no domain fingerprint, so it cannot match on one |
| C-009, C-018 | `Vantaa Puhtaus Oy` vs `  Vantaa  Puhtaus  Oy  ` with collapsed whitespace and upper-case city |
| C-010, C-020 | `Oulu Clean Solutions Ltd` / `Oulu Clean Solutions`, `ouluclean.test` vs `www.ouluclean.test`. Merged by **website**. C-010's phone is `n/a`: **invalid**, and no phone fingerprint, so it can never create a false match |
| C-013 | Completely empty row — **invalid** (missing company name), stored with the reason |
| C-012, C-014, C-015 | Ordinary, clean records: the control group |

## `companies_api*.json` — 8 items over 2 pages

API source, priority 10 — the highest, so it wins field conflicts.

| Item | Designed to trigger |
| --- | --- |
| `meta.next` | Pagination by a next-page path, followed until it is `null` |
| `data` + `contact.email`, `address.city` | Dotted-path mapping into nested objects |
| API-100 | `Nordic Clean Oy` again, this time with a *named* contact and a more precise street. Because this source has the higher priority, its email and address win the merge |
| API-104 | `Vantaa Puhtaus Oy` — merges into the CSV lead by domain |
| API-102, 105, 106 | Estonia, Norway, Sweden: `Estonia → EE`, `Norway → NO`, `Sweden → SE`, and `+372`/`+47`/`+46` numbers |
| API-103 | No website at all, and a national number (`016 555 8899`) that the `FI` default turns into `+358165558899` — a lead that can only ever match on its email or phone |
| `"not-an-object"` | A string where an object belongs. Yields a **record error**: counted, logged, run continues |
| `vat_id` | An unmapped field. Ignored for lead fields, still preserved in `source_records.raw` |

## `directory/` — an HTML listing

HTML source, priority 5. Two listing pages, four per-company detail pages.

| Element | Designed to trigger |
| --- | --- |
| `li.company` + `a.next` | Item selection and following pagination |
| `a.profile@href` | Detail pages, fetched per company and merged with the listing fields |
| `mailto:INFO@nordicclean.test` | `mailto:` stripping and lower-casing |
| `?utm_source=directory` | Tracking parameter removal |
| `03&nbsp;123&nbsp;4567` | Non-breaking spaces collapsed before phone parsing |
| `   Nordic Clean Oy   `, `   Savonlinna   Siivous    Ky   ` | Whitespace collapsing in company names |
| `Hidden Holdings Oy` → `/private/` | Disallowed by `robots.txt`. The detail page is **not fetched**; the record is rejected with a reason and counted in `errors` |
| `Lappeenranta Kiinteistöpalvelu` | No profile link and empty contact elements — listing data only |
| `Broken Listing` | Phone `not a phone`, nothing else — **invalid** |

`data/robots.txt` is served at the fixture root and disallows `/private/`. That one line is
what makes the robots check observable end to end:

```text
warning  record rejected  job=3  source=example_directory
         reason="robots.txt disallows http://fixtures/private/hidden-holdings.html"
```

## Cross-source result

After all three sources, lead 1 is one company assembled from six records:

```text
Nordic Clean Oy | anna.virtanen@nordicclean.test | +358401234567 | Helsinki FI

  record  1  example_csv        rule=initial        conf=1.00  review=false
  record  2  example_csv        rule=email          conf=1.00  review=false
  record  8  example_csv        rule=website        conf=0.95  review=false
  record 16  example_csv        rule=name_location  conf=0.80  review=true
  record 21  example_api        rule=website        conf=0.95  review=false
  record 28  example_directory  rule=website        conf=0.95  review=false
```

```bash
curl -s localhost:8000/api/leads/1 | jq '.provenance'
```

## Using the fixtures without Docker

The HTTP sources read `FIXTURES_URL`, defaulting to `http://localhost:8080`:

```bash
python -m http.server 8080 --directory examples/data
uv run leadpipe collect -c examples/configs/html.yaml
```

Both HTTP configs set `allow_private_hosts: true`, which is required to reach localhost and
should never be set for a source on the public internet.
