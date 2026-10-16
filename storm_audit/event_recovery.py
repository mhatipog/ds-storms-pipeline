"""Counterfactual event signals + independent archive reconciliation.

This is NOT a NOAA harvesting agent or a Databricks scheduler. Archive content
and availability are provided explicitly; expected source products are not
fabricated from an advisory cadence. A partial archive input cannot justify a
full-coverage conclusion. The durable queue remains pending until a verified
worker outcome is supplied by a separately reviewed integration.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timedelta
import json
from pathlib import Path
import tempfile

from .core import iso, parse_time
from .policy_replay import _intervals, _captured
from .resilient_dispatch import AdvisoryQueue, _rows


def _grid(start, until, hours):
    # Anchor reconciliation to UTC day boundary rather than to the first
    # requested replay tick; makes adjacent replay windows consistent.
    t=start.replace(hour=0,minute=0,second=0,microsecond=0)
    while t<until:
        if start<=t:
            yield t
        t+=timedelta(hours=hours)


def replay_recovery(manifest: dict, start: str, until: str, *,
                    feed_poll_minutes: int = 30, archive_scan_hours: int = 6,
                    feed_availability_lag_minutes: int = 0,
                    archive_availability_lag_minutes: int = 0,
                    outage_intervals=None,
                    dispatch_cooldown_minutes: int = 60,
                    max_heavy_batches_per_day: int = 8) -> dict:
    lo,hi=parse_time(start),parse_time(until)
    if type(dispatch_cooldown_minutes) is not int or not 0 <= dispatch_cooldown_minutes <= 1440:
        raise ValueError("dispatch cooldown must be 0..1440 minutes")
    if type(max_heavy_batches_per_day) is not int or not 1 <= max_heavy_batches_per_day <= 96:
        raise ValueError("daily heavy job budget must be 1..96")
    if lo>=hi:
        raise ValueError("start must precede until")
    if type(feed_poll_minutes) is not int or feed_poll_minutes not in (5,10,15,30,60):
        raise ValueError("feed polling must be 5,10,15,30,60 minutes")
    if type(archive_scan_hours) is not int or not 1<=archive_scan_hours<=24 or 24%archive_scan_hours:
        raise ValueError("archive reconciliation cadence must divide 24 hours")
    if any(type(x) is not int or not 0<=x<=1440 for x in
           (feed_availability_lag_minutes,archive_availability_lag_minutes)):
        raise ValueError("availability lags must be integer minutes 0..1440")
    docs=manifest.get("expected_advisories",[])
    # Identity validation protects against accidentally combining two
    # different advisory products under one simulated work key.
    parsed=_rows(docs,"track")
    if len(parsed)!=len(docs):
        raise ValueError("Duplicate expected advisory identity")
    products=[]
    for row in docs:
        t=parse_time(row["issued_at"])
        if lo<=t<hi:
            products.append((t,row))
    by_storm=defaultdict(list)
    for issue,row in products:
        by_storm[row["storm_id"].upper()].append((issue,row))
    for items in by_storm.values():
        items.sort(key=lambda r:(r[0],r[1]["product_id"]))
    outages=_intervals(outage_intervals or [])
    polls=[]
    t=lo.replace(minute=0,second=0,microsecond=0)
    while t<hi:
        if lo<=t:
            polls.append(t)
        t+=timedelta(minutes=feed_poll_minutes)
    scans=list(_grid(lo,hi,archive_scan_hours))
    events=sorted([(t,"feed") for t in polls]+[(t,"archive") for t in scans],key=lambda x:(x[0],x[1]))
    feed_lag=timedelta(minutes=feed_availability_lag_minutes)
    archive_lag=timedelta(minutes=archive_availability_lag_minutes)
    with tempfile.TemporaryDirectory() as dirname:
        queue=AdvisoryQueue(Path(dirname)/"queue.sqlite")
        first_discovery={}
        origin={}
        successful_feed=successful_arch=0
        failed_feed=failed_arch=0
        hypothetical_batches=0
        seen_batched=set()
        dispatches=[]
        dispatches_by_day=defaultdict(int)
        last_dispatch=None
        for tick,kind in events:
            if not _captured(tick,outages):
                queue.scan_failed(stream="track",source=kind,now=iso(tick),diagnostic="simulated outage")
                if kind=="feed":failed_feed+=1
                else:failed_arch+=1
                continue
            if kind=="feed":
                successful_feed+=1
                found=[]
                for rows in by_storm.values():
                    eligible=[r for issuance,r in rows if issuance+feed_lag<=tick]
                    if eligible:
                        found.append(eligible[-1])
            else:
                successful_arch+=1
                # Hypothetical archive enumeration supplies *all available*
                # historical source products, not just latest-per-storm.
                found=[r for issue,r in products if issue+archive_lag<=tick]
            # Preserve first observed mechanism for each expected record.
            queue.ingest(found,source=kind,stream="track",now=iso(tick),
                         scan_complete=False,assurance="partial_input_uncertified")
            for r in found:
                k=(r["storm_id"].upper(),r["issued_at"],r["product_id"].upper())
                if k not in first_discovery:
                    first_discovery[k]=iso(tick)
                    origin[k]=kind
            # Budgeted dispatch planning: preserve every pending advisory,
            # including ones deferred by cooldown or the daily cost cap.
            # NO actual processing is executed by this replay.
            batch_keys=set(first_discovery)-seen_batched
            day=iso(tick)[:10]
            eligible_after_cooldown=(last_dispatch is None or
                tick-last_dispatch >= timedelta(minutes=dispatch_cooldown_minutes))
            if (batch_keys and eligible_after_cooldown and
                    dispatches_by_day[day]<max_heavy_batches_per_day):
                hypothetical_batches+=1
                dispatches_by_day[day]+=1
                seen_batched.update(batch_keys)
                last_dispatch=tick
                dispatches.append({"modeled_trigger_at":iso(tick),
                                   "advisories_in_batch":len(batch_keys)})
        queue_status=queue.report(now=iso(hi))
        records=[]
        for issue,row in sorted(products,key=lambda t:(t[0],t[1]["storm_id"],t[1]["product_id"])):
            k=(row["storm_id"].upper(),row["issued_at"],row["product_id"].upper())
            records.append({"storm_id":k[0],"issued_at":k[1],"product_id":k[2],
                            "discovered_at":first_discovery.get(k),
                            "discovery_channel":origin.get(k),
                            "status":"queued_for_hypothetical_processing" if k in first_discovery else "not_discovered_by_window_end"})
    nominal_delays=[round((parse_time(seen)-parse_time(k[1])).total_seconds()/60,3)
                    for k,seen in first_discovery.items()]
    return {
      "kind":"offline_policy_scenario_not_an_operational_result",
      "window":{"start":iso(lo),"until":iso(hi)},
      "subset_size":len(products),
      "source_catalog_completeness":manifest.get("catalog_completeness","not_established"),
      "recorded":len(first_discovery),
      "not_discovered":len(products)-len(first_discovery),
      "max_nominal_issue_to_first_detection_minutes":max(nominal_delays) if nominal_delays else None,
      "discovery_channel_counts":{
          "feed":sum(v=="feed" for v in origin.values()),
          "archive":sum(v=="archive" for v in origin.values())},
      "metadata_polls":{"scheduled":len(polls),"succeeded":successful_feed,"failed":failed_feed},
      "archive_scans":{"scheduled":len(scans),"succeeded":successful_arch,"failed":failed_arch},
      "hypothetical_heavy_batches":hypothetical_batches,
      "hypothetical_heavy_dispatches":dispatches,
      "undispatched_work_at_window_end":len(first_discovery)-len(seen_batched),
      "dispatch_policy":{"cooldown_minutes":dispatch_cooldown_minutes,
                         "max_heavy_batches_per_day":max_heavy_batches_per_day},
      "queue":{"state":queue_status["state"],"counts":queue_status["counts"]},
      "assumptions":{"feed":"latest-available-per-storm","archive":"all-provided-source-records-available-by-scan",
                     "feed_lag_minutes":feed_availability_lag_minutes,
                     "archive_lag_minutes":archive_availability_lag_minutes,
                     "reported_availability_is_scenario_not_measured":True},
      "records":records,
      "limitations":[
          "All products come only from the provided, possibly partial manifest; this does not establish actual NHC coverage.",
          "Archive availability and polling reliability are modeled, not measured; permanent source loss cannot be repaired by this algorithm.",
          "The simulated batching is NOT Databricks execution; queue work is left pending and no completion is claimed.",
          "Cost caps can defer downstream work; a nonzero undispatched backlog demands explicit liveness monitoring.",
          "Successful eventual discovery requires at least one successful archive scan after each source product becomes available.",
          "Separate WSP product stream, true downstream per-storm completion, and source correction handling still need reviewed integration.",
      ]}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--until",required=True)
    p.add_argument("--feed-minutes",type=int,default=30)
    p.add_argument("--archive-hours",type=int,default=6)
    p.add_argument("--feed-lag",type=int,default=0)
    p.add_argument("--archive-lag",type=int,default=0)
    p.add_argument("--outages")
    p.add_argument("--dispatch-cooldown",type=int,default=60)
    p.add_argument("--daily-batch-cap",type=int,default=8)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    manifest=json.loads(Path(args.manifest).read_text(encoding="utf8"))
    outages=json.loads(Path(args.outages).read_text()) if args.outages else []
    output=replay_recovery(manifest,args.start,args.until,feed_poll_minutes=args.feed_minutes,
                           archive_scan_hours=args.archive_hours,feed_availability_lag_minutes=args.feed_lag,
                           archive_availability_lag_minutes=args.archive_lag,outage_intervals=outages,
                           dispatch_cooldown_minutes=args.dispatch_cooldown,
                           max_heavy_batches_per_day=args.daily_batch_cap)
    Path(args.output).write_text(json.dumps(output,indent=2)+"\n",encoding="utf8")
    print(json.dumps({key:output[key] for key in ("subset_size","recorded","not_discovered","discovery_channel_counts","hypothetical_heavy_batches","undispatched_work_at_window_end")}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
