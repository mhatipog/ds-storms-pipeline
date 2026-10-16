"""Reproducible source verification and regression tests for Nolo 2026-10-01 evidence."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import re

import pytest
from storm_audit.snapshot_timeline import parse_current_storms

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = REPO_ROOT / "noaa-archive"


def test_all_39_snapshots_exist_and_match_sha256_sums():
    sums_file = REPO_ROOT / "SHA256SUMS.txt"
    assert sums_file.exists(), "SHA256SUMS.txt must exist"
    
    lines = sums_file.read_text(encoding="utf-8").strip().splitlines()
    checked = 0
    for line in lines:
        digest, rel_path = line.split(maxsplit=1)
        p = REPO_ROOT / rel_path
        assert p.exists(), f"File {rel_path} in SHA256SUMS.txt must exist"
        actual = sha256(p.read_bytes()).hexdigest()
        assert actual == digest, f"Hash mismatch for {rel_path}"
        if rel_path.startswith("noaa-archive/CurrentStorms_"):
            checked += 1
    assert checked == 39, f"Expected 39 snapshots in SHA256SUMS.txt, found {checked}"


def test_all_39_snapshots_contain_valid_nolo_advisories():
    snapshots = sorted(list(ARCHIVE_DIR.glob("CurrentStorms_2026-10-01-*.json")))
    assert len(snapshots) == 39, "Expected 39 snapshot files"
    
    seen_advisories = set()
    for s in snapshots:
        raw = s.read_bytes()
        parsed = parse_current_storms(raw)
        assert "EP152026" in parsed["active_storm_ids"], f"EP152026 missing in {s.name}"
        pa = parsed["public_advisories"].get("EP152026")
        assert pa is not None, f"publicAdvisory missing in {s.name}"
        adv_num = pa["product_id"]
        assert adv_num in {"41A", "42", "42A", "43", "43A", "44", "44A", "45", "45A"}
        seen_advisories.add(adv_num)
        
    expected_set = {"41A", "42", "42A", "43", "43A", "44", "44A", "45", "45A"}
    assert seen_advisories == expected_set, f"Expected all 9 advisories, found {seen_advisories}"


def test_independent_replay_algorithmic_schedule_simulation():
    replay_path = REPO_ROOT / "independent-replay.json"
    assert replay_path.exists(), "independent-replay.json must exist"
    data = json.loads(replay_path.read_text(encoding="utf-8"))
    
    ocha_sim = data["polling_simulations"]["ocha_6h"]
    assert ocha_sim["captured_advisories"] == ["42", "43", "44", "45"]
    assert ocha_sim["missed_advisories"] == ["41A", "42A", "43A", "44A"]
    assert ocha_sim["intermediate_capture_rate"] == 0.0
    assert ocha_sim["regular_capture_rate"] == 1.0


def test_maintainer_query_references_valid_upstream_schema_columns():
    sql_schema = (REPO_ROOT / "src" / "schemas" / "sql" / "nhc_tables.sql").read_text(encoding="utf-8")
    maintainer_doc = (REPO_ROOT / "maintainer-request.md").read_text(encoding="utf-8")
    
    # Extract columns from storms.nhc_tracks_geo definition
    m = re.search(r"CREATE TABLE IF NOT EXISTS storms\.nhc_tracks_geo\s*\((.*?)\)\s*TABLESPACE", sql_schema, re.DOTALL)
    assert m is not None, "Failed to find storms.nhc_tracks_geo table definition"
    table_def = m.group(1)
    
    # Verify required columns exist in schema
    assert "atcf_id VARCHAR NOT NULL" in table_def
    assert "issued_time TIMESTAMP NOT NULL" in table_def
    assert "leadtime INTEGER NOT NULL" in table_def
    
    # Verify deprecated/nonexistent columns are NOT in schema
    assert "advisory_number" not in table_def
    assert "issuance_timestamp" not in table_def
    assert "created_at" not in table_def
    
    # Verify maintainer query uses the correct columns and not the deprecated ones
    m_sql = re.search(r"```sql\s*(.*?)\s*```", maintainer_doc, re.DOTALL)
    assert m_sql is not None, "Failed to find SQL block in maintainer-request.md"
    sql_query = m_sql.group(1)
    
    assert "atcf_id AS storm_id" in sql_query
    assert "issued_time AS issued_at" in sql_query
    assert "leadtime = 0" in sql_query
    assert "advisory_number" not in sql_query
    assert "issuance_timestamp" not in sql_query
    assert "created_at" not in sql_query
