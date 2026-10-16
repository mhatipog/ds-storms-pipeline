# NOAA CurrentStorms snapshot evidence: cautious first-observation reconstruction

## What's implemented

The offline `storm_audit.snapshot_timeline` module parses [NOAA's documented
CurrentStorms JSON contract](https://www.nhc.noaa.gov/productexamples/)
(`activeStorms[].id`, `publicAdvisory.advNum`, `issuance`, and `fileUpdateTime`).
Its schema behavior is cross-checked against a real, public example from
[OCHA's older NHC forecast repository](https://github.com/OCHA-DAP/ds-nhc-forecast/blob/main/NHC_JSON_Sample.json).
An **attribution-identified excerpt** of the example is included at
`examples/ocha_2023_noaa_feed_schema_excerpt.json`. The excerpt is *not* a
contemporaneous capture made during the 2026 Nolo event.

It accepts an **explicit offline manifest of saved snapshot files**, each with:

- a relative `.json` path (path traversal and symlink escapes rejected),
- a SHA256 content digest,
- a timestamp `observed_at` supplied by the dataset curator, and
- an optional source URL. For `retrospective_archive` captures, the URL must
  match the official `nhc.noaa.gov/archive/activeJson/{year}/CurrentStorms_*.json`
  namespace.

The module extracts *public-advisory* identity only. Changes in
`forecastAdvisory`, WSP, a different product kind, or `lastUpdate` alone are
not automatically treated as new public advisories. Storm IDs, UTC issuance,
advisory numbering, and source-year consistency are validated.

For each independently listed historical advisory, it reports:

- earliest snapshot **observing** that exact storm/advisory/issuance triple;
- last earlier snapshot of the *same active storm* explicitly showing a
  different public advisory, when available;
- presence count, content hash, `fileUpdateTime` if present, and provenance;
- conflicting number/time claims requiring investigation;
- **possible in-place source revisions** when the same advisory identity is
  observed with different NOAA `fileUpdateTime` values (a signal, not proof
  of changed bulletin content or downstream geometry);
- `not_observed_coverage_unknown` when no supplied snapshot has it.

**An archived snapshot's `observed_at` is not proven first availability.**
An independently authenticated collector log might establish when *that
collector* first observed an advisory, but even that is not an NHC publication
time. Likewise, the JSON `fileUpdateTime` can precede the nominal issuance
and is **not** the historical HTTP first-availability time. The source archive's
index file modification dates must never be silently used as publication times.

## Bounded synthetic regression, real advisory identities

The eight-product Nolo October 1 catalog comes from the manually reviewed NHC
storm index (`examples/noaa_nolo_2026-10-01_public_day.json`). Four **invented**
JSON snapshots, using NOAA's true JSON field names, simulate observations at
03:30/09:30/15:30/21:30 UTC. They are clearly labeled
`synthetic_scenario`, and SHA256-protected to exercise the ingestion contract.

Result: exactly four regular advisories are *visible* in those four simulated
snapshots; the four intermediate advisories are not *visible*. This says nothing
about actual NOAA snapshot coverage or what OCHA really ingested.

```bash
python -m storm_audit.snapshot_timeline \
  --snapshots-index examples/nolo_snapshot_scenario/synthetic-snapshot-index.json \
  --manifest examples/noaa_nolo_2026-10-01_public_day.json \
  --out /tmp/nolo_snapshot_observations.json

python -m pytest -q tests/test_snapshot_timeline.py
```

## What is needed for a real historical measurement

1. Obtain a **bounded set of actual JSON files** and the directory href index
   from https://www.nhc.noaa.gov/archive/activeJson/2026/. Do not take
   visually truncated link text (`CurrentStorms_2026-0..>`) as a filename; use
   the full HTML `href`. The helper `noaa_directory_urls` parses those safely.
2. Keep original bytes untouched. Record SHA256 plus the archive URL. Prefer
   authentic collection logs with observed-at timestamps. For retrospective
   archives, use a defensible **archive-snapshot timestamp** with its basis
   documented separately; it still cannot establish the historical HTTP
   first-publication time.
3. Provide a `retrospective_archive` snapshot index with these files and
   accurately labeled capture times. Never synthesize the index's timestamps.
4. Compare against independently checked NHC public advisory products and
   real OCHA ingestion/Databricks records **only with maintainer approval**.
5. Measure sensitivity to gaps in archival capture, product revisions, storm
   termination, and delays. If the NOAA archive itself omits intermediate
   snapshots, record unknown coverage and use a separate source catalog.

**Environment limitation (2026-10-16):** NOAA's archive index was searchable,
but direct file retrieval returned HTTP 403 in the browsing interface, and
network DNS failed in the execution container. Therefore **no actual 2026
archived CurrentStorms JSON files were retrieved or analyzed** in this run.
No external work, Databricks run, or OCHA production system was touched.

## Safety/acceptance gates

- No inference from cadence about advisories not in the source catalog.
- No attempt to infer publication-time intervals from directory Last-Modified.
- Absence from sparse snapshots is **unknown**, not proof of never existing.
- A screenshot or archive index alone never substitutes for the JSON bytes.
- Integrity hash mismatch, duplicate capture instant, conflicting advisory
  identity, unrecognized schema, or unsafe input URL fail closed.
- A zero *unobserved* count remains evidence-limited: it is not a verified OCHA
  delivery-completeness result or a measured disaster response benefit.

## Optional polite NOAA harvester (no credentials)

`storm_audit.archive_harvester` can parse a saved directory index without
any network request, or **only with explicit `--fetch`** retrieve matching
source JSON files from NOAA. It checks the full `href` targets, enforces an
HTTPS NOAA host/path allowlist (including redirects), limits day/file count
and individual response bytes, rate-limits requests to at least 1 second
apart by default, refuses unexpected schema, and never silently overwrites
changed archived file bytes. Nothing is submitted back to NOAA.

```bash
# Offline catalog-only inspection of a manually saved NOAA directory HTML:
python -m storm_audit.archive_harvester \
  --day 2026-10-01 --index-html ./nhc-2026-index.html \
  --out-dir /tmp/noaa-day-catalog

# When NOAA is reachable, explicit opt-in to network downloads:
python -m storm_audit.archive_harvester \
  --day 2026-10-01 --fetch --max-files 160 \
  --out-dir /tmp/noaa-day-2026-10-01
```

**Do not pass the generated retrieval log straight into the historical
timeline tool:** it deliberately contains `retrieved_at` (when you downloaded
old files *today*) and **no historical `observed_at`**. The timeline's own
hashed snapshot index must be independently curated with genuine snapshot
capture-time evidence. Archive file names or directory timestamps alone do
not establish the original publication/first-availability timestamp.

A restricted-network machine may be unable to download NOAA archives. That
is a documented blocker; not evidence that NOAA lacks those records.
