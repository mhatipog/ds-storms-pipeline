"""Counterfactual NHC polling-policy replay, not a replay of actual DB ingestion.

Assumptions: at each healthy poll a hypothetical current-storm feed exposes
only the newest *already available* advisory per storm. Archive issue times
are not first-availability times; lag is explicitly scenario-controlled.

A schedule-gapped advisory is NOT by itself a production failure. Policy was
changed 2026-09-30 to intentionally omit many intermediate advisories.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
import argparse
import json
from pathlib import Path

from .core import parse_time, iso, validate_manifest

POLICY_CHANGE_UTC = parse_time("2026-09-30T18:46:00Z")


def legacy_ticks(start: datetime, until: datetime):
    """Former NHC schedule: 00 and 30 past 00,03,06,...,21Z."""
    d = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d < until:
        for h in range(0, 24, 3):
            for m in (0, 30):
                tick = d + timedelta(hours=h, minutes=m)
                if start <= tick < until:
                    yield tick
        d += timedelta(days=1)


def reduced_ticks(start: datetime, until: datetime):
    """2026-09-30 cost-saving schedule: 03:30,09:30,15:30,21:30Z."""
    d = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d < until:
        for h in (3, 9, 15, 21):
            tick = d + timedelta(hours=h, minutes=30)
            if start <= tick < until:
                yield tick
        d += timedelta(days=1)


def event_discovery_ticks(start: datetime, until: datetime):
    """Cheap observation of advisory metadata every 30 min (hypothetical)."""
    t = start.replace(minute=0, second=0, microsecond=0)
    while t < until:
        if start <= t:
            yield t
        t += timedelta(minutes=30)


def mixed_ticks(start: datetime, until: datetime):
    """Historically bounded policy scenario; change time from PR #55."""
    return sorted(
        set(t for t in legacy_ticks(start, min(until, POLICY_CHANGE_UTC)))
        | set(t for t in reduced_ticks(max(start, POLICY_CHANGE_UTC), until))
    )


def _intervals(raw_intervals):
    intervals = []
    for obj in raw_intervals:
        lo = parse_time(obj["start"])
        hi = parse_time(obj["until"])
        if lo >= hi:
            raise ValueError("Outage interval must have start < until")
        intervals.append((lo, hi))
    return intervals


def _captured(t: datetime, downtime) -> bool:
    return not any(lo <= t < hi for lo, hi in downtime)


def replay(manifest: dict[str, Any], start: str, until: str, *, policy: str = "historical",
           availability_lag_minutes: int = 0, outage_intervals=None) -> dict[str, Any]:
    """Classify only SOURCE-LISTED advisories under explicit hypothetical polls.

    Not an estimate of total storm-advisory omission rate until the external
    catalog has been independently confirmed complete (including preceding
    and subsequent advisories around the time boundaries).
    """
    lo, hi = parse_time(start), parse_time(until)
    if lo >= hi:
        raise ValueError("Invalid replay interval")
    if policy not in {"historical", "legacy", "reduced", "event_driven"}:
        raise ValueError("Unknown schedule policy")
    if type(availability_lag_minutes) is not int or not 0 <= availability_lag_minutes <= 360:
        raise ValueError("availability_lag_minutes must be integer 0..360")
    expected, _ = validate_manifest(manifest)
    by_storm = defaultdict(list)
    for key in sorted(expected):
        if lo <= key.issued_at < hi:
            by_storm[key.storm_id].append(key)
    ticks = sorted(set({"historical": mixed_ticks, "legacy": legacy_ticks,
                       "reduced": reduced_ticks, "event_driven": event_discovery_ticks}[policy](lo, hi)))
    downtime = _intervals(outage_intervals or [])
    lag = timedelta(minutes=availability_lag_minutes)
    found = set()
    event_dispatch_ticks = set()
    if policy == "historical" and lo < POLICY_CHANGE_UTC < hi:
        policy_assurance = "historical_schedule_transition_from_merged_pr55"
    else:
        policy_assurance = "configured_scenario"
    # Determine what each poll would have selected. No rows are taken from
    # OCHA's production DB, and no schedules or outputs are altered.
    for tick in ticks:
        if not _captured(tick, downtime):
            continue
        for keys in by_storm.values():
            eligible = [k for k in keys if k.issued_at + lag <= tick]
            if eligible:
                newest = eligible[-1]
                if newest not in found:
                    event_dispatch_ticks.add(tick)
                found.add(newest)
    records = []
    for keys in by_storm.values():
        for i, key in enumerate(keys):
            available = key.issued_at + lag
            nxt = keys[i + 1].issued_at + lag if i + 1 < len(keys) else hi
            can_poll = [t for t in ticks if available <= t < nxt]
            working_polls = [t for t in can_poll if _captured(t, downtime)]
            # Last sample of a subset can be censored by missing later NOAA
            # products; do not claim that its presence proves real coverage.
            if key in found:
                status = "modeled_selected"
            elif available >= hi:
                status = "not_yet_available_by_window_end"
            elif can_poll and not working_polls:
                status = "modeled_outage_gap"
            elif not can_poll:
                status = "modeled_schedule_gap"
            else:
                status = "model_inconsistency"
            row = {
                "storm_id": key.storm_id,
                "issued_at": iso(key.issued_at),
                "source_ref": expected[key]["source_ref"],
                "status": status,
                "nominal_poll_opportunities": len(can_poll),
                "healthy_poll_opportunities": len(working_polls),
                "edge_censored": i == 0 or i == len(keys) - 1,
            }
            records.append(row)
    records.sort(key=lambda x: (x["issued_at"], x["storm_id"]))
    counts = Counter(x["status"] for x in records)
    return {
        "schema_version": 1, "kind": "schedule_counterfactual_not_production_observations",
        "policy": policy, "policy_assurance": policy_assurance,
        "window": {"start": iso(lo), "until": iso(hi)},
        "assumptions": {
            "feed": "latest_known_product_per_storm_at_each_poll",
            "availability_lag_minutes": availability_lag_minutes,
            "publication_times_known": False,
            "event_driven_assumes_reliable_noaa_feed_polling_and_deduplication": policy == "event_driven",
            "catalog_completeness": manifest.get("catalog_completeness", "not_established"),
            "downtime_is_scenario": bool(downtime),
        },
        "poll_count": len(ticks),
        # Scheduled policies represent heavy scheduled job invocations (even
        # when no eligible new advisory exists). The event-driven candidate
        # separates cheap metadata polling from expensive processing triggers.
        "modeled_heavy_job_invocations": (
            len(event_dispatch_ticks) if policy == "event_driven" else len(ticks)
        ),
        "blocked_polls": sum(not _captured(t, downtime) for t in ticks),
        "counts": dict(sorted(counts.items())),
        "records": records,
        "limitations": [
            "Only source-listed advisories are modeled. Do not infer total missed-advisory counts or full recall from a partial catalog.",
            "NOAA nominal issuance is not the actual first-published or first-retrieved time. Availability lag is hypothetical.",
            "Modeled schedule gaps may be intentional cost-saving policy and are not necessarily unexpected production failures.",
            "First/last advisories per storm may be censored by out-of-scope source products.",
            "No actual NHC CurrentStorms JSON state, DBX run status, DB snapshots, or impact-trigger outcomes are verified.",
            "Storms may have ended between polls; the model assumes source-listed storms remain eligible through the replay window.",
            "Event-driven polling/dispatch is a proposed architecture, not an observed available deployment or a tested cost estimate.",
        ],
    }


def scenario_grid(manifest: dict, start: str, until: str, *, lags=(0, 15, 30, 60), outage_intervals=None) -> dict:
    scenarios = []
    for policy in ("legacy", "reduced", "historical", "event_driven"):
        for lag in lags:
            r = replay(manifest, start, until, policy=policy,
                       availability_lag_minutes=lag, outage_intervals=outage_intervals)
            scenarios.append({"policy": policy, "availability_lag_minutes": lag,
                              "polls": r["poll_count"], "modeled_heavy_job_invocations": r["modeled_heavy_job_invocations"],
                              "blocked_polls": r["blocked_polls"],
                              "counts": r["counts"]})
    return {"kind": "bounded_source_catalog_sensitivity_analysis", "scenarios": scenarios,
            "warning": "Scenario counts describe the supplied catalog, not complete real-world NOAA or OCHA coverage."}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--policy", choices=["historical", "legacy", "reduced", "event_driven"], default="historical")
    p.add_argument("--lag-minutes", type=int, default=0)
    p.add_argument("--outages", help="Optional JSON list of modeled outage intervals")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text())
    outages = json.loads(Path(args.outages).read_text()) if args.outages else []
    result = replay(manifest, args.start, args.until, policy=args.policy,
                    availability_lag_minutes=args.lag_minutes, outage_intervals=outages)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"polls": result["poll_count"], "modeled_heavy_job_invocations": result["modeled_heavy_job_invocations"], "blocked_polls": result["blocked_polls"], "counts": result["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
