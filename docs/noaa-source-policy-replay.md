# Independent NOAA advisory acquisition + collection-policy replay

## Status and validity (16 October 2026)

This is a research continuation of the **read-only NHC advisory completeness auditor**. It neither deploys code to OCHA nor accesses the OCHA database. It explicitly distinguishes:

1. NOAA **nominal issuance** times (supported by individual official source products);
2. **First available** times (unknown here; evaluated only as lag scenarios);
3. OCHA **scheduled collection opportunities** (documented in merged PR #55);
4. Simulated **source updates selected by each schedule** (model outcomes);
5. Actual ingestion, exposure/trigger correctness and financial costs (**not evaluated**).

The NOAA archive host returned access errors in this execution environment, so **live bulk harvesting was not performed**. The repository includes a network-enabled generator and an offline HTML parser, with fail-closed behavior. The example catalog has 22 selected advisory products (17 on September 24 for four storms, five on October 1 for Nolo), individually linked to NOAA archive pages or its index. It is **not exhaustive for either day, and emphatically not for September–October 2026**. Some examples use indexed evidence of a product rather than the full page body; the individual `evidence_level` values record that distinction.

Do **not** submit synthetic rows to the production auditor as if they were complete source truth.

## Actual collection policy: no retroactive assumptions

Per [OCHA PR #55](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/55):

- Before 2026-09-30 approximately 18:46 UTC: 16 polls/day at `00:00,00:30,03:00,03:30,...,21:00,21:30` UTC;
- Afterwards: 4 polls/day at `03:30,09:30,15:30,21:30` UTC;
- The maintainers intentionally accepted missing intermediate and special advisories during the reduced-cost period, with possible future backfills;
- The change required coordination with downstream Haiti and storm-alert jobs.

The transition instant comes from the PR deployment description, not a validated historical run timeline. Actual job starts and failures require Databricks evidence.

## Source-backed bounded counterfactuals

**All numbers below apply only to the curated source subset; no population-wide recall claims.** Under a zero-minute availability delay, with a hypothetical latest-known-advisory-per-storm feed:

| Window, source subset | Legacy 16/day | Reduced 4/day | Event-driven 30-minute metadata polling |
|---|---|---|---|
| 24 September, 17 listed products | 17 selected | 14 selected; 3 schedule gaps | 17 selected; 6 modeled heavy dispatches across storm batches |
| 1 October, Nolo's 5 listed products | 5 selected | 3 selected; 2 schedule gaps | 5 selected; 5 modeled heavy dispatches |

The October 1 missed-in-model advisories are at **12:00 and 18:00 UTC**, as illustrated by [Nolo 43A](https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.043.shtml) and [Nolo 44A](https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.044.shtml). The 15:00 and 21:00 regular advisories supersede them before the next reduced-policy poll. This does **not** establish that they were unexpectedly lost: the reduced policy intentionally omits intermediate advisories.

The **event-driven candidate** uses 48 inexpensive metadata-check opportunities per day, and batches all newly discovered storm products at each poll into one hypothetical expensive job. It is an optimization *hypothesis*, not a deployable OCHA change; actual job initialization, per-storm ETL stages, Databricks pricing and download reliability still need evaluation.

### Publishing latency sensitivity

An archived advisory's nominal issuance does not tell us its first available time. We therefore repeat the replay with an assumed *uniform* 0, 15, 30 and 60-minute availability lag. For the October 1 Nolo subset, the reduced policy models 3/5 selected with lags 0–30 minutes but only 2/5 with a 60-minute lag; the previous policy models 5/5 at lags 0–30 minutes and 4/5 at 60 minutes. These are hypothetical timing scenarios, **not latency measurements**.

### 24 September outage, separately

[OCHA PR #53](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/53) describes a failed database configuration and an outage from approximately 03:30 to 18:30 UTC. The provided **illustrative outage scenario** excludes ticks between 03:30 and 18:31 and blocks 11 of 16 *scheduled poll opportunities*. This is not an independent reconstruction of job logs or the full set of 20 missing NHC products; the interval boundary and source catalog are incomplete. The policy simulator labels these distinct from schedule gaps.

## Run it entirely offline

From the repository root:

```bash
python -m pytest -q tests/test_noaa_source_policy.py

python -m storm_audit.policy_replay \
  --manifest examples/noaa_2026_verified_subset.json \
  --start 2026-10-01T00:00:00Z --until 2026-10-02T00:00:00Z \
  --policy historical --lag-minutes 0 \
  --output /tmp/oct1_policy_replay.json

# Proposed lightweight observation + change-trigger scenario
python -m storm_audit.policy_replay \
  --manifest examples/noaa_2026_verified_subset.json \
  --start 2026-10-01T00:00:00Z --until 2026-10-02T00:00:00Z \
  --policy event_driven --output /tmp/oct1_event_driven.json
```

To parse separately downloaded NOAA `.shtml` products in an offline folder, without fetching a live page:

```bash
python -m storm_audit.noaa_archive \
  --storm EP152026 \
  --start 2026-09-24T00:00:00Z --until 2026-10-02T00:00:00Z \
  --html-dir ./saved_noaa_products \
  --output /tmp/independent_manifest.json
```

With a working NOAA connection, **explicitly** fetch official archive products for the selected storms:

```bash
python -m storm_audit.noaa_archive \
  --storm AL062026 --storm EP152026 --storm EP162026 --storm EP172026 \
  --start 2026-09-24T00:00:00Z --until 2026-10-16T00:00:00Z \
  --fetch --output /tmp/noaa_manifest.json
```

The importer prefers NOAA `public` and `public_a` etc., not forecast discussions or `fstadv` duplicates. It validates the storm ID, product number, official domain, local timezone and any UTC summary. A mismatch raises rather than making up a timestamp. **Successful parsing does not, by itself, certify that a complete archive was discovered.** A source-completeness review is still essential.

## Next independent validation gates

1. Collect a complete bounded NOAA archive from an authorized reachable network, including special updates and any catalog exceptions, and record source coverage and checksums.
2. Independently audit product identity, corrections/revisions and UTC times; do not use guessed fixed-cadence rows.
3. Obtain first-observed/publication timestamps or continuous polling logs for availability modeling; do not derive publication time from archive modification timestamps.
4. Get an authorized, consistent read-only historical OCHA snapshot or application logs to validate actual missed, intentionally omitted and recovered inputs.
5. Execute the existing geometry and population-exposure pipeline on isolated archived data to quantify changes before claiming operational or humanitarian impact.
6. Benchmark metadata polling + conditional processing **in real CU/DBX cost units** and review with maintainers before modifying any schedule.

**Acceptance criterion:** An independent source inventory reconciled with actual ingestion evidence, a correct policy timeline, zero false blame for expected policy omissions, and reproducible measured downstream differences when they exist.

## Safer event discovery and reconciliation prototype

The latest-only metadata feed is a lossy hint, not a completeness source. For a
failure-oriented, durable offline queue, scheduled archive catch-up, modeled
batch/cost caps and recovery tests, see
[reliable-event-reconciliation.md](reliable-event-reconciliation.md).
This research prototype does not submit Databricks jobs or touch OCHA data.
