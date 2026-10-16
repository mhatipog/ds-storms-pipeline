"""Regressions for the verified, bounded NHC storm-index case study."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from storm_audit.bounded_day_study import check_inventory,run_study,to_markdown,main

D=Path(__file__).resolve().parents[1]/"examples"
MAN=json.loads((D/"noaa_nolo_2026-10-01_public_day.json").read_text())
INDEX=json.loads((D/"noaa_nolo_2026-10-01_index_control.json").read_text())


def test_storm_index_has_eight_explicit_products_including_midnight_boundary():
    x=check_inventory(MAN,INDEX)
    assert x["listed_public_products"]==8
    assert x["regular"]==4 and x["intermediate"]==4
    assert MAN["expected_advisories"][0]["issued_at"]=="2026-10-01T00:00:00Z"
    assert len(x["other_source_updates"])==1


def test_reduced_policy_omits_four_of_eight_under_zero_delay():
    r=run_study(MAN,INDEX,lags=(0,))
    z=r["assumption_grid"][0]["models"]
    assert z["legacy"]["modeled_selected"]==8
    assert z["reduced"]["modeled_selected"]==4
    assert z["reduced"]["modeled_schedule_gap"]==4
    assert z["event_driven"]["modeled_selected"]==8
    assert set(r["zero_lag_reduced_omissions"])=={"41A","42A","43A","44A"}
    assert z["event_driven"]["hypothetical_job_invocations"]==8
    assert z["reduced"]["hypothetical_job_invocations"]==4


def test_full_queued_work_is_not_completed_or_certified():
    r=run_study(MAN,INDEX,lags=(0,))
    assert r["recovery_model"]["discovered"]==8
    assert r["recovery_model"]["actual_queue_pending"]==8
    assert r["recovery_model"]["actual_verified"]==0
    assert r["recovery_model"]["queue_assurance"]=="coverage_unestablished"
    assert r["operational_gate"]["allowed_automatic_backfills"]==0


def test_source_record_missing_from_manually_transcribed_inventory_fails():
    m=deepcopy(MAN)
    m["expected_advisories"]=m["expected_advisories"][1:]
    with pytest.raises(ValueError,match="differs from bounded"):
        check_inventory(m,INDEX)


def test_extra_nonpublic_update_cannot_be_silently_treated_as_public_advisory():
    m=deepcopy(MAN)
    m["expected_advisories"].append({**m["expected_advisories"][0],
          "issued_at":"2026-10-01T12:35:00Z","product_id":"43UPDATE"})
    with pytest.raises(ValueError,match="differs from bounded"):
        check_inventory(m,INDEX)


def test_wrong_noaa_index_provenance_fails_closed():
    m=deepcopy(MAN);m["source_index"]="https://evil.com"
    with pytest.raises(ValueError,match="provenance"):
        check_inventory(m,INDEX)


def test_lag_sensitivity_cannot_be_interpreted_as_true_availability():
    r=run_study(MAN,INDEX,lags=(0,30,60))
    assert [x["assumed_availability_lag_minutes"] for x in r["assumption_grid"]]==[0,30,60]
    assert r["source_time_assurance"].startswith("nominal_issuance_only")
    assert r["assumption_grid"][2]["models"]["legacy"]["modeled_selected"]==7


def test_recovery_following_outage_requires_later_scan():
    outage=[{"start":"2026-10-01T09:00:00Z","until":"2026-10-02T00:00:00Z"}]
    no_followup=run_study(MAN,INDEX,lags=(0,),feed_outage=outage)
    yes_followup=run_study(MAN,INDEX,lags=(0,),feed_outage=outage,
                            replay_through_next_archive=True)
    assert no_followup["recovery_model"]["undiscovered_by_window_end"]>0
    assert yes_followup["recovery_model"]["undiscovered_by_window_end"]==0
    assert yes_followup["recovery_model"]["actual_verified"]==0


def test_markdown_discloses_no_production_outcome():
    r=run_study(MAN,INDEX,lags=(0,))
    s=to_markdown(r)
    assert "actual verified completions: 0" in s
    assert "not actual ingestion" in s
    assert "noaa.gov/archive/2026/NOLO.shtml" in s


def test_cli_writes_reproducible_report(tmp_path):
    out=tmp_path/"report.json";md=tmp_path/"report.md"
    assert main(["--manifest",str(D/"noaa_nolo_2026-10-01_public_day.json"),
                  "--index",str(D/"noaa_nolo_2026-10-01_index_control.json"),
                  "--output",str(out),"--markdown",str(md)])==0
    r=json.loads(out.read_text())
    assert r["source_scope"]["listed_public_products"]==8
    assert "Zero-lag" in md.read_text()
