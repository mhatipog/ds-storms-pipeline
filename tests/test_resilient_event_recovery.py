"""Failure-oriented tests for event hints, independent catalog reconciliation,
fail-closed durable queue and simulated crash-safe dispatch. Offline only.
"""
from __future__ import annotations

import copy
import json
import random
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest

from storm_audit.resilient_dispatch import AdvisoryQueue
from storm_audit.event_recovery import replay_recovery

BASE=Path(__file__).resolve().parents[1]
SEED=json.loads((BASE/"examples/noaa_2026_verified_subset.json").read_text())
START="2026-10-01T00:00:00Z"
END="2026-10-02T00:00:00Z"
NOW="2026-10-01T12:00:00Z"
AFTER="2026-10-01T13:00:00Z"


def nolo():
    return [x for x in SEED["expected_advisories"] if x["issued_at"].startswith("2026-10-01")]


def key(row):
    return f"{row['storm_id']}|{row['issued_at']}|{row['product_id']}"


def q(tmp_path):
    return AdvisoryQueue(tmp_path/"tasks.db")


def test_baseline_recovery_source_subset_without_false_certification():
    r=replay_recovery(SEED,START,END)
    assert (r["subset_size"],r["recorded"],r["not_discovered"]) == (5,5,0)
    assert r["discovery_channel_counts"] == {"feed":3,"archive":2}
    assert r["queue"]["state"] == "coverage_unestablished"
    assert r["queue"]["counts"]=={"queued":5}
    assert r["archive_scans"]["scheduled"]==4
    assert "partial" in r["source_catalog_completeness"]


def test_weak_latest_only_feed_can_not_recover_lost_intermediates_by_itself():
    r=replay_recovery(SEED,START,END,archive_availability_lag_minutes=1440)
    assert r["discovery_channel_counts"]=={"feed":5,"archive":0} or r["not_discovered"]>0
    # Without independent archival enumeration, the model cannot claim
    # complete historical source coverage in any case.
    assert r["queue"]["state"]=="coverage_unestablished"


def test_archive_reconciliation_finds_advisories_feed_never_saw():
    r=replay_recovery(SEED,START,END,feed_poll_minutes=60,
                      archive_availability_lag_minutes=30,
                      outage_intervals=[{"start":"2026-10-01T11:30:00Z",
                                         "until":"2026-10-01T15:30:00Z"}])
    assert r["recorded"]==5
    assert r["discovery_channel_counts"]["archive"]>=1
    assert r["assumptions"]["reported_availability_is_scenario_not_measured"]


def test_outage_recovery_eventually_when_archive_is_available():
    r=replay_recovery(SEED,START,"2026-10-02T06:00:00Z",outage_intervals=[{
        "start":"2026-10-01T08:00:00Z","until":"2026-10-01T18:30:00Z"}])
    assert r["metadata_polls"]["failed"]>0
    assert r["archive_scans"]["failed"]>0
    assert r["recorded"]==5
    assert r["queue"]["counts"]=={"queued":5}


def test_no_successful_reconciliation_no_claim_of_total_coverage():
    r=replay_recovery(SEED,START,END,feed_availability_lag_minutes=1440,
                      archive_availability_lag_minutes=1440)
    assert r["recorded"]==0
    assert r["not_discovered"]==5
    assert r["queue"]["state"]=="coverage_unestablished"


def test_last_product_arriving_after_final_archive_scan_is_censored():
    r=replay_recovery(SEED,START,END,archive_availability_lag_minutes=300,
                      feed_availability_lag_minutes=1440)
    assert r["recorded"]<5
    assert r["not_discovered"]>0


def test_outage_with_no_archive_scan_does_not_assert_success():
    r=replay_recovery(SEED,START,END,outage_intervals=[{
        "start":START,"until":END}])
    assert r["recorded"]==0
    assert r["metadata_polls"]["failed"]==48
    assert r["archive_scans"]["failed"]==4


def test_replay_order_is_independent_of_manifest_row_order():
    original=replay_recovery(SEED,START,END)
    altered=copy.deepcopy(SEED)
    random.Random(12345).shuffle(altered["expected_advisories"])
    again=replay_recovery(altered,START,END)
    assert original["records"]==again["records"]


def test_replay_rejects_contradictory_duplicate_source_identity():
    altered=copy.deepcopy(SEED)
    altered["expected_advisories"].append({**nolo()[0],"source_ref":nolo()[0]["source_ref"]+"?bad"})
    with pytest.raises(ValueError):
        replay_recovery(altered,START,END)


def test_replay_wrong_parameters_fail_before_db_side_effects():
    with pytest.raises(ValueError,match="cadence"):
        replay_recovery(SEED,START,END,archive_scan_hours=5)
    with pytest.raises(ValueError,match="polling"):
        replay_recovery(SEED,START,END,feed_poll_minutes=7)


def test_duplicate_feed_and_archive_do_not_generate_two_jobs(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    assert store.ingest([rec],source="feed",now=NOW)["added"]==1
    assert store.ingest([rec],source="feed",now=NOW)["duplicates"]==1
    assert store.ingest([rec],source="archive",now=NOW)["duplicates"]==1
    assert store.report(now=NOW)["counts"]=={"queued":1}
    product=store.get("track",key(rec))
    assert product["seen_feed"]==product["seen_archive"]==1


def test_atomic_batch_rolls_back_on_bad_later_row(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    invalid={**nolo()[1],"issued_at":"not-a-time"}
    with pytest.raises(ValueError):
        store.ingest([rec,invalid],now=NOW)
    assert store.get("track",key(rec)) is None


def test_conflicting_product_does_not_overwrite_or_launch(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    other={**rec,"source_ref":rec["source_ref"].replace("public.","fstadv.")}
    assert store.ingest([other],now=NOW)["conflicts"]==1
    row=store.get("track",key(rec))
    assert row["status"]=="quarantined"
    assert row["source_ref"]==rec["source_ref"]
    assert store.claim(now=NOW)==[]
    assert store.report(now=NOW)["state"]=="needs_review"


def test_failed_archive_scan_never_erases_prior_products(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    store.scan_failed(stream="track",source="archive",now=AFTER,diagnostic="503 upstream")
    assert store.get("track",key(rec))["status"]=="queued"
    report=store.report(now=AFTER)
    assert report["latest_archive_scan_state"]=="failed"
    assert report["state"]=="coverage_unestablished"


def test_claim_is_unique_and_fenced(tmp_path):
    store=q(tmp_path)
    store.ingest(nolo()[:2],now=NOW)
    one=store.claim(now=NOW,batch_size=1,lease_seconds=60)
    two=store.claim(now=NOW,batch_size=1,lease_seconds=60)
    assert len(one)==len(two)==1
    assert one[0]["product_key"]!=two[0]["product_key"]
    assert store.claim(now=NOW)==[]
    with pytest.raises(ValueError,match="Stale"):
        store.report_outcome(stream="track",product_key=one[0]["product_key"],
           lease_token="wrong",outcome="acknowledged",now=NOW,evidence="receipt")


def test_expired_lease_never_automatically_double_dispatches(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    token=store.claim(now=NOW,lease_seconds=10)[0]
    assert store.claim(now=AFTER)==[]
    assert store.get("track",key(rec))["status"]=="verification_required"
    with pytest.raises(ValueError,match="Stale"):
        store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                             outcome="acknowledged",now=AFTER,evidence="late")


def test_ambiguous_launch_needs_manual_verification(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    token=store.claim(now=NOW)[0]
    store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                         outcome="uncertain",now=NOW)
    assert store.claim(now=AFTER)==[]
    assert store.report(now=AFTER)["state"]=="needs_review"
    store.verify(stream="track",product_key=key(rec),outcome="unknown",now=AFTER)
    assert store.get("track",key(rec))["status"]=="verification_required"


def test_only_independent_verified_not_started_allows_retry(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    token=store.claim(now=NOW)[0]
    store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                         outcome="uncertain",now=NOW)
    store.verify(stream="track",product_key=key(rec),outcome="verified_not_started",
                 now=NOW,independent_evidence="external-run-ledger:job-never-created")
    assert store.claim(now=NOW)==[]
    assert len(store.claim(now=AFTER))==1


def test_acknowledged_is_not_claimed_territory_verified(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    token=store.claim(now=NOW)[0]
    store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                         outcome="acknowledged",now=NOW,evidence="worker-123-says-done")
    assert store.get("track",key(rec))["status"]=="acknowledged"
    assert store.report(now=AFTER)["state"]=="coverage_unestablished"
    store.verify(stream="track",product_key=key(rec),outcome="verified_complete",now=AFTER,
                 independent_evidence="downstream-advisory-ledger:123")
    assert store.get("track",key(rec))["status"]=="verified"


def test_definitely_not_started_can_retry_but_backoff_is_enforced(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW)
    token=store.claim(now=NOW)[0]
    store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                         outcome="definitely_not_started",now=NOW)
    assert store.claim(now=NOW)==[]
    assert store.claim(now="2026-10-01T12:00:29Z")==[]
    assert len(store.claim(now="2026-10-01T12:00:30Z"))==1


def test_full_catalog_attestation_fail_closed_by_default(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    with pytest.raises(ValueError,match="Complete coverage"):
        store.ingest([rec],source="feed",now=NOW,scan_complete=True,assurance="externally_verified_complete")
    with pytest.raises(ValueError,match="Complete coverage"):
        store.ingest([rec],source="archive",now=NOW,scan_complete=True,assurance="partial_22_products")
    assert store.report(now=NOW)["state"]=="coverage_unestablished"


def test_wsp_queue_is_independent_of_track_queue(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW,stream="wsp")
    assert store.report(now=NOW,stream="track")["counts"]=={}
    assert store.report(now=NOW,stream="wsp")["counts"]=={"queued":1}


def test_never_green_when_scan_is_only_partial_even_if_all_tasks_verified(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW,source="archive",assurance="partial_source")
    token=store.claim(now=NOW)[0]
    store.report_outcome(stream="track",product_key=key(rec),lease_token=token["lease_token"],
                         outcome="acknowledged",now=NOW,evidence="worker")
    store.verify(stream="track",product_key=key(rec),outcome="verified_complete",now=NOW,independent_evidence="audit:123")
    assert store.report(now=AFTER)["state"]=="coverage_unestablished"


def test_sqlite_persists_after_reinstantiation(tmp_path):
    path=tmp_path/"persistent.sqlite"
    a=AdvisoryQueue(path)
    rec=nolo()[0]
    a.ingest([rec],now=NOW)
    b=AdvisoryQueue(path)
    assert b.get("track",key(rec))["source_ref"]==rec["source_ref"]
    assert len(b.claim(now=NOW))==1


def test_feed_latest_signal_can_skip_rapid_superseded_intermediate_even_without_outage():
    # Synthetic sources are deliberately NOT alleged real NOAA products.
    # A 12:05 product replaced at 12:20 cannot be seen by a 12:30
    # latest-only poll, even if every scheduled request succeeds.
    short={"expected_advisories":[
        {"storm_id":"AL012026","issued_at":"2026-10-01T12:05:00Z",
         "product_id":"90A","source_ref":"https://www.nhc.noaa.gov/archive/2026/al01/al012026.public_a.090.shtml"},
        {"storm_id":"AL012026","issued_at":"2026-10-01T12:20:00Z",
         "product_id":"90B","source_ref":"https://www.nhc.noaa.gov/archive/2026/al01/al012026.public_b.090.shtml"},
    ],"catalog_completeness":"synthetic_injected_two_products"}
    recovered=replay_recovery(short,START,END,archive_availability_lag_minutes=0)
    assert recovered["recorded"]==2
    assert recovered["discovery_channel_counts"]=={"feed":1,"archive":1}
    no_archive=replay_recovery(short,START,END,archive_availability_lag_minutes=1440)
    assert no_archive["recorded"]==1
    assert no_archive["not_discovered"]==1


def test_future_issuance_rejected_from_queue_before_source_publication(tmp_path):
    store=q(tmp_path)
    with pytest.raises(ValueError,match="Future issuance"):
        store.ingest([nolo()[-1]],now=NOW)
    assert store.report(now=NOW)["counts"]=={}


def test_replay_latency_is_nominal_not_real_publication_latency():
    replay=replay_recovery(SEED,START,END,feed_availability_lag_minutes=60,
                           archive_availability_lag_minutes=60)
    assert replay["max_nominal_issue_to_first_detection_minutes"]>=60
    assert replay["assumptions"]["reported_availability_is_scenario_not_measured"]


def test_two_local_workers_cannot_claim_same_product(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=q(tmp_path)
    store.ingest(nolo(),now="2026-10-02T00:00:00Z")
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:store.claim(now="2026-10-02T00:00:00Z",batch_size=1),range(5)))
    keys=[r[0]["product_key"] for r in results if r]
    assert len(keys)==len(set(keys))==5


def test_local_cli_persists_and_displays_only_unestablished_coverage(tmp_path,capsys):
    from storm_audit.resilient_dispatch import main
    path=tmp_path/"source.json"
    path.write_text(json.dumps({"expected_advisories":nolo()[:1],
             "catalog_completeness":"partial_sample"}))
    db=tmp_path/"record.db"
    assert main(["--db",str(db),"ingest","--manifest",str(path),
                 "--source","archive","--now","2026-10-02T01:00:00Z"])==0
    assert main(["--db",str(db),"status","--now","2026-10-02T02:00:00Z"])==0
    assert '"state": "coverage_unestablished"' in capsys.readouterr().out


def test_no_false_full_coverage_when_unrelated_stream_has_verified_catalog(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW,stream="wsp",source="archive",
                 scan_complete=True,assurance="externally_verified_complete")
    assert store.report(now=AFTER,stream="track")["state"]=="coverage_unestablished"
    assert store.report(now=AFTER,stream="wsp")["state"]=="backlog_or_unverified"


def test_successful_archive_scan_then_failed_scan_returns_unknown(tmp_path):
    store=q(tmp_path)
    rec=nolo()[0]
    store.ingest([rec],now=NOW,source="archive",scan_complete=True,
                 assurance="externally_verified_complete")
    store.scan_failed(stream="track",source="archive",now=AFTER,diagnostic="HTTP 503")
    assert store.report(now=AFTER)["state"]=="coverage_unestablished"


def test_daily_cost_cap_preserves_discovered_advisories_as_pending():
    result=replay_recovery(SEED,START,END,max_heavy_batches_per_day=1)
    assert result["recorded"]==5
    assert result["hypothetical_heavy_batches"]==1
    assert result["undispatched_work_at_window_end"]>=1
    assert result["queue"]["counts"]=={"queued":5}


def test_no_run_cap_does_not_prove_processing_complete():
    result=replay_recovery(SEED,START,END,max_heavy_batches_per_day=8,
                           dispatch_cooldown_minutes=120)
    assert result["hypothetical_heavy_batches"]<=8
    assert all(x["advisories_in_batch"]>=1 for x in result["hypothetical_heavy_dispatches"])
    assert result["queue"]["counts"]=={"queued":5}


def test_invalid_budget_rejected_fail_closed():
    with pytest.raises(ValueError,match="budget"):
        replay_recovery(SEED,START,END,max_heavy_batches_per_day=0)
    with pytest.raises(ValueError,match="cooldown"):
        replay_recovery(SEED,START,END,dispatch_cooldown_minutes=-1)


def test_same_url_new_noaa_product_body_hash_is_quarantined(tmp_path):
    store=q(tmp_path)
    rec={**nolo()[0],"content_sha256":"a"*64}
    store.ingest([rec],now=NOW)
    updated={**rec,"content_sha256":"b"*64}
    assert store.ingest([updated],now=AFTER)["conflicts"]==1
    assert store.get("track",key(rec))["status"]=="quarantined"
    assert store.claim(now=AFTER)==[]


def test_invalid_content_hash_fails_without_ingestion(tmp_path):
    store=q(tmp_path)
    bad={**nolo()[0],"content_sha256":"not-a-sha256"}
    with pytest.raises(ValueError,match="content_sha256"):
        store.ingest([bad],now=NOW)
    assert store.get("track",key(bad)) is None
