# Maintainer Request: Read-Only Operational Evidence for Nolo (`EP152026`)

## 1. Context & Purpose

The OCHA research investigation into Tropical Storm Nolo (`EP152026`) on **1 October 2026 UTC** has established from genuine NOAA historical archives that nine advisory payloads (`41A`, `42`, `42A`, `43`, `43A`, `44`, `44A`, `45`, and `45A`) were uploaded to NOAA's `CurrentStorms.json` feed.

Under the 6-hour polling schedule introduced in **PR #55** (`0 30 3,9,15,21 * * ?`), the four intermediate advisories (`41A`, `42A`, `43A`, and `44A`) were overwritten in the live feed 40 to 48 minutes prior to each scheduled run.

To determine whether these intermediate advisories were actually omitted during live operations or captured via alternative mechanisms, an authorized OCHA database administrator or maintainer is requested to provide a **minimal, non-sensitive, read-only data export**.

---

## 2. Corrected Upstream SQL Database Query

> [!IMPORTANT]
> A previous draft query referenced nonexistent column names (`advisory_number`, `issuance_timestamp`, and `created_at`). 
> The corrected query below has been strictly validated against the upstream schema defined in [`src/schemas/sql/nhc_tables.sql`](file:///C:/Users/me10_/AppData/Local/Temp/claude/C--Users-me10--OneDrive-Desktop-CC-jobpost/a26c05de-c66b-425b-b996-22105873ccb4/scratchpad/ds-storms-pipeline/src/schemas/sql/nhc_tables.sql).

Execute the following read-only transaction in PostgreSQL:

```sql
BEGIN TRANSACTION
  ISOLATION LEVEL REPEATABLE READ,
  READ ONLY;

SELECT
    atcf_id AS storm_id,
    issued_time AS issued_at,
    COUNT(*)::integer AS row_count,
    COUNT(*) FILTER (
        WHERE leadtime = 0
    )::integer AS observed_rows
FROM storms.nhc_tracks_geo
WHERE atcf_id = 'EP152026'
  AND issued_time >= TIMESTAMP '2026-10-01 00:00:00'
  AND issued_time < TIMESTAMP '2026-10-02 00:00:00'
GROUP BY atcf_id, issued_time
ORDER BY issued_time;

COMMIT;
```

### Schema Cross-Verification
- **Table**: `storms.nhc_tracks_geo` (Track points with geometry; stores forecast and observation points).
- **`atcf_id`**: VARCHAR (Standardized ATCF identifier, e.g. `'EP152026'`).
- **`issued_time`**: TIMESTAMP NOT NULL (Advisory issuance timestamp in UTC).
- **`leadtime`**: INTEGER NOT NULL (`leadtime = 0` designates the actual observed storm position; `leadtime > 0` designates forward forecast track points).

---

## 3. Epistemic Limitation: Why Current-State Cannot Prove Historical State

**A current-state query cannot prove the original October 1 processing state.**

The table `storms.nhc_tracks_geo` does not contain an ingestion timestamp column (`ingested_at` or `created_at`). The pipeline uses `INSERT ... ON CONFLICT DO UPDATE` or transactional delete/re-insert semantics.

If a subsequent backfill or manual reconciliation script (such as `scripts/backfill_nhc_from_archive.py`) was executed at any point after 1 October 2026, the intermediate advisories would now exist in the table as current state. Conversely, if rows are absent today, it does not distinguish between a live polling omission and a downstream table truncation.

---

## 4. Minimal Historical Databricks Metadata Needed

To establish the **genuine historical state** as of 1 October 2026, maintainers are requested to export the following execution metadata from Databricks:

1. **Job Run History for NHC Pipeline**:
   - Job ID: `nhc_pipeline` (or corresponding scheduled bundle job)
   - Date: `2026-10-01`
   - Specific run start and completion timestamps for:
     - `03:30 UTC` run
     - `09:30 UTC` run
     - `15:30 UTC` run
     - `21:30 UTC` run
   - Execution status: `SUCCESS`, `FAILED`, `SKIPPED`, or `UPSTREAM_FAILED`.
2. **Job Run Parameters & Task Output Summary**:
   - Extracted `issued_time` values recorded in the Databricks run logs or stdout for each of those four runs.
   - Whether any manual or ad-hoc backfill runs were dispatched for `EP152026` on or following 1 October 2026.
3. **Azure Blob Ingestion Snapshot (if available)**:
   - File listing under `storm/nhc/current/` container from `2026-10-01` with blob creation timestamps.

---

## 5. Export Packaging Contract

To ingest this data directly into the automated verification harness (`storm_audit.operational_evidence`), format the query output as a single JSON object matching [`examples/operational-export-contract-example.json`](file:///C:/Users/me10_/AppData/Local/Temp/claude/C--Users-me10--OneDrive-Desktop-CC-jobpost/a26c05de-c66b-425b-b996-22105873ccb4/scratchpad/ds-storms-pipeline/examples/operational-export-contract-example.json):

```json
{
  "schema_version": 1,
  "table": "storms.nhc_tracks_geo",
  "storm_id": "EP152026",
  "scope_start": "2026-10-01T00:00:00Z",
  "scope_until": "2026-10-02T00:00:00Z",
  "query_status": "succeeded",
  "coverage": "full_bounded_scan",
  "snapshot_type": "current_state",
  "exported_at": "2026-10-16T12:00:00Z",
  "rows": [
    {
      "storm_id": "EP152026",
      "issued_at": "2026-10-01T03:00:00Z",
      "row_count": 16,
      "observed_rows": 1
    }
  ]
}
```

This export contains zero credentials, personal data, or proprietary geometry, and satisfies the fail-closed verification gate.
