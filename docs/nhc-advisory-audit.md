# NHC Advisory Completeness Auditor

**Independent, read-only proof of concept for OCHA's NHC storm pipeline.** This tool
reconciles an independently sourced manifest of NHC advisories against the
pipeline's raw tracks, derived buffers, exposure tables and (optionally)
issuance-wide completion markers. It does not change any data, trigger alerts,
or start Databricks jobs.

**Status (2026-10-15):** 28 local automated tests passing; synthetic historical
incident scenario evaluated. **Not deployed, not peer-reviewed upstream,
not verified against a live OCHA database or the NHC archive per advisory.**

Related upstream: [storm-pipeline issue #20](https://github.com/OCHA-DAP/ds-storms-pipeline/issues/20),
[September 2026 NHC backfill PR #53](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/53), and
[completion markers PR #46](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/46).

## Run the historical **illustrative** scenario

Python 3.12+; no third-party packages required for offline analysis.

```bash
# Run from the repository root
python -m storm_audit \
  --manifest examples/2026-09-24-incident-manifest.json \
  --snapshot examples/2026-09-24-synthetic-snapshot.json \
  --output examples/incident-report.json \
  --markdown examples/incident-report.md

python -m pytest -q  # pytest only needed to run tests
```

The scenario is explicitly marked `illustrative` on **both** inputs. It
reconstructs the **20 missing products** listed in OCHA's PR #53: 03Z, 09Z,
15Z for Fay, Nolo, Odalys and Polo; additionally 00Z, 06Z, 12Z, 18Z for
Nolo and Polo. Four post-outage storm advisories with derived table rows are
synthetically supplied to exercise the stale-output detector.

Expected output: 20 `EXPECTED_RAW_ABSENT` and 16
`POSSIBLY_STALE_CUMULATIVE` (four selected output stages for four storms).
Neither metric is a measurement of OCHA's current production database or actual
recomputed exposure differences.

## Actual DB inspection (optional, read only)

1. Independently list expected advisories from an authoritative NHC archive
   source. **Do not infer advisories from a fixed 3h/6h cadence:** off-cycle
   special products and publication delays are the entire point of this tool.
2. Prepare CSV with `storm_id,issued_at,source_ref,required_stages` headers.
   `required_stages` is optional and pipe-separated. Only assert a stage if
   you verified the input was eligible for that processing step. In particular,
   exposure rows can legitimately be empty when no population intersects.
3. Build manifest and review it before setting its assurance level:

```bash
python -m storm_audit.build_manifest catalog.csv expected.json \
  --source-description 'Independently reviewed NHC archive listing' \
  --source-assurance unverified
```

4. Use a **read-only PostgreSQL account** with SELECT permission on the
   required `storms` tables. The collector additionally issues
   `SET TRANSACTION READ ONLY` before any query. Credentials must be set in
   an environment variable, never in command arguments or shared reports.

```bash
export STORM_AUDIT_DSN='postgresql+psycopg2://readonly_user:REDACTED@db.example/storms'
python -m storm_audit \
  --manifest expected.json \
  --dsn-env STORM_AUDIT_DSN \
  --lookahead-hours 48 \
  --save-snapshot observed.json \
  --output result.json --markdown result.md \
  --fail-on-gaps
```

Install `sqlalchemy` and a compatible PostgreSQL driver (`psycopg2-binary`
for the example) only for this mode. The command exits 2 if any required
raw advisory is absent, 1 for errors, 0 otherwise. It does not update tables.
DB snapshot metadata indicates what was scanned. Missing/inaccessible tables
are **not** silently interpreted as empty output.

## Data contract

- `expected_advisories`: independent records keyed by `(storm_id, issued_at)`
  with an audit `source_ref` for each; every advisory expects `raw_tracks`.
- `observations`: key `(storm_id, issued_at, stage)` and observed `row_count`.
  Row presence is *not* proof of successful processing.
- `scanned_stages`: required explicit list. A stage never scanned cannot yield
  an absence finding. A source scan failure prevents downstream inferences.
- `expected_completions`: optional timestamps and admin-level marker
  expectations. These are **issuance-wide**, not storm-specific.
- `completion_markers`: optional observed markers, queried from
  `storms.exposure_completion` in DB mode.
- `as_of`: optional snapshot cutoff; advisories expected after the cutoff
  are refused. Always supply it for operational evidence.
- Every report includes `source_assurance` and `snapshot_assurance`.

Findings are limited to:

| Code | Interpretation |
|---|---|
| `EXPECTED_RAW_ABSENT` | Independently expected advisory is absent **relative to provided source and scanned snapshot**. Verify source completeness and ingestion timing. |
| `NO_STAGE_ROWS` | Raw input exists, but no rows in a stage explicitly expected by operator; may be a legitimate no-data case. |
| `NO_EXPOSURE_EVIDENCE` | No exposure rows; *informational only*, because zero population intersection is possible. |
| `MISSING_COMPLETION_MARKER` | Missing explicitly expected whole-issuance/admin-level marker; could indicate partial processing. |
| `POSSIBLY_STALE_CUMULATIVE` | A later observed-derived artifact exists after a missing earlier advisory of the same storm. Geometry change is **not** yet proven. |

The current version does not audit WSP-specific issued times; WSP and track
advisories have different issuance clocks. It does not fetch NHC archives or
automatically determine what products the NHC should have published.

## Security and operational constraints

- No deployment, scheduler, database writes, or notifications.
- Database identifiers are hard-coded allow-lists; storm values are SQL bound
  parameters. The collector only issues `SELECT` in a read-only transaction.
- No credentials are logged or included in artifacts.
- No automatic backfills. Any repair must be separately reviewed and tested
  by OCHA maintainers.
- No claims about actual displaced people, lives saved, or financial impact.

## Suggested upstream sequence

1. Share the offline proof and agree with maintainers on the authoritative
   expected-advisory catalog and staging-table eligibility rules.
2. On read-only DEV credentials, capture an explicit raw/derived snapshot
   for a selected archived storm and compare it to independently collected
   NHC products. Audit false positives, empty stages, and completion markers.
3. Run a blinded historical replay (the September incident or another case)
   against an archived, time-consistent snapshot. Measure gap recall and false
   alarm rate against maintainer-reviewed truth labels.
4. Only after validation, propose optional scheduled *read-only* monitoring.
   Alerting, backfills, and production integrations require separate approval.

See [`methodology.md`](methodology.md) and [`PR_PROPOSAL.md`](PR_PROPOSAL.md) for details.
