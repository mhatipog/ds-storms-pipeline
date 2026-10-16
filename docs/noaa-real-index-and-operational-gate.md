# NOAA 1 October 2026 archive listing: verifiable *metadata*, not JSON captures

## Independent archive evidence acquired

On 16 October 2026, the publicly indexed [NOAA CurrentStorms 2026
archive directory](https://prod-east-nhc.woc.noaa.gov/archive/activeJson/2026/)
was accessible as **rendered directory metadata** (source index lines
2413–2450 for 2026-10-01). It listed **38 rows** with Last modified dates on
1 October between **02:34 and 23:34 UTC**, all with a displayed size of 14K.
The rendered labels were truncated (`CurrentStorms_2026-1..>`). Direct links
for high-index file entries could not be resolved in the browsing interface;
network DNS also failed from the execution container. No 2026 Nolo JSON
payload was downloaded. Source evidence is transcribed as 38 clearly labeled
metadata entries in `examples/noaa_2026-10-01_archived_json_directory_visible_rows.json`.

Commands:

```sh
python -m storm_audit.archived_listing \
  --index-evidence examples/noaa_2026-10-01_archived_json_directory_visible_rows.json \
  --output /tmp/noaa_archive_index_report.json

python -m storm_audit.operational_evidence \
  --manifest examples/noaa_nolo_2026-10-01_public_day.json \
  --reviewed-index examples/noaa_nolo_2026-10-01_index_control.json \
  --output /tmp/nolo_operational_evidence.json
```

The four reduced-schedule ticks (03:30/09:30/15:30/21:30 UTC) have directory
metadata entries listed 6/6/6/8 minutes earlier, respectively. This only
indicates **index entries existed with nearby Last modified values**, not that
Nolo advisory content was in those files or that OCHA actually fetched them.
Last modified is neither a verified snapshot-capture timestamp nor HTTP
first-availability evidence. We do **not** infer latency from it.

## Operational evidence gate (not bypassable by a success flag)

The `operational_evidence` tool starts with all eight NOAA-indexed public
advisories labeled **operational_evidence_unavailable**. It consumes an
optional, explicitly attested export of the public `storms.nhc_tracks_geo`
key/row counts, but **never** accesses a database itself. No DSN, secrets or
production jobs are involved.

The operator's export must declare its scope, source table, complete scan
status, UTC export time and whether it is a **current-state** extract or a
**historical-as-of** snapshot. This self-attestation is not independently
verified. A current-state extract from October 16 cannot prove what the
operational database contained on October 1, especially given later backfills.
Even a historical-as-of extract alone cannot establish when NHC published an
advisory or when the Databricks job originally ingested and processed it.

An example contract with all rows unknown, **not production data**, appears
at `examples/operational-export-contract-example.json`. A database operator
can generate the aggregated source row counts with a reviewed, read-only query:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT atcf_id AS storm_id, issued_time,
       COUNT(*)::integer AS row_count
  FROM storms.nhc_tracks_geo
 WHERE atcf_id = 'EP152026'
   AND issued_time >= TIMESTAMP '2026-10-01 00:00:00'
   AND issued_time <  TIMESTAMP '2026-10-02 00:00:00'
 GROUP BY atcf_id, issued_time
 ORDER BY issued_time;
COMMIT;
```

**Do not provide credentials or connection strings** in the export. The SQL
returns *current database presence*, not past ingestion timing, unless run
against a preserved, timestamped historical snapshot. Backfilled data may
cause all eight advisories to be present today even if some were never
available to the October 1 processing cycle.

## What remains blocked

1. Full original NOAA JSON file hrefs and historical JSON bytes/hashes.
2. Independently attested original NOAA feed visibility timestamps.
3. Authorised historical Databricks run history / database state snapshots.
4. A validated comparison of observed inputs with downstream exposure results.

**Next useful step:** an OCHA maintainer or an authorized machine with NOAA
archive access captures a full directory HTML page and the eight relevant
CurrentStorms JSON snapshots, preserving hashes. A database operator then
exports the bounded read-only data or comparable historical job evidence.
These steps require no deployment of this research prototype.
