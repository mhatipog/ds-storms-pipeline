# Suggested first upstream discussion / pull request

**Title:** Add independent read-only NHC advisory completeness audit (prototype)

**Links:** [Issue #20](https://github.com/OCHA-DAP/ds-storms-pipeline/issues/20),
[historical NHC outage recovery #53](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/53),
[completion marker fix #46](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/46).

## Motivation

Exposure-completion markers distinguish finished from unfinished work for an
*already selected* issuance. They do not establish that every advisory
published by the NHC was selected in the first place. Issue #20 documents an
explicit global-maximum-timestamp failure mode. The September 2026 outage
provides a documented recovery case for missing advisory inputs and cumulative
staleness.

## Scope

This adds an optional offline, read-only auditor, with an external advisory
manifest, scanned table snapshots, and evidence-based findings. It performs
no job scheduling, database writes, or production deployment.

It deliberately does not infer advisories from a fixed schedule, does not
consider a lack of exposure rows proof of failure, and labels later
cumulative artifacts as **possibly stale**, requiring actual replays.

## Tests

- 28 local pytest cases: outage reconstruction, clean controls, randomized
  omission injection, source/snapshot scope checks, as-of cutoff,
  anti-cascading assertions, issuance-wide completion markers, and SQL
  read-only transaction assertions.
- The September example is synthetic and **not an actual historical production
  measurement**.

## Questions for maintainers

1. Is the source-to-downstream reconciliation already solved elsewhere in the
   live monitoring stack? If so, where should this check integrate instead?
2. Which independent NHC advisory catalog should be treated as authoritative,
   including intermediate/special advisories?
3. Which production stages may legitimately omit rows for a given advisory?
4. Can we inspect a maintainer-approved read-only archived DEV snapshot to
   benchmark precision and recall before any operational integration?
5. Are the existing completion-marker records always per issuance/admin level
   rather than per storm (as documented in #46)?

## Explicit non-goals

Changing NHC orchestration, adding another hosted app, touching operational
alert triggers, auto-backfilling data, or quantifying affected populations
without archived replay evidence. Those would be independent, reviewed PRs.
