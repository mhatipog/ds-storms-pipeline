"""Conservative source-backed, BOUNDED advisory-day policy experiment.

The NHC source index and the curated manifest are two manually extracted
representations of official archive evidence; matching them is an inventory
consistency check, NOT proof that any advisory was available at its nominal
time or processed by OCHA. No external side effects.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path

from .core import parse_time, iso
from .policy_replay import replay
from .event_recovery import replay_recovery


def check_inventory(manifest: dict, index: dict) -> dict:
    """Fail closed on a mismatch against the reviewed bounded index."""
    required = {"source_index", "expected_public_products", "storm_id", "utc_date"}
    if not required.issubset(index):
        raise ValueError("Bounded NOAA index control is missing required metadata")
    expected_list = index["expected_public_products"]
    if not expected_list or not isinstance(expected_list, list):
        raise ValueError("Expected nonempty reviewed NOAA public-product listing")
    if manifest.get("source_index") != index["source_index"]:
        raise ValueError("Manifest and index provenance mismatch")
    if not manifest.get("catalog_completeness", "").startswith("bounded_"):
        raise ValueError("Require a bounded, explicitly qualified source index")
    day = index["utc_date"]
    if not isinstance(day, str) or len(day) != 10:
        raise ValueError("Bad UTC day")
    start = parse_time(day + "T00:00:00Z")
    end = start + timedelta(days=1)
    source_rows = manifest.get("expected_advisories", [])
    if not isinstance(source_rows, list):
        raise ValueError("Missing expected_advisories")
    def normalize(rows, *, manifest_rows):
        out = set()
        for r in rows:
            storm = r.get("storm_id", index["storm_id"]) if not manifest_rows else r.get("storm_id")
            pid = r.get("product_id")
            issued = r.get("issued_at")
            if storm != index["storm_id"] or not isinstance(pid, str) or not pid:
                raise ValueError("Mismatched storm or product identity")
            t = parse_time(issued)
            if not start <= t < end:
                raise ValueError("Source advisory outside index's UTC day")
            key = (storm, pid.upper(), iso(t))
            if key in out:
                raise ValueError("Duplicate NOAA product identity")
            out.add(key)
            if manifest_rows:
                if not r.get("source_ref", "").startswith("https://www.nhc.noaa.gov/archive/"):
                    raise ValueError("Missing or non-NOAA archive reference")
                if r.get("product_kind") not in {"regular", "intermediate"}:
                    raise ValueError("Missing product type")
        return out
    wanted = normalize(expected_list, manifest_rows=False)
    got = normalize(source_rows, manifest_rows=True)
    if wanted != got:
        raise ValueError("Curated advisory manifest differs from bounded NHC index: "
                         f"missing={sorted(wanted-got)!r}; unexpected={sorted(got-wanted)!r}")
    return {"storm_id":index["storm_id"],"start":iso(start),"until":iso(end),
            "listed_public_products":len(wanted),
            "intermediate":sum(r["product_kind"]=="intermediate" for r in source_rows),
            "regular":sum(r["product_kind"]=="regular" for r in source_rows),
            "index_url":index["source_index"],
            "other_source_updates":index.get("other_source_updates", [])}


def run_study(manifest: dict, index: dict, *, lags=(0,30,60),
              feed_outage=None, replay_through_next_archive=False) -> dict:
    inventory = check_inventory(manifest, index)
    start, until = inventory["start"], inventory["until"]
    lag_rows = []
    for lag in lags:
        if type(lag) is not int or not 0 <= lag <= 360:
            raise ValueError("Lag scenario must be 0..360 integer minutes")
        scenarios = {}
        for policy in ("legacy","reduced","event_driven"):
            r = replay(manifest,start,until,policy=policy,availability_lag_minutes=lag)
            scenarios[policy] = {"modeled_selected":r["counts"].get("modeled_selected",0),
                                 "modeled_schedule_gap":r["counts"].get("modeled_schedule_gap",0),
                                 "not_yet_available":r["counts"].get("not_yet_available_by_window_end",0),
                                 "hypothetical_job_invocations":r["modeled_heavy_job_invocations"],
                                 "scheduled_observations":r["poll_count"]}
        lag_rows.append({"assumed_availability_lag_minutes":lag,"models":scenarios})
    recovery_until = iso(parse_time(until) + timedelta(hours=6)) if replay_through_next_archive else until
    recovery = replay_recovery(manifest,start,recovery_until, feed_poll_minutes=30,
       archive_scan_hours=6, outage_intervals=feed_outage or [],
       dispatch_cooldown_minutes=60, max_heavy_batches_per_day=8)
    # Do not conflate a proposed batch with the current operational interface:
    # the NHC job's --issued-time is scalar; historical replay requires a
    # source-aware backfill and ordered reprocessing, neither of which runs.
    operational_gate = {
      "batch_multi_issuance_supported_by_existing_scalar_issued_time_argument":False,
      "archived_products_auto_ingested_by_current_realtime_etl":False,
      "archive_replay_requires_separate_reviewed_ingestion":True,
      "cumulative_outputs_require_chronological_recompute":True,
      "actual_db_snapshot_available":False,
      "real_databricks_cost_measured":False,
      "allowed_automatic_backfills":0,
      "humanitarian_effect_measured":False,
      "recommended_action":"shadow_audit_and_maintainer_review_only",
    }
    # A planning batch can group events to estimate a future multi-issuance
    # worker, but it does NOT demonstrate the existing job can execute it.
    reduced = lag_rows[0]["models"]["reduced"] if lag_rows else None
    return {
      "kind":"bounded_noaa_public_advisory_counterfactual_not_production_validation",
      "source_scope":inventory,
      "source_coverage_assertion":"matches_reviewed_day_index_not_independent_global_completeness",
      "source_time_assurance":"nominal_issuance_only; first_availability_unobserved",
      "assumption_grid":lag_rows,
      "zero_lag_reduced_omissions": [row["product_id"] for row in manifest["expected_advisories"]
          if row["issued_at"] in {r["issued_at"] for r in replay(
              manifest,start,until,policy="reduced")["records"]
              if r["status"]=="modeled_schedule_gap"}],
      "recovery_model":{
          "replay_through":recovery_until,
          "outages_are_hypothetical":bool(feed_outage),
          "discovered":recovery["recorded"],
          "undiscovered_by_window_end":recovery["not_discovered"],
          "channels":recovery["discovery_channel_counts"],
          "hypothetical_dispatch_plans":recovery["hypothetical_heavy_batches"],
          "actual_queue_pending":recovery["actual_queue_pending_at_window_end"],
          "actual_verified":recovery["operational_work_verified"],
          "queue_assurance":recovery["queue"]["state"],
      },
      "operational_gate":operational_gate,
      "limitations":[
         "The indexed eight public advisories for one storm/day do not establish completeness of all NOAA product types; the index lists a separate 12:35 update.",
         "The NOAA source index was manually transcribed; matching it against a manually curated manifest is a consistency check only.",
         "No first-publication, live JSON feed, Databricks processing, OCHA ingestion, geometry, exposure or decision data was observed.",
         "The previous research sample contained only five advisories that day and must NOT be used to claim whole-day coverage.",
         "The event-driven simulation assumes a source eventually exposes the complete bounded product inventory after the modeled lag.",
         "Current Databricks ingestion and dispatch cannot execute the hypothetical multi-issuance batch plan as-is.",
         "Accepted schedule omissions and unexpected failures must be reported separately in any operational deployment.",
      ],
    }


def to_markdown(report: dict) -> str:
    scope=report["source_scope"]
    lines=["# Source-indexed Nolo day: policy and recovery benchmark", "",
        f"**Window:** {scope['start']} through {scope['until']} (exclusive).",
        f"**Verified against bounded NOAA storm index:** {scope['listed_public_products']} listed public products ({scope['regular']} regular, {scope['intermediate']} intermediate).",
        f"**Index:** {scope['index_url']}",
        "", "## Models — not actual ingestion", "",
        "| Hypothetical source availability lag | Legacy selected | Reduced selected | 30-min discovery selected |",
        "|---|---:|---:|---:|",]
    for row in report["assumption_grid"]:
        models=row["models"]
        lines.append(f"| {row['assumed_availability_lag_minutes']} min | {models['legacy']['modeled_selected']} | {models['reduced']['modeled_selected']} | {models['event_driven']['modeled_selected']} |")
    lines+= ["", "**Zero-lag reduced-schedule omissions (modeled, not observed):** " + ", ".join(report["zero_lag_reduced_omissions"]),
        "", "## Recovery model", "",
        f"Discoveries: {report['recovery_model']['discovered']}; actual verified completions: {report['recovery_model']['actual_verified']}; durable queue pending: {report['recovery_model']['actual_queue_pending']}.",
        f"Queue assurance: `{report['recovery_model']['queue_assurance']}` (NOT source completeness).",
        "", "## Operational safety gate", "",
        "The existing operational job accepts one issuance timestamp. The simulated dispatch batch is a *plan*, not evidence that OCHA can replay multiple advisories in a single job or save money.",
        "", "## Limitations", ""]
    lines.extend("- "+x for x in report["limitations"])
    return "\n".join(lines)+"\n"


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",required=True)
    p.add_argument("--index",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--markdown")
    a=p.parse_args(argv)
    man=json.loads(Path(a.manifest).read_text())
    idx=json.loads(Path(a.index).read_text())
    result=run_study(man,idx)
    Path(a.output).write_text(json.dumps(result,indent=2)+"\n")
    if a.markdown:
        Path(a.markdown).write_text(to_markdown(result))
    print(json.dumps({"advisories":result["source_scope"]["listed_public_products"],
                      "zero_lag_reduced_selected":result["assumption_grid"][0]["models"]["reduced"]["modeled_selected"],
                      "actual_verified":result["recovery_model"]["actual_verified"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
