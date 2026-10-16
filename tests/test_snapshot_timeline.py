"""Fail-closed offline checks for NOAA CurrentStorms temporal evidence.

No test requires network, Databricks, operational data or paid infrastructure.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from storm_audit.snapshot_timeline import (
    SourceIntegrityError, canonical_advisory_id, parse_current_storms,
    read_snapshot_index, reconcile_timeline, noaa_directory_urls, main,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DAY = json.loads((EXAMPLES / "noaa_nolo_2026-10-01_public_day.json").read_text())


def nolo(public="042", issued="2026-10-01T03:00:00.000Z", update="2026-10-01T02:55:52.439Z"):
    return {"activeStorms":[{"id":"ep152026","lastUpdate":issued,
              "publicAdvisory":{"advNum":public,"issuance":issued,"fileUpdateTime":update,
                                "url":"https://www.nhc.noaa.gov/text/HFOTCPep1.shtml"},
              "forecastAdvisory":{"advNum":"099","issuance":issued}}]}


def raw(item):
    return json.dumps(item,separators=(",", ":")).encode()


def setup(tmp_path, observations, *, mode="synthetic_scenario"):
    rows=[]
    for n,(at,snapshot) in enumerate(observations):
        p=tmp_path/f"snap-{n:02}.json";data=raw(snapshot);p.write_bytes(data)
        rows.append({"path":p.name,"sha256":sha256(data).hexdigest(),
          "source_url":None,"observed_at":at})
    return {"schema_version":1,"mode":mode,"snapshots":rows}


def test_real_noaa_public_advisory_schema_and_separate_product_timestamps():
    # Field contract matches OCHA-DAP/ds-nhc-forecast/NHC_JSON_Sample.json.
    record=parse_current_storms(raw(nolo()))
    assert record["active_storm_ids"]==["EP152026"]
    a=record["public_advisories"]["EP152026"]
    assert a=={"product_id":"42","issued_at":"2026-10-01T03:00:00Z",
               "file_update_time":"2026-10-01T02:55:52.439Z"}
    assert a["product_id"]!="99" # forecastAdvisory ignored.


def test_zero_active_storms_not_interpreted_as_missing_product():
    assert parse_current_storms(b'{"activeStorms": []}')=={"active_storm_ids":[],"public_advisories":{}}


def test_later_offcycle_intermediate_number_parsed_without_collapsing():
    assert canonical_advisory_id("043A")=="43A"
    assert canonical_advisory_id("00043a")=="43A"
    a=parse_current_storms(raw(nolo("043A","2026-10-01T12:00:00.000Z")))
    assert a["public_advisories"]["EP152026"]["product_id"]=="43A"


@pytest.mark.parametrize("bad", ["", "ABC", "00", "043-A", "043 A", "-3", "43AA", 43, "1000"])
def test_bad_advisory_ids_fail_closed(bad):
    with pytest.raises(SourceIntegrityError):
        canonical_advisory_id(bad)


def test_malformed_json_duplicate_storm_and_missing_public_fields():
    with pytest.raises(SourceIntegrityError):parse_current_storms(b'{broken')
    with pytest.raises(SourceIntegrityError):parse_current_storms(b'{"activeStorms":null}')
    obj=nolo();obj["activeStorms"].append(deepcopy(obj["activeStorms"][0]))
    with pytest.raises(SourceIntegrityError,match="Multiple"):parse_current_storms(raw(obj))
    obj=nolo();del obj["activeStorms"][0]["publicAdvisory"]["advNum"]
    with pytest.raises(SourceIntegrityError,match="Missing"):parse_current_storms(raw(obj))


def test_snapshot_hash_mismatch_fails_closed(tmp_path):
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo())])
    index["snapshots"][0]["sha256"]="a"*64
    with pytest.raises(SourceIntegrityError,match="hash mismatch"):
        read_snapshot_index(index,tmp_path)


def test_path_traversal_and_symlink_escape_rejected(tmp_path):
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo())])
    index["snapshots"][0]["path"]="../secrets.json"
    with pytest.raises(SourceIntegrityError,match="relative"):
        read_snapshot_index(index,tmp_path)
    outside=tmp_path.parent/"outside.json";outside.write_text("{}")
    link=tmp_path/"out.json";link.symlink_to(outside)
    index["snapshots"][0]["path"]="out.json"
    with pytest.raises(SourceIntegrityError,match="escapes"):
        read_snapshot_index(index,tmp_path)
    outside.unlink()


def test_two_conflicting_snapshots_at_same_capture_time_rejected(tmp_path):
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo()),
                          ("2026-10-01T03:30:00Z",nolo("043","2026-10-01T09:00:00Z"))])
    with pytest.raises(SourceIntegrityError,match="same capture instant"):
        read_snapshot_index(index,tmp_path)


def test_untrusted_archive_url_rejected(tmp_path):
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo())],mode="retrospective_archive")
    index["snapshots"][0]["source_url"]="https://attacker.example/CurrentStorms_2026-10-01.json"
    with pytest.raises(SourceIntegrityError,match="official NOAA"):
        read_snapshot_index(index,tmp_path)
    index["snapshots"][0]["source_url"]="https://www.nhc.noaa.gov/archive/activeJson/2026/CurrentStorms_2026-10-01_0330.json"
    assert read_snapshot_index(index,tmp_path)["snapshot_count"]==1


def test_observation_interval_bracketed_only_by_same_storm(tmp_path):
    index=setup(tmp_path,[
        ("2026-10-01T03:30:00Z",nolo("042","2026-10-01T03:00:00Z")),
        ("2026-10-01T06:30:00Z",nolo("042A","2026-10-01T06:00:00Z")),
        ("2026-10-01T09:30:00Z",nolo("043","2026-10-01T09:00:00Z")),
    ])
    parsed=read_snapshot_index(index,tmp_path)
    result=reconcile_timeline(DAY,parsed)
    a=next(r for r in result["records"] if r["product_id"]=="42A")
    assert a["first_observed_at"]=="2026-10-01T06:30:00Z"
    assert a["last_explicitly_different_at"]=="2026-10-01T03:30:00Z"
    assert a["interval_assurance"]=="bounded_between_captures_not_publication_time"
    assert result["evidence_assurance"]=="synthetic_only"
    assert result["observed_product_count"]==3
    assert result["not_observed_count"]==5
    assert result["identity_conflict_count"]==0


def test_absent_storm_before_first_positive_not_negative_evidence(tmp_path):
    index=setup(tmp_path,[
        ("2026-10-01T02:30:00Z",{"activeStorms":[]}),
        ("2026-10-01T03:30:00Z",nolo("042","2026-10-01T03:00:00Z"))])
    result=reconcile_timeline(DAY,read_snapshot_index(index,tmp_path))
    a=next(r for r in result["records"] if r["product_id"]=="42")
    assert a["first_observed_at"]=="2026-10-01T03:30:00Z"
    assert a["last_explicitly_different_at"] is None
    assert a["interval_assurance"]=="upper_bound_only_not_publication_time"


def test_wrong_issuance_same_advisory_number_flagged_not_trusted(tmp_path):
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo("042","2026-10-01T02:59:00Z"))])
    result=reconcile_timeline(DAY,read_snapshot_index(index,tmp_path))
    a=next(r for r in result["records"] if r["product_id"]=="42")
    assert a["status"]=="identity_conflict_needs_review"
    assert a["first_observed_at"] is None
    assert result["identity_conflict_count"]==1


def test_latest_only_four_reduced_poll_snapshots_are_not_full_archive_evidence(tmp_path):
    series=[("2026-10-01T03:30:00Z",nolo("042","2026-10-01T03:00:00Z")),
            ("2026-10-01T09:30:00Z",nolo("043","2026-10-01T09:00:00Z")),
            ("2026-10-01T15:30:00Z",nolo("044","2026-10-01T15:00:00Z")),
            ("2026-10-01T21:30:00Z",nolo("045","2026-10-01T21:00:00Z"))]
    result=reconcile_timeline(DAY,read_snapshot_index(setup(tmp_path,series),tmp_path))
    assert result["observed_product_count"]==4
    assert result["not_observed_count"]==4
    assert all(r["status"]=="not_observed_coverage_unknown" for r in result["records"] if r["product_id"].endswith("A"))
    assert result["kind"]=="verified_snapshot_observation_not_operational_ingestion"


def test_noaa_directory_uses_href_not_truncated_labels():
    html='''<html><a href="CurrentStorms_2026-10-01_0330.json">CurrentStorms_2026-0..&gt;</a>
<a href="CurrentStorms_2026-10-01_0930.json">x</a>
<a href="../2025/CurrentStorms_2025-10-01_0000.json">old</a>
<a href="https://evil.example/CurrentStorms_2026-10-01_1000.json">evil</a>
<a href="CurrentStorms_2026-10-01_0330.json">duplicate</a>
</html>'''
    got=noaa_directory_urls(html,2026)
    assert got==[
        "https://www.nhc.noaa.gov/archive/activeJson/2026/CurrentStorms_2026-10-01_0330.json",
        "https://www.nhc.noaa.gov/archive/activeJson/2026/CurrentStorms_2026-10-01_0930.json"]


def test_cli_round_trip_without_network(tmp_path):
    idx=setup(tmp_path,[("2026-10-01T03:30:00Z",nolo())])
    path=tmp_path/"snapshots-index.json";path.write_text(json.dumps(idx))
    man=tmp_path/"manifest.json";man.write_text(json.dumps(DAY))
    output=tmp_path/"report.json"
    assert main(["--snapshots-index",str(path),"--manifest",str(man),"--out",str(output)])==0
    result=json.loads(output.read_text())
    assert result["observed_product_count"]==1
    assert result["not_observed_count"]==7


def test_checked_in_synthetic_case_is_reproducible_and_explicitly_not_observed(tmp_path):
    root=EXAMPLES/"nolo_snapshot_scenario"
    index=json.loads((root/"synthetic-snapshot-index.json").read_text())
    r=reconcile_timeline(DAY,read_snapshot_index(index,root))
    assert r["evidence_assurance"]=="synthetic_only"
    assert r["snapshot_count"]==4
    assert (r["observed_product_count"],r["not_observed_count"])==(4,4)
    assert {x["product_id"] for x in r["records"] if x["first_observed_at"]}=={"42","43","44","45"}
    expected=json.loads((root/"timeline-report.json").read_text())
    assert r==expected


def test_ocha_2023_example_excerpt_decodes_using_real_field_names():
    obj=json.loads((EXAMPLES/"ocha_2023_noaa_feed_schema_excerpt.json").read_text())
    r=parse_current_storms(raw(obj))
    assert r["public_advisories"]["AL062023"] == {
        "product_id":"11", "issued_at":"2023-08-22T03:00:00Z",
        "file_update_time":"2023-08-22T02:55:52.439Z",
    }


def test_same_advisory_source_file_update_can_signal_in_place_revision(tmp_path):
    earlier=nolo("042","2026-10-01T03:00:00Z","2026-10-01T02:55:00Z")
    later=nolo("042","2026-10-01T03:00:00Z","2026-10-01T03:08:34Z")
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",earlier),
                          ("2026-10-01T03:45:00Z",later)])
    report=reconcile_timeline(DAY,read_snapshot_index(index,tmp_path))
    a=next(x for x in report["records"] if x["product_id"]=="42")
    assert a["observed_in_snapshots"]==2
    assert a["source_revision_candidate"] is True
    assert a["status"]=="possible_source_revision_needs_review"
    assert len(a["source_file_update_times"])==2
    assert report["possible_revision_count"]==1
    assert report["observed_product_count"]==1


def test_repeated_identical_file_update_time_does_not_report_revision(tmp_path):
    sample=nolo("042","2026-10-01T03:00:00Z","2026-10-01T02:55:00Z")
    index=setup(tmp_path,[("2026-10-01T03:30:00Z",sample),
                          ("2026-10-01T03:45:00Z",sample)])
    report=reconcile_timeline(DAY,read_snapshot_index(index,tmp_path))
    a=next(x for x in report["records"] if x["product_id"]=="42")
    assert a["source_revision_candidate"] is False
    assert a["status"]=="observed_in_supplied_snapshots"
    assert report["possible_revision_count"]==0
