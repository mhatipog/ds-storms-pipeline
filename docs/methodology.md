# Methodology and evaluation protocol

## Why another auditor when completion markers exist?

OCHA's [PR #46](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/46)
correctly introduced per-issuance/per-admin-level exposure-completion markers
to distinguish partial processing from successful completion. Those markers
measure **whether a submitted computation finished**. They cannot, by
themselves, answer **whether every expected NHC storm advisory was submitted**.
This separate audit tests that source-to-processing reconciliation problem.

## Claims hierarchy

1. **Presence proof**: output rows exist for a given work unit.
2. **Independent completeness**: source manifest from external NHC products
   contains an advisory and the ingestion snapshot does not. This is only as
   strong as the independently verified NHC manifest and snapshot's `as_of`.
3. **Processing-completion proof**: every required marker for an issuance is
   present, under the operational semantics of PR #46. Not storm-specific.
4. **Staleness candidate**: an advisory missing from raw could affect later
   cumulative wind swaths for the same storm, but replay must quantify actual
   geometry/population differences before describing outputs as corrupted.
5. **Humanitarian decision impact**: must be established from authorized
   downstream monitoring, not inferred from missing rows alone.

## Historical September 2026 counterfactual

Source: OCHA storm pipeline [PR #53](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/53).
The source PR describes a prod connection outage 2026-09-24, the missing
advisories for four storms, and stale derived products after the gap. Its
repair was reported as run/verified October 8, merged October 13.

This prototype's `examples/2026-09-24-incident-manifest.json` builds 20
expected earlier advisories plus four **synthetic** later products. The
synthetic snapshot withholds those 20 earlier raw records and includes later
products. A correct auditor must: (i) identify exactly 20 missing raw
advisories, (ii) flag later cumulative products of the *same storms*,
(iii) avoid cascading `NO_STAGE_ROWS` for downstream stages whose raw source
is missing, (iv) not report source gaps when raw was not actually scanned,
and (v) return no warnings on an entirely consistent complete synthetic
snapshot.

This is a proof of algorithm behavior, **not** a historical blind replay.
Actual evaluation requires independently archived NHC product metadata,
actual time-consistent snapshots, and a maintainer-labelled impact set.

## Proposed real-world experiment

- Register a fixed test window and storms before viewing downstream output.
- Gather NHC archive product IDs and UTC issuance timestamps from a source
  independent of the database, including special advisories.
- Review expected stage eligibility per storm and issuance (forecast wind radii,
  observed leadtime, valid WSP products) with maintainers.
- Capture immutable, timestamped table snapshots in read-only mode, with hashes
  of the manifest and output.
- Blindly label incident windows with known good/missing inputs, with two
  reviewers where feasible.
- Compute true-positive, false-positive, false-negative counts separately for
  missing raw advisory detection and downstream staleness candidates.
- Replay downstream derivations on isolated test data to measure area and
  population exposure deltas; report uncertainty from source revisions.
- Preserve an operator-readable report with complete evidence and the exact
  source rows responsible for each finding.

## Known limitations

- Published NHC archives may have multiple product types/advisory numbering
  and delayed appearance; comparing to a guessed regular schedule is invalid.
- `atcf_id` can differ from display names and might require verified mapping.
- Completeness markers are not equivalent to source catalog completeness.
- Row presence is weaker than computation completeness, and zero-exposure
  stages can legitimately produce zero rows.
- WSP products have an issuance clock distinct from tracks and are not checked
  in this first implementation.
- Later cumulative artifacts are *possibly*, not necessarily, geometrically
  stale if previous advisories were unavailable. Some missing observations may
  contribute no additional wind area.
- Read-only database access is optional and **has not been tested against
  OCHA's real environment**. SQL matches publicly reviewed source code.
- Current reported recall is from deterministic injected failures only and
  must not be presented as a production sensitivity estimate.
