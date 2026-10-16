# Reliable NHC event discovery with periodic archive reconciliation

**Status:** offline prototype; no NOAA fetches, OCHA production credentials,
Databricks job triggers, operational alerts, or changes to schedules. The
simulations use a selected, incomplete NOAA source catalog or explicitly
synthetic burst inputs. This design is **not a guarantee of zero missed
advisories**, nor proof of observed OCHA data loss or operational savings.

## Critical improvement over the earlier event-driven proposal

A latest-only feed is a lossy *change hint*, even when polled frequently.
Two products can be published between polls; the feed may expose only the
newer one. A feed outage can skip arbitrarily many updates. As a result,
"poll metadata every 30 minutes and dispatch if changed" **does not
provide source completeness**.

The redesign separates four concerns:

1. **Fast hint path:** frequent cheap feed metadata observations, persisting
   any identifiable NOAA product. Duplicate signals have no effect.
2. **Independent reconciliation:** periodically enumerate *all* available
   products in a bounded NOAA archive window; compare product identities
   against the durable queue and add older omitted events. A 200 OK response
   is NOT enough to certify that the archive scan was exhaustive. Failed
   scans cannot advance source coverage or delete previous records.
3. **Durable dispatch ledger:** single-host SQLite reference queue with
   transactional inserts and unique storm/issuance/product identities.
   Separately classify `queued`, `leased`, `verification_required`,
   `acknowledged`, `verified`, and `quarantined` states. No network or
   production job launches are implemented here.
4. **Independent result verification:** a worker receipt is weaker than
   actual downstream completion. After a timed-out or ambiguous launch,
   **do not retry blindly**: compare against a real, independently verified
   downstream per-product result. The currently published OCHA
   `storms.exposure_completion` marker is issuance-wide, not storm-specific,
   so it is insufficient evidence for per-storm verification by itself.

### State transitions

```text
signal / archive discovery
          |
          v
        queued  <-------------------------------+
          |                                     |
          v                                     |
        leased -- confirmed no job started -----+  (bounded backoff)
          |
          +-- explicit worker receipt --> acknowledged --> independent verification --> verified
          |
          +-- lease expired / uncertain result --> verification_required
                                                     |             |
                                              verified absent   verified complete
                                                     |             |
                                                  queued         verified
          +-- source identity conflict --> quarantined (manual source review)
```

If a worker times out, its external job may still be running or may have
succeeded. Fenced lease tokens reject stale results **inside SQLite**, but
they cannot enforce exactly-once effects in a remote Databricks process.
Provider-specific idempotency and read-after-write result reconciliation are
required before any production integration.

### Cost/latency guardrails

- Discovery and reconciliation are lightweight **hypotheses**, not measured
  Cloudflare/Databricks costs. NOAA rate limits and fair use must be checked.
- Run planning groups newly discovered products, imposes a configurable
  cooldown between expensive batches, and caps simulated daily heavy batches.
- **Never throw away discovered advisories when budget is exhausted.** Keep a
  visible undispatched backlog. A future operations integration should age
  and escalate that backlog, not silently claim completion.
- Return `coverage_unestablished` when only an incomplete archive sample is
  available, even if every observed job has been acknowledged.
- Source archive history can be incomplete, revised or delayed; periodic
  reconciliation cannot recreate an event omitted from *all* sources.
- NOAA source acquisition/publishing time, when a product *first* became
  available, must be measured independently before claiming operational
  information latency.

## Reproduce locally (Python standard library; pytest only for tests)

```bash
python -m pytest -q tests/test_resilient_event_recovery.py \
  tests/test_noaa_source_policy.py tests/test_nhc_advisory_audit.py

# Offline counterfactual: source-limited October 1 sample, not production data.
python -m storm_audit.event_recovery \
  --manifest examples/noaa_2026_verified_subset.json \
  --start 2026-10-01T00:00:00Z --until 2026-10-02T00:00:00Z \
  --feed-minutes 30 --archive-hours 6 \
  --dispatch-cooldown 60 --daily-batch-cap 8 \
  --output /tmp/recovery.json

# Local durable queue; does NOT start processing jobs.
python -m storm_audit.resilient_dispatch --db /tmp/nhc_audit_queue.sqlite \
  ingest --source archive --manifest examples/noaa_2026_verified_subset.json \
  --now 2026-10-03T00:00:00Z
python -m storm_audit.resilient_dispatch --db /tmp/nhc_audit_queue.sqlite \
  status --now 2026-10-03T00:00:00Z
```

### Replayed failure matrix

The provided test cases cover:

| Failure scenario | Required behavior |
|---|---|
| Two advisories between polls | Feed may miss older; later archive scan can recover it |
| Feed unavailable during an outage | No success claim; a later successful archive scan may backfill |
| Archive scan fails/has partial coverage | Preserve history; coverage remains unknown |
| Same signal received repeatedly | One durable product identity and one queued work unit |
| Source product contradicts prior identity | Quarantine, no silent overwrite |
| Multiple workers claim jobs concurrently | SQLite transaction + leases prevent duplicate *local* claims |
| Worker killed or dispatch outcome ambiguous | Enter verification required, no automatic costly re-run |
| Proof that remote job never started | Explicit downstream evidence permits a backoff-controlled retry |
| Work is acknowledged but outputs unverified | Keep acknowledgement distinct from verified completion |
| Run budget exhausted | Keep queued work and report backlog |
| WSP versus track products | Separate namespace; no inference that their issuance clocks match |
| Exhaustive NOAA catalog unavailable | Never claim complete source coverage |

### Evidence hierarchy and handoff requirements

This prototype validates state-machine logic using deterministic failures and
source-listed scenarios. Before real integration with OCHA, require:

1. A complete, independently reviewed NOAA advisory inventory for a defined
   storm/time window, including revised and intermediate products, with
   original files/hashes and fetch/availability timestamps.
2. Agreement with maintainers on which products are *eligible* for ingestion,
   whether policy intentionally skips intermediate updates, and how track
   versus WSP products should be handled.
3. Immutable per-product (storm, issuance, product/version) processing
   records. Verify whether their current DB/Databricks schema can support
   them; do not pretend issuance-wide `exposure_completion` is sufficient.
4. A non-production replay across representative storm seasons, including
   observed publication delays, source failures, job crashes, and incident
   periods such as 2026-09-24. Compare outputs with existing downstream
   Haiti/Cuba monitoring and record error/latency/cost tradeoffs.
5. An externally operated scheduling/queueing design with distributed
   transactions, credential scoping, deduplication and exactly-once-*effects*
   safeguards. The SQLite model is not a substitute for those controls.
6. Explicit maintainer approval, staged shadow mode and rollback procedures
   before connecting this work to an operational storm pipeline.

**Acceptance goal:** no *silent* known source omissions in an independently
verified bounded source window, no false report of success with unverified
coverage, and deterministic recovery under tested, documented failure
assumptions. A universal guarantee of no missed NOAA advisories is impossible
without an actually complete and continuously available independent source.

### Source version caveat

If an independently retrieved NOAA source body has a trusted SHA-256 digest,
include it as `content_sha256` (64 hex characters) on an ingested product.
The queue fingerprints it alongside the storm, nominal issuance time,
product identifier and source URL. A **different hash for the same identity
is quarantined** rather than silently replacing processed input.
Products with only URLs and no source-body hashes cannot detect revisions
published at the same URL; their provenance is explicitly weaker.

The `wsp` queue namespace currently provides isolation only, not a complete
WSP data model. Real WSP archives and issuance cycles do not necessarily map
to per-storm advisory IDs, so the full identity and completion contract for
WSP must be reviewed separately before any production connection.
