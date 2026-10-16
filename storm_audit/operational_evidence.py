"""Fail-closed operational-evidence join for bounded NOAA advisory research.

No network, DB access, or production actions. A read-only database EXPORT
can be supplied later by an authorised OCHA operator; without it, every
operational outcome is explicitly unknown. An export taken today cannot prove
what was present in a historic Databricks run.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from .core import iso, parse_time
from .bounded_day_study import check_inventory


class EvidenceError(ValueError):
    pass


def _key(row: dict) -> tuple[str, str]:
    sid = row.get("storm_id")
    if not isinstance(sid, str) or not sid.strip():
        raise EvidenceError("storm_id required")
    return sid.strip().upper(), iso(parse_time(row["issued_at"]))


def classify_operational(
    manifest: dict[str, Any], reviewed_index: dict[str, Any],
    export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile eight independently listed advisories to evidence *provided*.

    The optional export contract requires explicit snapshot/coverage metadata.
    Current database state != historical state: never report a historically
    missing advisory from a current-state-only scan.
    """
    catalog = check_inventory(manifest, reviewed_index)
    allowed = {_key(r) for r in manifest["expected_advisories"]}
    counts: Counter[str] = Counter()
    got: dict[tuple[str, str], int] = {}
    assurance = "no_operational_export"
    export_meta: dict[str, Any] = {}
    if export is not None:
        if export.get("schema_version") != 1:
            raise EvidenceError("Unsupported operational export schema")
        if export.get("table") != "storms.nhc_tracks_geo":
            raise EvidenceError("Only exact raw track table is recognized")
        if export.get("storm_id") != catalog["storm_id"]:
            raise EvidenceError("Operational storm does not match source inventory")
        start = parse_time(export["scope_start"])
        until = parse_time(export["scope_until"])
        if start > parse_time(catalog["start"]) or until < parse_time(catalog["until"]):
            raise EvidenceError("Export must cover entire audited UTC day")
        if start >= until:
            raise EvidenceError("Invalid export interval")
        if export.get("query_status") != "succeeded" or export.get("coverage") != "full_bounded_scan":
            raise EvidenceError("Operational export did not attest a full successful scan")
        scanned_at = parse_time(export["exported_at"])
        is_historical = export.get("snapshot_type") == "historical_asof"
        if export.get("snapshot_type") not in ("current_state", "historical_asof"):
            raise EvidenceError("Distinguish current state from a historical snapshot")
        if is_historical:
            source_asof = parse_time(export["snapshot_as_of"])
            if source_asof > scanned_at:
                raise EvidenceError("Historical source snapshot cannot be later than export")
            if source_asof < parse_time(catalog["until"]):
                raise EvidenceError("Historical snapshot precedes end of the audited day; future advisories cannot be called missing")
        else:
            if export.get("snapshot_as_of") is not None:
                raise EvidenceError("Current-state export may not claim historical as-of")
            source_asof = None
        rows = export.get("rows")
        if not isinstance(rows, list):
            raise EvidenceError("Operational rows must be a list (can be empty)")
        for row in rows:
            key = _key(row)
            if key not in allowed:
                raise EvidenceError(f"Out-of-scope operational row {key}")
            n = row.get("row_count")
            if type(n) is not int or n <= 0:
                raise EvidenceError("Included rows require strictly positive integer count")
            if key in got:
                raise EvidenceError("Duplicate operational issuance")
            got[key] = n
        assurance = "operator_attested_historical_snapshot" if is_historical else "operator_attested_current_state"
        export_meta = {
            "exported_at": iso(scanned_at),
            "snapshot_as_of": iso(source_asof) if source_asof else None,
            "source_snapshot_type": export["snapshot_type"],
            "historical_ingestion_time_verifiable": False,
            "operator_attestation_not_independently_verified": True,
        }
    records = []
    for a in manifest["expected_advisories"]:
        key = _key(a)
        if export is None:
            verdict = "operational_evidence_unavailable"
        elif key in got:
            verdict = "row_present_in_export_not_original_ingestion_time"
        elif assurance == "operator_attested_current_state":
            verdict = "row_absent_from_current_export_not_proof_of_historical_omission"
        else:
            verdict = "row_absent_from_attested_historical_snapshot_requires_review"
        counts[verdict] += 1
        records.append({
            "storm_id": key[0], "issued_at": key[1], "product_id": a["product_id"],
            "source_url": a["source_ref"], "operational_row_count": got.get(key),
            "operational_verdict": verdict,
        })
    return {
        "kind": "source_versus_optional_attested_export_not_production_audit",
        "source_index": catalog["index_url"],
        "source_listed_public_advisories": len(allowed),
        "operational_export_assurance": assurance,
        "operational_metadata": export_meta,
        "counts": dict(sorted(counts.items())),
        "records": records,
        "all_advisories_verified_processed": False,
        "limitations": [
            "NOAA product index proves a listed source product, not original feed availability.",
            "No OCHA production database, job logs, or exposure tables were accessed by this tool.",
            "Even rows in an attested historical snapshot do not prove original ingestion latency or downstream completeness.",
            "A current-state export cannot prove what the pipeline held on the historical event date.",
            "Advisory source and OCHA operational availability may differ; manual eligibility review required.",
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--reviewed-index", required=True)
    p.add_argument("--operational-export", help="Optional approved, read-only JSON export")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    load = lambda f: json.loads(Path(f).read_text(encoding="utf8"))
    result = classify_operational(load(args.manifest), load(args.reviewed_index),
             load(args.operational_export) if args.operational_export else None)
    Path(args.output).write_text(json.dumps(result, indent=2)+"\n", encoding="utf8")
    print(json.dumps({"source_listed":result["source_listed_public_advisories"],
                      "operational_export_assurance":result["operational_export_assurance"],
                      "counts":result["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
