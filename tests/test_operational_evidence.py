"""Strict offline real-evidence boundary checks. No DB access or networking."""
import copy
import json
from pathlib import Path
import pytest
from storm_audit.archived_listing import audit_listing, ListingEvidenceError
from storm_audit.operational_evidence import classify_operational, EvidenceError, main

ROOT=Path(__file__).resolve().parents[1]/"examples"

def fixture():
    man=json.loads((ROOT/"noaa_nolo_2026-10-01_public_day.json").read_text())
    idx=json.loads((ROOT/"noaa_nolo_2026-10-01_index_control.json").read_text())
    return man,idx

def export(kind="current_state",rows=None):
    e={"schema_version":1,"table":"storms.nhc_tracks_geo","storm_id":"EP152026",
       "scope_start":"2026-10-01T00:00:00Z","scope_until":"2026-10-02T00:00:00Z",
       "query_status":"succeeded","coverage":"full_bounded_scan",
       "exported_at":"2026-10-16T10:00:00Z","snapshot_type":kind,"rows":rows or []}
    if kind=="historical_asof":e["snapshot_as_of"]="2026-10-02T00:00:00Z"
    return e

def rows_for(man,subset):
    return [{"storm_id":x["storm_id"],"issued_at":x["issued_at"],"row_count":1}
            for x in man["expected_advisories"][:subset]]

def test_real_directory_lists_38_but_proves_zero_snapshot_contents():
    listing=json.loads((ROOT/"noaa_2026-10-01_archived_json_directory_visible_rows.json").read_text())
    r=audit_listing(listing)
    assert r["visible_rows"]==38
    assert r["json_documents_downloaded"]==0
    assert r["advisory_identities_verified_from_json"]==0
    assert not r["publication_latency_measured"]
    assert [a["listing_delta_minutes"] for a in r["reduced_schedule_index_crosscheck"]]==[6,6,6,8]


def test_truncated_file_link_cannot_be_claimed_as_verified():
    d=json.loads((ROOT/"noaa_2026-10-01_archived_json_directory_visible_rows.json").read_text())
    d["visible_rows"][0]["full_href_verified"]=True
    with pytest.raises(ListingEvidenceError,match="mix"):
        audit_listing(d)


def test_no_operational_export_yields_all_unknown():
    man,idx=fixture();r=classify_operational(man,idx)
    assert r["source_listed_public_advisories"]==8
    assert r["counts"]=={"operational_evidence_unavailable":8}
    assert r["operational_export_assurance"]=="no_operational_export"
    assert not r["all_advisories_verified_processed"]


def test_current_export_absence_is_not_historical_proof():
    m,i=fixture();r=classify_operational(m,i,export())
    assert r["counts"]=={"row_absent_from_current_export_not_proof_of_historical_omission":8}
    assert all("not_proof_of_historical_omission" in x["operational_verdict"] for x in r["records"])


def test_positive_current_export_only_proves_row_presence_when_scanned():
    m,i=fixture();r=classify_operational(m,i,export(rows=rows_for(m,4)))
    assert r["counts"]["row_present_in_export_not_original_ingestion_time"]==4
    assert r["counts"]["row_absent_from_current_export_not_proof_of_historical_omission"]==4
    assert not r["all_advisories_verified_processed"]


def test_historical_asof_requires_specific_attested_snapshot_metadata():
    m,i=fixture();r=classify_operational(m,i,export(kind="historical_asof",rows=rows_for(m,4)))
    assert r["counts"]["row_absent_from_attested_historical_snapshot_requires_review"]==4
    assert r["operational_metadata"]["operator_attestation_not_independently_verified"]
    assert r["operational_metadata"]["snapshot_as_of"]=="2026-10-02T00:00:00Z"

@pytest.mark.parametrize("mutation,match", [
    (lambda x:x.update(table="other.table"),"Only exact"),
    (lambda x:x.update(storm_id="EP162026"),"does not match"),
    (lambda x:x.update(query_status="failed"),"full successful"),
    (lambda x:x.update(coverage="partial"),"full successful"),
    (lambda x:x.update(scope_start="2026-10-01T01:00:00Z"),"entire"),
    (lambda x:x.update(scope_until="2026-10-01T23:00:00Z"),"entire"),
    (lambda x:x.update(snapshot_type="unknown"),"Distinguish"),
    (lambda x:x.update(snapshot_as_of="2026-10-01T00:00:00Z"),"may not"),
 ])
def test_invalid_export_fails_closed(mutation,match):
        m,i=fixture(); e=export(); mutation(e)
        with pytest.raises(EvidenceError,match=match):classify_operational(m,i,e)


def test_historical_snapshot_before_end_of_source_day_rejected():
    m,i=fixture();e=export(kind="historical_asof");e["snapshot_as_of"]="2026-10-01T16:00:00Z"
    with pytest.raises(EvidenceError,match="precedes end"):
        classify_operational(m,i,e)


def test_sample_operational_export_is_deliberately_not_runnable():
    m,i=fixture()
    sample=json.loads((ROOT/"operational-export-contract-example.json").read_text())
    with pytest.raises(EvidenceError,match="full successful"):
        classify_operational(m,i,sample)


def test_historical_snapshot_after_export_rejected():
    m,i=fixture();e=export(kind="historical_asof");e["snapshot_as_of"]="2026-10-18T00:00:00Z"
    with pytest.raises(EvidenceError,match="later"):
        classify_operational(m,i,e)


def test_duplicate_and_out_of_scope_operational_rows_rejected():
    m,i=fixture();e=export(rows=rows_for(m,1));e["rows"].append(e["rows"][0].copy())
    with pytest.raises(EvidenceError,match="Duplicate"):
        classify_operational(m,i,e)
    e=export(rows=[{"storm_id":"EP152026","issued_at":"2026-10-01T04:00:00Z","row_count":1}])
    with pytest.raises(EvidenceError,match="Out-of-scope"):
        classify_operational(m,i,e)


def test_malformed_or_zero_count_rejected():
    m,i=fixture(); e=export(rows=rows_for(m,1));e["rows"][0]["row_count"]=0
    with pytest.raises(EvidenceError,match="strictly positive"):
        classify_operational(m,i,e)


def test_cli_no_export_produces_uncertainty_not_false_missed(tmp_path):
    m,i=fixture(); manifest=tmp_path/"man.json"; index=tmp_path/"idx.json"
    manifest.write_text(json.dumps(m));index.write_text(json.dumps(i))
    out=tmp_path/"report.json"
    assert main(["--manifest",str(manifest),"--reviewed-index",str(index),"--output",str(out)])==0
    r=json.loads(out.read_text())
    assert r["counts"]=={"operational_evidence_unavailable":8}
