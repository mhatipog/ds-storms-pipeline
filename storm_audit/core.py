"""Deterministic, read-only reconciliation of archived NHC advisories.

No persistence, networking, or imports from the operational storm pipeline.
Input evidence is never silently inferred from the processing outputs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
STAGES = (
    "raw_tracks",
    "forecast_buffers",
    "observed_buffers",
    "forecast_only_buffers",
    "forecast_exposure",
    "observed_exposure",
    "forecast_only_exposure",
)
# If there are no exposure rows, it can mean there is no exposed population.
# Empty/missing buffers are much stronger evidence, but still need eligibility.
EXPOSURE_STAGES = frozenset(x for x in STAGES if x.endswith("_exposure"))
# Only these stages consume the *cumulative* observed wind swath.
CUMULATIVE_STAGES = frozenset((
    "observed_buffers", "observed_exposure",
    "forecast_only_buffers", "forecast_only_exposure",
))
# Missing a predecessor makes a descendant absence explainable, not a new root cause.
UPSTREAM = {
    "raw_tracks": (),
    "forecast_buffers": ("raw_tracks",),
    "observed_buffers": ("raw_tracks",),
    "forecast_only_buffers": ("forecast_buffers", "observed_buffers"),
    "forecast_exposure": ("forecast_buffers",),
    "observed_exposure": ("observed_buffers",),
    "forecast_only_exposure": ("forecast_only_buffers",),
}


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamps must be ISO-8601 strings including timezone")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid timestamp {value!r}") from e
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp missing UTC offset: {value!r}")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_stage(stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage {stage!r}; allowed: {', '.join(STAGES)}")


@dataclass(frozen=True, order=True)
class Key:
    storm_id: str
    issued_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Key:
        name = data.get("storm_id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each row must have a non-empty storm_id")
        return cls(name.strip().upper(), parse_time(data["issued_at"]))

    def to_dict(self) -> dict[str, str]:
        return {"storm_id": self.storm_id, "issued_at": iso(self.issued_at)}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    storm_id: str
    issued_at: str
    stage: str
    description: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = list(self.evidence)
        return result


def validate_manifest(manifest: dict[str, Any]) -> tuple[dict[Key, dict], set[str]]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Manifest schema_version must be {SCHEMA_VERSION}")
    if not isinstance(manifest.get("expected_advisories"), list):
        raise ValueError("Manifest must have expected_advisories list")
    expected: dict[Key, dict] = {}
    for row in manifest["expected_advisories"]:
        key = Key.from_dict(row)
        if key in expected:
            raise ValueError(f"Duplicate expected advisory: {key.to_dict()}")
        source_ref = row.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValueError(f"Expected advisory lacks independent source_ref: {key.to_dict()}")
        required = row.get("required_stages", ["raw_tracks"])
        if not isinstance(required, list) or not required:
            raise ValueError("required_stages must be a non-empty list")
        for stage in required:
            _validate_stage(stage)
        if "raw_tracks" not in required:
            raise ValueError("Each expected advisory must require raw_tracks")
        expected[key] = {"source_ref": source_ref, "required_stages": tuple(dict.fromkeys(required))}
    return expected, {x.storm_id for x in expected}


def _get_snapshot(snapshot: dict[str, Any]) -> tuple[dict[tuple[Key, str], dict], set[str]]:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Snapshot schema_version must be {SCHEMA_VERSION}")
    scanned = snapshot.get("scanned_stages")
    if not isinstance(scanned, list):
        raise ValueError("Snapshot must explicitly list scanned_stages (can be empty)")
    for stage in scanned:
        _validate_stage(stage)
    if not isinstance(snapshot.get("observations"), list):
        raise ValueError("Snapshot must have observations list")
    obs = {}
    for row in snapshot["observations"]:
        key = Key.from_dict(row)
        stage = row.get("stage")
        _validate_stage(stage)
        if stage not in scanned:
            raise ValueError(f"Observation for {stage} but it was not scanned")
        count = row.get("row_count")
        if type(count) is not int or count < 0:
            raise ValueError("row_count must be a nonnegative integer")
        item = (key, stage)
        if item in obs:
            raise ValueError(f"Duplicate observation for {item}")
        # row_count > 0 proves presence, NOT complete calculation.
        obs[item] = {"row_count": count, "observed_source": row.get("observed_source", "snapshot")}
    return obs, set(scanned)


def audit(manifest: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Reconcile authoritative expectations against an explicitly scoped snapshot.

    Two kinds of findings:
      EXPECTED_RAW_ABSENT: the manifest asserts an advisory exists;
        the explicitly scanned raw table does not contain it.
      NO_STAGE_ROWS / NO_EXPOSURE_EVIDENCE: *suspicions*, never proof of
        incomplete calculation, because outputs may legitimately be empty.
      POSSIBLY_STALE_CUMULATIVE: missing earlier inputs can invalidate later
        cumulative products. Signals what to *verify*, not definite corruption.
    """
    expected, storm_ids = validate_manifest(manifest)
    observed, scanned = _get_snapshot(snapshot)
    as_of = snapshot.get("as_of")
    if as_of is not None:
        cutoff = parse_time(as_of)
        future = [k for k in expected if k.issued_at > cutoff]
        if future:
            raise ValueError(
                f"{len(future)} expected advisory times are later than the "
                "snapshot as_of time; avoid false missing-advisory alarms"
            )
    findings: list[Finding] = []
    unscanned = set()
    missing_raw: dict[str, list[datetime]] = defaultdict(list)
    unmatched = []
    for key in sorted(expected):
        policy = expected[key]
        for stage in policy["required_stages"]:
            if stage not in scanned:
                unscanned.add(stage)
                continue
            row = observed.get((key, stage))
            if row is not None and row["row_count"] > 0:
                continue
            ref = policy["source_ref"]
            if stage == "raw_tracks":
                missing_raw[key.storm_id].append(key.issued_at)
                findings.append(Finding(
                    "EXPECTED_RAW_ABSENT", "high", key.storm_id,
                    iso(key.issued_at), stage,
                    "Expected advisory absent from the scanned raw tracks table.",
                    (ref, "scanned:raw_tracks"),
                ))
                continue
            if "raw_tracks" not in scanned or not observed.get((key, "raw_tracks"), {}).get("row_count"):
                # Root-cause already recorded above; avoid cascaded false alarms.
                continue
            severity = "info" if stage in EXPOSURE_STAGES else "warning"
            code = "NO_EXPOSURE_EVIDENCE" if stage in EXPOSURE_STAGES else "NO_STAGE_ROWS"
            findings.append(Finding(
                code, severity, key.storm_id, iso(key.issued_at), stage,
                "Expected stage has no output rows; empty output may be legitimate, investigate eligibility/completion.",
                (ref, f"scanned:{stage}"),
            ))
    # A gap in a historical advisory only threatens subsequent products for
    # the *same* storm; don't equate existence of some later rows with proof
    # that they are correct or that missing history changed their geometry.
    stale_seen: set[tuple[Key, str]] = set()
    for times in missing_raw.values():
        times.sort()
    for (key, stage), row in sorted(observed.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if key.storm_id not in storm_ids or stage not in CUMULATIVE_STAGES or row["row_count"] == 0:
            continue
        earlier = missing_raw[key.storm_id]
        prior_count = bisect_left(earlier, key.issued_at)
        if not prior_count:
            continue
        if (key, stage) in stale_seen:
            continue
        stale_seen.add((key, stage))
        findings.append(Finding(
            "POSSIBLY_STALE_CUMULATIVE", "warning", key.storm_id,
            iso(key.issued_at), stage,
            "Derived output exists after missing earlier advisory; replay may change the cumulative swath.",
            (f"{prior_count} missing earlier advisory/advisories", f"earliest_gap:{iso(earlier[0])}"),
        ))
    # Completion markers are a separate assurance signal from presence of
    # rows. The upstream table is keyed by (table, issuance, admin_level),
    # NOT storm ID. Do not wrongly present its absence as storm-specific proof.
    completion_checked = snapshot.get("completion_scanned", False)
    if type(completion_checked) is not bool:
        raise ValueError("completion_scanned must be a bool")
    marker_records = snapshot.get("completion_markers", [])
    if not isinstance(marker_records, list):
        raise ValueError("completion_markers must be a list")
    present_markers: set[tuple[str, datetime, int]] = set()
    for marker in marker_records:
        stage = marker.get("stage")
        _validate_stage(stage)
        if stage not in EXPOSURE_STAGES:
            raise ValueError("Completion markers are only for exposure stages")
        al = marker.get("admin_level")
        if type(al) is not int or al < 0:
            raise ValueError("admin_level must be a nonnegative integer")
        if not completion_checked:
            raise ValueError("Cannot claim completion marker without scanning completion table")
        present_markers.add((stage, parse_time(marker["issued_at"]), al))
    expectations = manifest.get("expected_completions", [])
    if not isinstance(expectations, list):
        raise ValueError("expected_completions must be a list")
    seen_marker_expectations = set()
    for row in expectations:
        stage = row.get("stage")
        _validate_stage(stage)
        if stage not in EXPOSURE_STAGES:
            raise ValueError("expected_completions must reference exposure stages")
        timestamp = parse_time(row["issued_at"])
        levels = row.get("admin_levels")
        if not isinstance(levels, list) or not levels or any(type(x) is not int or x < 0 for x in levels):
            raise ValueError("admin_levels must be a nonempty list of nonnegative integers")
        if not isinstance(row.get("source_ref"), str) or not row["source_ref"].strip():
            raise ValueError("expected_completions requires source_ref")
        for al in levels:
            mk = (stage, timestamp, al)
            if mk in seen_marker_expectations:
                raise ValueError("Duplicate expected completion marker")
            seen_marker_expectations.add(mk)
            if not completion_checked:
                unscanned.add("exposure_completion")
            elif mk not in present_markers:
                findings.append(Finding(
                    "MISSING_COMPLETION_MARKER", "warning", "(issuance-wide)",
                    iso(timestamp), stage,
                    f"No whole-issuance completion marker for admin_level={al}; partial processing is possible.",
                    (row["source_ref"], f"admin_level:{al}"),
                ))
    severity_rank = {"high": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (severity_rank[f.severity], f.storm_id, f.issued_at, f.stage, f.code))
    counts = Counter(f.code for f in findings)
    coverage_complete = not unscanned and "raw_tracks" in scanned
    any_gap = bool(findings)
    status = (
        "gaps_detected" if any_gap and coverage_complete
        else "gaps_detected_in_partial_scope" if any_gap
        else "incomplete_evidence" if not coverage_complete
        else "no_findings_in_scanned_scope"
    )
    # A clean result does NOT prove completeness beyond explicitly supplied
    # expected advisory list and scanned stages.
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {
            "expected_advisories": len(expected),
            "storms": len(storm_ids),
            "scanned_stages": sorted(scanned),
            "unscanned_required_stages": sorted(unscanned),
            "source_description": manifest.get("source_description", "user-supplied manifest"),
            "snapshot_description": snapshot.get("snapshot_description", "user-supplied snapshot"),
            "source_assurance": manifest.get("source_assurance", "unverified"),
            "snapshot_assurance": snapshot.get("snapshot_assurance", "unverified"),
            "coverage_complete": coverage_complete,
            "snapshot_as_of": as_of or "not_declared",
            "completion_scanned": completion_checked,
        },
        "counts": dict(sorted(counts.items())),
        "findings": [f.to_dict() for f in findings],
        "limitations": [
            "Only advisories explicitly listed in the independent manifest are checked; an incomplete source manifest can conceal gaps.",
            "A finding is relative to the supplied manifest and snapshot, not necessarily proof of actual historical operations; inspect assurance metadata.",
            "Snapshot as_of must be contemporaneous with source availability; this tool cannot infer when an archival source was first published.",
            "The snapshot is evidence of row presence, not computational completion; missing exposure rows can be legitimate.",
            "Exposure completion markers are issued_time/admin_level-wide, never proof of an individual storm run.",
            "Historical-gap propagation signals potentially stale cumulative products, not proven changed geometry or impact.",
            "WSP products use a separate issuance clock and are not assessed by this track-advisory auditor.",
            "This tool performs no production writes and makes no operational alert/funding decisions.",
        ],
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Independent NHC advisory-completeness audit",
        "",
        f"**Result:** `{report['status']}`",
        f"**Source assurance:** `{report['scope']['source_assurance']}`; **snapshot assurance:** `{report['scope']['snapshot_assurance']}`",
        f"**Snapshot as-of:** `{report['scope']['snapshot_as_of']}`",
        f"**Expected advisories:** {report['scope']['expected_advisories']} across {report['scope']['storms']} storms",
        f"**Scanned stages:** {', '.join(report['scope']['scanned_stages']) or 'none'}",
        "",
        "## Findings by type", "",
    ]
    counts = report["counts"]
    if not counts:
        lines.append("No findings in the provided, explicitly scanned scope. This is not a guarantee of complete historical coverage.")
    else:
        for code, n in counts.items():
            lines.append(f"- `{code}`: {n}")
    lines.extend(["", "## Evidence (first 100 findings)", "", "| Level | Storm | Advisory (UTC) | Stage | Finding |", "|---|---|---|---|---|"])
    for f in report["findings"][:100]:
        lines.append(f"| {f['severity']} | {f['storm_id']} | {f['issued_at']} | {f['stage']} | {f['code']} |")
    if len(report["findings"]) > 100:
        lines.append(f"\n{len(report['findings']) - 100} additional findings in machine-readable JSON.")
    lines.extend(["", "## Limitations", ""])
    for note in report["limitations"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
