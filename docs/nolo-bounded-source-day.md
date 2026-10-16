# Nolo (EP152026): bounded NOAA-source policy benchmark, 1 October 2026

## Why this is a correction, not just another synthetic example

The previous selected NOAA subset included only five Nolo advisories from
09:00–21:00 UTC. NOAA's official **2026 Nolo storm archive summary** lists
**eight** public-advisory products for 1 October 2026 (00:00–21:00 UTC):

| UTC | Product | Kind | NOAA primary source |
|---|---|---|---|
| 00:00 | 41A | intermediate | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.041.shtml |
| 03:00 | 42 | regular | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.042.shtml |
| 06:00 | 42A | intermediate | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.042.shtml |
| 09:00 | 43 | regular | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.043.shtml |
| 12:00 | 43A | intermediate | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.043.shtml |
| 15:00 | 44 | regular | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.044.shtml |
| 18:00 | 44A | intermediate | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.044.shtml |
| 21:00 | 45 | regular | https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.045.shtml |

Reference index: https://www.nhc.noaa.gov/archive/2026/NOLO.shtml

**Explicit product-type boundary:** The same NOAA index lists a 12:35 UTC
`update`; it is *not counted as a ninth regular/intermediate public advisory*.
This item requires separate classification and ingestion-eligibility review.

The catalog and companion source-index control are manually transcribed from
official NOAA material. Cross-checking them prevents accidental omissions
within this bounded list; it does **not** establish live feed publication
availability or a complete archive of all product types. Never use the index
file's modification timestamps as actual first publication time.

## Reproducible scenario results (hypothetical source availability)

With the supplied eight-item source inventory and **0-minute lag**:

| Candidate | Products modeled selected | Nominal expensive job invocations |
|---|---:|---:|
| Former schedule: 00/:30 every 3 hours | 8/8 | 16 |
| Reduced schedule: 03:30, 09:30, 15:30, 21:30 | 4/8 | 4 |
| Thirty-minute discovery + modeled triggers | 8/8 | 8 |

A 60-minute lag reduces the former schedule to 7/8 **within this UTC day**,
while discovery still models 8/8. These are sensitivity scenarios; true
publication, data-ingestion and alert latencies have not been observed.
The reduced schedule's four modeled omissions (41A, 42A, 43A, 44A) are
**intentional-policy omissions under the cost-saving configuration**,
not newly established bugs or actual measured production losses.

## Why the headline "8 advisories in 8 batches" is NOT deployable yet

- Current NHC ETL fetches current storm information; it does **not** ingest
  previously skipped archive products merely because a queue discovered them.
- The operational pipeline passes a **single issued_time** to processing.
  A plan grouping multiple advisories cannot be executed as one heavy job
  without explicit new support and maintainer validation.
- A historical backfill must ingest independently verified NOAA products,
  process advisories in causal order and invalidate/recompute downstream
  cumulative swaths that depended on the earlier gap.
- NOAA archive availability and the correctness of WSP/track joins need
  separate validation. Archive ingestion scripts already exist for an
  **incident-specific** backfill (OCHA PR #53); this is not a production
  general-purpose event consumer.
- No Databricks compute, energy, API quota, monetary savings or population
  exposure effects have been measured.

## Staged work plan — no production effects

1. Verify the bounded NOAA source inventory, record checksums and classify
   the 12:35 update. Record the archive's scope and residual uncertainty.
2. Acquire *real historic feed snapshots* or observational polling logs to
   estimate first-observed time; do not substitute nominal issuance.
3. Compare against a time-consistent historical OCHA snapshot, with
   maintainer-approved source identity mapping, and separate intentional
   policy omissions from unknown/failed ingestions.
4. In a detached development environment, implement and verify archive
   ingestion and chronological downstream recompute using actual historical
   geometries and population inputs. Produce output hashes and measured diffs.
5. Profile compute and network costs of both policies; then evaluate a
   bounded, durable backfill plan with explicit idempotency, rate limits,
   completion verification and manual approval gates.

## Local reproducer

Run from the repository root:

```bash
python -m storm_audit.bounded_day_study \
  --manifest examples/noaa_nolo_2026-10-01_public_day.json \
  --index examples/noaa_nolo_2026-10-01_index_control.json \
  --output /tmp/nolo-oct1-evidence.json \
  --markdown /tmp/nolo-oct1-evidence.md
python -m pytest -q tests/test_bounded_nolo_study.py
```

**Result classification:** source-backed *bounded index*, simulated
observation policies, **zero** verified Databricks jobs, and no claim about
actual OCHA population exposure or humanitarian decisions. Keep this a
research branch until the independent source and operational inputs are
available for a real-data replay.
