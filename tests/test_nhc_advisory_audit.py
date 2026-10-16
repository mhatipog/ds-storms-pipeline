"""Pure deterministic tests: no network, credentials or operational tables."""
import copy
import json
from pathlib import Path
import random

import pytest

from storm_audit.core import audit, iso, parse_time, markdown_report
from storm_audit.collector import TABLES
from storm_audit.__main__ import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def incident():
    return (json.loads((EXAMPLES / "2026-09-24-incident-manifest.json").read_text()),
            json.loads((EXAMPLES / "2026-09-24-synthetic-snapshot.json").read_text()))


def stages_for(manifest):
    seen = set()
    for adv in manifest["expected_advisories"]:
        for stage in adv["required_stages"]:
            seen.add((adv["storm_id"], adv["issued_at"], stage))
    return sorted(seen)


def full_snapshot(manifest):
    return {
        "schema_version": 1,
        "scanned_stages": list(TABLES),
        "observations": [
            {"storm_id": storm, "issued_at": t, "stage": stage, "row_count": 1}
            for storm, t, stage in stages_for(manifest)
        ],
    }


def counts(manifest, snapshot):
    return audit(manifest, snapshot)["counts"]


def test_september_scenario_finds_all_20_documented_gaps():
    manifest, snapshot = incident()
    assert len(manifest["expected_advisories"]) == 24
    result = audit(manifest, snapshot)
    assert result["counts"]["EXPECTED_RAW_ABSENT"] == 20
    assert result["counts"]["POSSIBLY_STALE_CUMULATIVE"] == 16
    assert result["scope"]["storms"] == 4
    assert not any(f["code"] == "NO_STAGE_ROWS" for f in result["findings"])


def test_clean_full_snapshot_has_no_findings():
    manifest, _ = incident()
    result = audit(manifest, full_snapshot(manifest))
    assert result["counts"] == {}
    assert result["status"] == "no_findings_in_scanned_scope"


def test_detection_is_independent_of_record_order():
    manifest, snapshot = incident()
    expected = counts(manifest, snapshot)
    random.Random(143).shuffle(manifest["expected_advisories"])
    random.Random(211).shuffle(snapshot["observations"])
    assert counts(manifest, snapshot) == expected


def test_duplicate_manifest_is_rejected():
    manifest, snapshot = incident()
    manifest["expected_advisories"].append(copy.deepcopy(manifest["expected_advisories"][0]))
    with pytest.raises(ValueError, match="Duplicate expected advisory"):
        audit(manifest, snapshot)


def test_duplicate_snapshot_observation_is_rejected():
    manifest, snapshot = incident()
    snapshot["observations"].append(copy.deepcopy(snapshot["observations"][0]))
    with pytest.raises(ValueError, match="Duplicate observation"):
        audit(manifest, snapshot)


def test_missing_raw_scan_gives_no_false_claim():
    manifest, snapshot = incident()
    snapshot["scanned_stages"].remove("raw_tracks")
    snapshot["observations"] = [r for r in snapshot["observations"] if r["stage"] != "raw_tracks"]
    result = audit(manifest, snapshot)
    assert result["counts"].get("EXPECTED_RAW_ABSENT", 0) == 0
    assert result["status"] == "incomplete_evidence"
    assert "raw_tracks" in result["scope"]["unscanned_required_stages"]


def test_other_storm_gap_does_not_taint_healthy_storm():
    manifest, snapshot = incident()
    target = "AL062026"
    manifest["expected_advisories"] = [a for a in manifest["expected_advisories"] if a["storm_id"] == target]
    r = audit(manifest, snapshot)
    assert all(f["storm_id"] == target for f in r["findings"])


def test_absent_exposure_rows_are_only_informational():
    manifest, snap = incident()
    manifest["expected_advisories"] = [a for a in manifest["expected_advisories"] if a["issued_at"].startswith("2026-09-25")]
    for a in manifest["expected_advisories"]:
        a["required_stages"].append("forecast_exposure")
    r = audit(manifest, snap)
    assert r["counts"].get("NO_EXPOSURE_EVIDENCE") == 4
    assert not r["counts"].get("EXPECTED_RAW_ABSENT", 0)
    assert all(f["severity"] == "info" for f in r["findings"])


def test_missing_raw_suppresses_descendant_alarm_flood():
    manifest, snap = incident()
    r = audit(manifest, snap)
    assert r["counts"].get("NO_STAGE_ROWS", 0) == 0
    assert r["counts"]["EXPECTED_RAW_ABSENT"] == 20


def test_detects_missing_buffer_only_when_raw_exists_and_stage_scanned():
    manifest, snap = incident()
    snap["observations"] = [r for r in snap["observations"] if not (
        r["storm_id"] == "AL062026" and r["stage"] == "forecast_buffers" and r["issued_at"].startswith("2026-09-25"))]
    result = audit(manifest, snap)
    assert result["counts"].get("NO_STAGE_ROWS", 0) == 1


def test_timestamps_require_timezone_and_normalize():
    assert iso(parse_time("2026-09-25T05:00:00+02:00")) == "2026-09-25T03:00:00Z"
    with pytest.raises(ValueError, match="missing UTC offset"):
        parse_time("2026-09-25T03:00:00")


def test_invalid_negative_and_bool_counts_are_rejected():
    manifest, snap = incident()
    snap["observations"][0]["row_count"] = -1
    with pytest.raises(ValueError, match="row_count"):
        audit(manifest, snap)
    snap["observations"][0]["row_count"] = True
    with pytest.raises(ValueError, match="row_count"):
        audit(manifest, snap)


def test_source_reference_required():
    manifest, snap = incident()
    del manifest["expected_advisories"][0]["source_ref"]
    with pytest.raises(ValueError, match="source_ref"):
        audit(manifest, snap)


def test_scan_scope_enforced():
    manifest, snap = incident()
    snap["scanned_stages"] = ["raw_tracks"]
    with pytest.raises(ValueError, match="not scanned"):
        audit(manifest, snap)


def test_markdown_report_is_machine_result_based():
    manifest, snap = incident()
    report = markdown_report(audit(manifest, snap))
    assert "EXPECTED_RAW_ABSENT`" in report
    assert "20" in report
    assert "WSP products use" in report


def test_cli_writes_json_markdown_and_exit_code(tmp_path):
    jout, mout = tmp_path / "a.json", tmp_path / "a.md"
    rc = main(["--manifest", str(EXAMPLES / "2026-09-24-incident-manifest.json"),
               "--snapshot", str(EXAMPLES / "2026-09-24-synthetic-snapshot.json"),
               "--output", str(jout), "--markdown", str(mout), "--fail-on-gaps"])
    assert rc == 2
    assert json.loads(jout.read_text())["counts"]["EXPECTED_RAW_ABSENT"] == 20
    assert "Independent NHC" in mout.read_text()


def test_randomly_injected_missing_advisories_report_exact_gap_count():
    manifest, _ = incident()
    for seed in range(50):
        rand = random.Random(seed)
        snap = full_snapshot(manifest)
        missing = {k for k in stages_for(manifest) if k[2] == "raw_tracks" and rand.random() < 0.3}
        snap["observations"] = [row for row in snap["observations"] if (
            row["storm_id"], row["issued_at"], row["stage"]) not in missing]
        out = audit(manifest, snap)
        assert out["counts"].get("EXPECTED_RAW_ABSENT", 0) == len(missing)


def test_collector_allowlist_matches_audited_stages():
    assert set(TABLES) == set(full_snapshot(incident()[0])["scanned_stages"])


def test_refuse_future_advisories_after_snapshot_time():
    manifest, snap = incident()
    snap["as_of"] = "2026-09-24T01:00:00Z"
    with pytest.raises(ValueError, match="later than the snapshot"):
        audit(manifest, snap)


def test_asof_time_can_be_offset_aware():
    manifest, snap = incident()
    snap["as_of"] = "2026-09-25T08:00:00+02:00"
    r = audit(manifest, snap)
    assert r["counts"]["EXPECTED_RAW_ABSENT"] == 20


def test_csv_manifest_builder_parses_explicit_off_cycle_times(tmp_path):
    from storm_audit.build_manifest import build_from_csv
    p = tmp_path / "catalog.csv"
    p.write_text("storm_id,issued_at,source_ref,required_stages\n"
                 "AL062026,2026-09-24T16:30:00Z,https://example.com/advisory,raw_tracks|forecast_buffers\n")
    m = build_from_csv(str(p))
    assert m["expected_advisories"][0]["issued_at"] == "2026-09-24T16:30:00Z"
    assert m["source_assurance"] == "unverified"


def test_csv_manifest_builder_rejects_invalid_stage(tmp_path):
    from storm_audit.build_manifest import build_from_csv
    p = tmp_path / "catalog.csv"
    p.write_text("storm_id,issued_at,source_ref,required_stages\n"
                 "AL062026,2026-09-24T16:30:00Z,https://example.com/advisory,not_a_stage\n")
    with pytest.raises(ValueError, match="Invalid required_stages"):
        build_from_csv(str(p))


def test_partial_exposure_markers_detected_at_issuance_level():
    manifest, snapshot = incident()
    manifest["expected_completions"] = [{
        "stage": "forecast_exposure", "issued_at": "2026-09-25T03:00:00Z",
        "admin_levels": [0, 1], "source_ref": manifest["incident_ref"],
    }]
    snapshot["completion_scanned"] = True
    snapshot["completion_markers"] = [{"stage": "forecast_exposure",
        "issued_at": "2026-09-25T03:00:00Z", "admin_level": 0}]
    r = audit(manifest, snapshot)
    assert r["counts"]["MISSING_COMPLETION_MARKER"] == 1
    issue = next(f for f in r["findings"] if f["code"] == "MISSING_COMPLETION_MARKER")
    assert issue["storm_id"] == "(issuance-wide)"
    assert "admin_level:1" in issue["evidence"]


def test_completion_unscanned_never_falsely_flags_missing_markers():
    manifest, snapshot = incident()
    manifest["expected_completions"] = [{
        "stage": "observed_exposure", "issued_at": "2026-09-25T03:00:00Z",
        "admin_levels": [0], "source_ref": manifest["incident_ref"],
    }]
    r = audit(manifest, snapshot)
    assert "exposure_completion" in r["scope"]["unscanned_required_stages"]
    assert r["counts"].get("MISSING_COMPLETION_MARKER", 0) == 0


def test_completion_marker_without_scan_rejected():
    manifest, snapshot = incident()
    snapshot["completion_markers"] = [{
        "stage": "forecast_exposure", "issued_at": "2026-09-25T03:00:00Z",
        "admin_level": 0,
    }]
    with pytest.raises(ValueError, match="without scanning"):
        audit(manifest, snapshot)


def test_all_completion_markers_present_is_not_an_alarm():
    manifest, snapshot = incident()
    manifest["expected_completions"] = [{
        "stage": "forecast_exposure", "issued_at": "2026-09-25T03:00:00Z",
        "admin_levels": [0, 1], "source_ref": manifest["incident_ref"],
    }]
    snapshot["completion_scanned"] = True
    snapshot["completion_markers"] = [
        {"stage": "forecast_exposure", "issued_at": "2026-09-25T03:00:00Z", "admin_level": n} for n in [0,1]
    ]
    r = audit(manifest, snapshot)
    assert r["counts"].get("MISSING_COMPLETION_MARKER", 0) == 0


def test_postgres_collector_uses_read_only_transaction_and_selects_only(monkeypatch):
    import sqlalchemy
    from storm_audit.collector import collect_postgres
    from contextlib import nullcontext
    statements = []

    class Rows:
        def __init__(self, scalar_value="storms.present"):
            self.scalar_value = scalar_value
        def scalar(self):
            return self.scalar_value
        def mappings(self):
            return self
        def all(self):
            return []
    class FakeConnection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def begin(self):
            return nullcontext()
        def exec_driver_sql(self, sql):
            statements.append(str(sql))
        def execute(self, sql, params=None):
            statements.append(str(sql))
            return Rows()
    class FakeEngine:
        def connect(self):
            return FakeConnection()
        def dispose(self):
            pass
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **kw: FakeEngine())
    manifest, _ = incident()
    snapshot = collect_postgres(manifest, "postgresql://nobody:password@fake/readonly")
    assert snapshot["completion_scanned"]
    assert snapshot["snapshot_assurance"] == "database_read_only"
    assert set(snapshot["scanned_stages"]) == set(TABLES)
    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert all(s.startswith(("SET TRANSACTION READ ONLY", "SELECT")) for s in statements)


def test_collector_skips_nonexistent_tables_without_missing_claim(monkeypatch):
    import sqlalchemy
    from storm_audit.collector import collect_postgres
    from contextlib import nullcontext
    class NoTable:
        def scalar(self):
            return None
    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def begin(self): return nullcontext()
        def exec_driver_sql(self, sql): pass
        def execute(self, sql, params=None):
            return NoTable()
    class Engine:
        def connect(self): return Conn()
        def dispose(self): pass
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **kw: Engine())
    manifest, _ = incident()
    snap = collect_postgres(manifest, "postgresql://localhost/fake")
    assert snap["scanned_stages"] == []
    assert len(snap["scan_warnings"]) == 8
    result = audit(manifest, snap)
    assert result["counts"] == {}
    assert result["status"] == "incomplete_evidence"
