"""Handle NOAA Apache archive INDEX rows without inventing JSON contents.

The web-rendered directory truncates clickable filenames in its display. Its
last-modified column is not a verified original capture/publication timestamp.
The reported rows therefore cannot contribute positive advisory observations.
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from .core import iso, parse_time


class ListingEvidenceError(ValueError):
    pass


def audit_listing(data: dict) -> dict:
    if data.get("schema_version") != 1:
        raise ListingEvidenceError("Unsupported directory listing")
    if data.get("source_index") not in (
        "https://www.nhc.noaa.gov/archive/activeJson/2026/",
        "https://prod-east-nhc.woc.noaa.gov/archive/activeJson/2026/",
    ):
        raise ListingEvidenceError("Index source must be the authorized NOAA path")
    if data.get("utc_day") != "2026-10-01":
        raise ListingEvidenceError("This bounded study only covers 2026-10-01")
    rows = data.get("visible_rows")
    if not isinstance(rows, list) or not rows:
        raise ListingEvidenceError("No listing rows")
    dates = []
    for r in rows:
        if r.get("display_label_truncated") is not True or r.get("full_href_verified") is not False:
            raise ListingEvidenceError("Cannot mix unverified truncated labels and verified URLs")
        if r.get("file_content_accessible") is not False:
            raise ListingEvidenceError("Cannot claim archive contents were read")
        day = parse_time(r["directory_last_modified_utc"])
        if not ("2026-10-01T00:00:00Z" <= iso(day) < "2026-10-02T00:00:00Z"):
            raise ListingEvidenceError("Index row outside audited day")
        if r.get("size_label") != "14K":
            raise ListingEvidenceError("Unexpected listing size; review against actual index")
        dates.append(day)
    if dates != sorted(set(dates)):
        raise ListingEvidenceError("Duplicate or out-of-order index timestamps")
    gaps = [int((b-a).total_seconds()/60) for a,b in zip(dates,dates[1:])]
    regular = [3,9,15,21]
    schedule = []
    for hour in regular:
        tick = parse_time(f"2026-10-01T{hour:02d}:30:00Z")
        past = [d for d in dates if d <= tick]
        candidate = past[-1] if past else None
        schedule.append({
            "poll_at":iso(tick),
            "latest_directory_row_before_poll": iso(candidate) if candidate else None,
            "listing_delta_minutes": round((tick-candidate).total_seconds()/60) if candidate else None,
            "advisory_identity_verified": False,
            "poll_was_executed_by_ocha": None,
        })
    return {
        "kind":"real_noaa_directory_listing_metadata_not_json_capture",
        "source_index":data["source_index"],
        "source_access":"rendered_directory_listing_only",
        "visible_rows":len(rows),
        "first_listed_utc":iso(dates[0]),
        "last_listed_utc":iso(dates[-1]),
        "max_inter_row_gap_minutes":max(gaps) if gaps else 0,
        "reduced_schedule_index_crosscheck":schedule,
        "json_documents_downloaded":0,
        "advisory_identities_verified_from_json":0,
        "publication_latency_measured":False,
        "ocha_ingestion_access":False,
        "limits":[
            "File labels were truncated in the rendered HTML directory, so exact hrefs are not verified.",
            "The Last modified column is a directory-file metadata value, not proven original NHC publication or snapshot capture time.",
            "Historical JSON bytes and SHA256 are unavailable; no advisory identity is determined from this listing.",
            "Relative proximity to a polling tick neither proves that a particular advisory was in the file nor that OCHA polled.",
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index-evidence",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    report=audit_listing(json.loads(Path(args.index_evidence).read_text()))
    Path(args.output).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"visible_index_rows":report["visible_rows"],"verified_json":0}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
