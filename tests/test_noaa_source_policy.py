"""Offline, deterministic NOAA parser and documented-policy counterfactuals."""
import copy
import json
from pathlib import Path

import pytest

from storm_audit.noaa_archive import (
    archive_directory, product_urls, parse_product, manifest_from_documents,
    fetch_text,
)
from storm_audit.policy_replay import replay, scenario_grid, mixed_ticks, legacy_ticks, reduced_ticks
from storm_audit.core import parse_time, validate_manifest

DATA = Path(__file__).resolve().parents[1] / "examples"


def seed():
    return json.loads((DATA / "noaa_2026_verified_subset.json").read_text())


def only_rows(*r):
    return {"schema_version":1,"expected_advisories":[{"storm_id":s,"issued_at":t,"source_ref":url,"required_stages":["raw_tracks"]} for s,t,url in r]}


def raw_page(storm="EP152026", num="16A", issue="800 AM HST Thu Sep 24 2026", summary="1800 UTC"):
    return (f"<html><h2>Tropical Storm NOLO</h2><pre>\nBULLETIN\n"
            f"Tropical Storm Nolo Intermediate Advisory Number {num}\n"
            f"NWS Central Pacific Hurricane Center Honolulu HI {storm}\n"
            f"Issued by NWS National Hurricane Center Miami FL\n{issue}\n"
            f"SUMMARY OF 800 AM HST...{summary}...INFORMATION\n"
            "LOCATION...14.9N 156.1W\n</pre></html>")


def test_official_archive_directory_format():
    assert archive_directory("AL062026") == "https://www.nhc.noaa.gov/archive/2026/al06/"
    assert archive_directory("EP152026") == "https://www.nhc.noaa.gov/archive/2026/ep15/"


@pytest.mark.parametrize("storm", ["AL06", "../../etc", "ftp://noaa", "", "EP152026#foo"])
def test_bad_storm_ids_rejected(storm):
    with pytest.raises(ValueError):
        archive_directory(storm)


def test_directory_discovery_only_public_products_and_exact_storm():
    html = '''<a href="ep152026.public.015.shtml">normal</a>
<a href="ep152026.public_a.015.shtml">intermediate</a>
<a href="ep152026.fstadv.015.shtml">duplicate representation</a>
<a href="ep162026.public.015.shtml">wrong storm</a>
<a href="https://evil.example/ep152026.public.017.shtml">evil</a>
<a href="//evil.example/ep152026.public.017.shtml">protocol-relative evil</a>
<a href="../ep16/ep152026.public.016.shtml">off-directory</a>
<a href="ep152026.public.015.shtml">duplicate</a>'''
    urls = product_urls("EP152026", html)
    assert urls == [
        "https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.015.shtml",
        "https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.015.shtml",
    ]


def test_archive_directory_pagination_limit_requires_explicit_override():
    html = "".join(f'<a href="ep152026.public.{i:03d}.shtml">x</a>' for i in range(7))
    with pytest.raises(ValueError, match="Too many"):
        product_urls("EP152026", html, limit=5)


def test_noaa_nolo_intermediate_16a_hst_to_utc():
    url = "https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml"
    result = parse_product(url, raw_page())
    assert result["issued_at"] == "2026-09-24T18:00:00Z"
    assert result["product_id"] == "16A"
    assert result["product_kind"] == "intermediate"
    assert result["time_basis"] == "nominal_issuance_utc_not_first_available"


def test_cross_midnight_hst_date_converted_using_local_header():
    url="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.015.shtml"
    txt="Tropical Storm Nolo Advisory Number 15\nNWS Honolulu HI EP152026\n1100 PM HST Wed Sep 23 2026\nSUMMARY OF 1100 PM HST...0900 UTC...INFORMATION"
    assert parse_product(url, txt)["issued_at"] == "2026-09-24T09:00:00Z"


def test_cst_900_am_is_1500z():
    url="https://www.nhc.noaa.gov/archive/2026/ep17/ep172026.public.016.shtml"
    txt="Hurricane Polo Advisory Number 16\nEP172026\n900 AM CST Thu Sep 24 2026\nSUMMARY OF 900 AM CST...1500 UTC...INFORMATION"
    assert parse_product(url, txt)["issued_at"] == "2026-09-24T15:00:00Z"


def test_gmt_300_am():
    url="https://www.nhc.noaa.gov/archive/2026/al06/al062026.public.016.shtml"
    txt="Tropical Storm Fay Advisory Number 16\nAL062026\n300 AM GMT Thu Sep 24 2026\nSUMMARY OF 300 AM GMT...0300 UTC...INFORMATION"
    assert parse_product(url, txt)["issued_at"] == "2026-09-24T03:00:00Z"


def test_timezone_summary_inconsistency_is_rejected():
    url="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml"
    with pytest.raises(ValueError,match="contradicts"):
        parse_product(url,raw_page(summary="1700 UTC"))


def test_storm_mismatch_rejected():
    url="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml"
    with pytest.raises(ValueError, match="storm ID"):
        parse_product(url,raw_page(storm="EP162026"))


def test_number_and_suffix_mismatch_rejected():
    url="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml"
    with pytest.raises(ValueError, match="suffix"):
        parse_product(url,raw_page(num="16"))
    with pytest.raises(ValueError, match="number"):
        parse_product(url,raw_page(num="17A"))


def test_non_noaa_url_rejected_even_if_plausible():
    with pytest.raises(ValueError,match="approved"):
        parse_product("https://fake.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml",raw_page())
    with pytest.raises(ValueError,match="NOAA-only"):
        fetch_text("http://www.nhc.noaa.gov/archive/2026/ep15/")


def test_manifest_parses_actual_source_text_not_guessed_cadence():
    url="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml"
    manifest=manifest_from_documents([(url,raw_page())],"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z")
    assert len(manifest["expected_advisories"]) == 1
    assert manifest["expected_advisories"][0]["issued_at"] == "2026-09-24T18:00:00Z"
    assert manifest["catalog_completeness"] == "not_established"
    expected,_=validate_manifest(manifest)
    assert len(expected)==1


def test_noaa_docs_duplicate_times_rejected():
    u1="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.015.shtml"
    u2="https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.015.shtml"
    # If nominal times clash, they need manual review, not silent dedup.
    txt="Tropical Storm Nolo Advisory Number 15\nEP152026\n500 AM HST Thu Sep 24 2026\nSUMMARY OF 500 AM HST...1500 UTC...INFORMATION"
    txt2="Tropical Storm Nolo Intermediate Advisory Number 15A\nEP152026\n500 AM HST Thu Sep 24 2026\nSUMMARY OF 500 AM HST...1500 UTC...INFORMATION"
    with pytest.raises(ValueError, match="Multiple public products"):
        manifest_from_documents([(u1,txt),(u2,txt2)],"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z")


def test_historical_schedule_changes_at_documented_deploy_time():
    start=parse_time("2026-09-30T00:00:00Z")
    stop=parse_time("2026-10-01T00:00:00Z")
    ticks=mixed_ticks(start,stop)
    assert len(ticks)==15  # 7 old 3-hour blocks *2, then 21:30 new
    assert parse_time("2026-09-30T18:30:00Z") in ticks
    assert parse_time("2026-09-30T21:00:00Z") not in ticks
    assert parse_time("2026-09-30T21:30:00Z") in ticks


def test_legacy_and_reduced_poll_counts():
    start=parse_time("2026-10-01T00:00:00Z")
    stop=parse_time("2026-10-02T00:00:00Z")
    assert len(list(legacy_ticks(start,stop))) == 16
    assert len(list(reduced_ticks(start,stop))) == 4


def test_october_nolo_independent_pages_show_both_intermediate_gaps():
    man=seed()
    start,end="2026-10-01T00:00:00Z","2026-10-02T00:00:00Z"
    old=replay(man,start,end,policy="legacy")
    new=replay(man,start,end,policy="historical")
    assert old["counts"] == {"modeled_selected":5}
    assert new["counts"] == {"modeled_selected":3,"modeled_schedule_gap":2}
    missing={x["issued_at"] for x in new["records"] if x["status"]=="modeled_schedule_gap"}
    assert missing == {"2026-10-01T12:00:00Z","2026-10-01T18:00:00Z"}
    assert new["assumptions"]["catalog_completeness"].startswith("partial_")


def test_september_policy_not_retroactively_applied():
    man=seed()
    s,e="2026-09-24T00:00:00Z","2026-09-25T00:00:00Z"
    assert replay(man,s,e,policy="historical")["counts"] == {"modeled_selected":17}
    cf=replay(man,s,e,policy="reduced")
    assert cf["counts"] == {"modeled_selected":14,"modeled_schedule_gap":3}


def test_approx_outage_is_distinct_from_schedule_gap():
    man=seed()
    outage=json.loads((DATA/"2026-09-24-outage-scenario.json").read_text())
    r=replay(man,"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z",outage_intervals=outage)
    assert r["blocked_polls"] == 11
    assert r["counts"].get("modeled_outage_gap",0)>0
    assert r["counts"].get("modeled_schedule_gap",0)==0
    assert r["assumptions"]["downtime_is_scenario"]


def test_availability_lag_sensitivity_and_no_publication_claim():
    man=seed()
    args=(man,"2026-10-01T00:00:00Z","2026-10-02T00:00:00Z")
    grid=scenario_grid(*args,lags=(0,15,30,60))
    assert len(grid["scenarios"])==16
    assert grid["scenarios"][0]["polls"]==16
    assert grid["scenarios"][4]["polls"]==4
    assert not replay(*args)["assumptions"]["publication_times_known"]


def test_partial_source_catalog_cannot_be_silently_marked_complete():
    man=seed()
    assert man["catalog_completeness"].startswith("partial_")
    r=replay(man,"2026-10-01T00:00:00Z","2026-10-02T00:00:00Z")
    assert r["kind"]=="schedule_counterfactual_not_production_observations"
    assert any(x["edge_censored"] for x in r["records"])
    assert any("Only source-listed advisories" in line for line in r["limitations"])


def test_synthetic_outage_is_not_alleged_real_measurement():
    man=seed()
    r=replay(man,"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z",outage_intervals=json.loads((DATA/"2026-09-24-outage-scenario.json").read_text()))
    assert r["kind"].startswith("schedule_counterfactual")
    assert r["assumptions"]["publication_times_known"] is False


def test_future_advisory_does_not_count_as_available():
    man=only_rows(("AL012026","2026-10-01T23:50:00Z","https://www.nhc.noaa.gov/example"))
    r=replay(man,"2026-10-01T00:00:00Z","2026-10-02T00:00:00Z",availability_lag_minutes=60)
    assert r["counts"]=={"not_yet_available_by_window_end":1}


def test_outage_intervals_validate_bounds():
    man=seed()
    with pytest.raises(ValueError,match="interval"):
        replay(man,"2026-10-01T00:00:00Z","2026-10-02T00:00:00Z",outage_intervals=[{"start":"2026-10-01T09:00:00Z","until":"2026-10-01T03:00:00Z"}])


def test_duplicate_source_advisory_rejected():
    man=seed()
    man["expected_advisories"].append(copy.deepcopy(man["expected_advisories"][0]))
    with pytest.raises(ValueError,match="Duplicate expected advisory"):
        replay(man,"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z")


def test_offline_cli_parses_saved_noaa_product_page(tmp_path):
    from storm_audit.noaa_archive import main
    path = tmp_path / "ep152026.public_a.016.shtml"
    path.write_text(raw_page())
    output = tmp_path / "manifest.json"
    rc = main(["--storm","EP152026", "--start","2026-09-24T00:00:00Z",
               "--until","2026-09-25T00:00:00Z", "--html-dir",str(tmp_path),
               "--output",str(output)])
    assert rc == 0
    data = json.loads(output.read_text())
    assert data["expected_advisories"][0]["issued_at"] == "2026-09-24T18:00:00Z"
    assert data["catalog_completeness"] == "not_established"


def test_cli_requires_explicit_source_not_implicit_network(tmp_path):
    from storm_audit.noaa_archive import main
    with pytest.raises(SystemExit):
        main(["--storm","EP152026", "--start","2026-09-24T00:00:00Z",
              "--until","2026-09-25T00:00:00Z", "--output",str(tmp_path/"x.json")])


def test_proposed_event_driven_cheap_polling_can_capture_intermediates():
    man = seed()
    r = replay(man, "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z", policy="event_driven")
    assert r["poll_count"] == 48
    assert r["counts"] == {"modeled_selected": 5}
    assert r["modeled_heavy_job_invocations"] == 5
    assert r["assumptions"]["event_driven_assumes_reliable_noaa_feed_polling_and_deduplication"]
    # 48 cheap metadata polls are not 48 expensive Databricks job runs.


def test_event_driven_batches_simultaneous_multi_storm_advisories():
    man = seed()
    r = replay(man, "2026-09-24T00:00:00Z", "2026-09-25T00:00:00Z", policy="event_driven")
    assert r["counts"] == {"modeled_selected": 17}
    assert r["modeled_heavy_job_invocations"] == 6  # timestamps 03,09,12,15,18,21Z
    assert r["modeled_heavy_job_invocations"] < replay(
        man,"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z",policy="legacy"
    )["modeled_heavy_job_invocations"]
