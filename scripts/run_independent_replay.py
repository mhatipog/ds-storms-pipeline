"""Independent Replay Engine and Red-Team Audit for NOAA 2026-10-01 Nolo Data.

Derives timeline, transitions, and polling visibility purely algorithmically
without hardcoding advisory-to-poll mappings.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from storm_audit.snapshot_timeline import parse_current_storms

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = REPO_ROOT / "noaa-archive"
MANIFEST_PATH = REPO_ROOT / "examples" / "noaa_nolo_2026-10-01_public_day.json"


def parse_snapshot_time(filename: str) -> datetime:
    """Extract nominal capture time from filename: CurrentStorms_YYYY-MM-DD-HHMM.json."""
    stem = filename.replace("CurrentStorms_", "").replace(".json", "")
    parts = stem.split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    hhmm = parts[3]
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def build_audit_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = sorted(list(ARCHIVE_DIR.glob("CurrentStorms_2026-10-01-*.json")))
    
    records = []
    for fp in files:
        raw = fp.read_bytes()
        digest = sha256(raw).hexdigest()
        snap_time = parse_snapshot_time(fp.name)
        parsed = parse_current_storms(raw)
        
        # Raw json for subsidiary fields
        full_json = json.loads(raw.decode("utf-8"))
        nolo_storm = next((s for s in full_json.get("activeStorms", []) if s.get("id", "").upper() == "EP152026"), None)
        
        pa = parsed["public_advisories"].get("EP152026")
        fa = nolo_storm.get("forecastAdvisory") if nolo_storm else None
        gis_wsp = nolo_storm.get("windSpeedProbabilitiesGIS") if nolo_storm else None
        cone = nolo_storm.get("trackCone") if nolo_storm else None
        
        records.append({
            "filename": fp.name,
            "nominal_time": snap_time,
            "nominal_time_iso": snap_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sha256": digest,
            "bytes": len(raw),
            "contains_nolo": "EP152026" in parsed["active_storm_ids"],
            "advisory_id": pa["product_id"] if pa else None,
            "nominal_issuance": pa["issued_at"] if pa else None,
            "pa_file_update_time": pa["file_update_time"] if pa else None,
            "fa_adv_num": fa.get("advNum") if fa else None,
            "fa_issuance": fa.get("issuance") if fa else None,
            "wsp_issuance": gis_wsp.get("issuance") if gis_wsp else None,
            "wsp_file_update_time": gis_wsp.get("fileUpdateTime") if gis_wsp else None,
            "cone_adv_num": cone.get("advNum") if cone else None,
            "active_storms": parsed["active_storm_ids"],
        })
    return records, manifest


def derive_advisory_lifecycles(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Derive for every advisory: earliest snapshot, latest snapshot, and first subsequent different advisory."""
    lifecycles = {}
    
    # Group chronologically
    advisory_order = []
    for r in records:
        adv = r["advisory_id"]
        if adv and (not advisory_order or advisory_order[-1] != adv):
            advisory_order.append(adv)
            
    for adv in set(r["advisory_id"] for r in records if r["advisory_id"]):
        snaps = [r for r in records if r["advisory_id"] == adv]
        first = snaps[0]
        last = snaps[-1]
        
        # Find first subsequent snapshot that contains a different advisory
        first_idx = records.index(first)
        last_idx = records.index(last)
        
        subsequent_different = None
        for r in records[last_idx + 1:]:
            if r["advisory_id"] and r["advisory_id"] != adv:
                subsequent_different = r
                break
                
        # Find last prior snapshot that contained a different advisory
        prior_different = None
        for r in reversed(records[:first_idx]):
            if r["advisory_id"] and r["advisory_id"] != adv:
                prior_different = r
                break

        lifecycles[adv] = {
            "advisory_id": adv,
            "snapshot_count": len(snaps),
            "earliest_snapshot": first["filename"],
            "earliest_nominal_time": first["nominal_time_iso"],
            "latest_snapshot": last["filename"],
            "latest_nominal_time": last["nominal_time_iso"],
            "last_prior_different_snapshot": prior_different["filename"] if prior_different else None,
            "last_prior_different_time": prior_different["nominal_time_iso"] if prior_different else None,
            "first_subsequent_different_snapshot": subsequent_different["filename"] if subsequent_different else None,
            "first_subsequent_different_time": subsequent_different["nominal_time_iso"] if subsequent_different else None,
            "superseded_by_advisory": subsequent_different["advisory_id"] if subsequent_different else None,
            "nominal_issuance": first["nominal_issuance"],
            "file_update_time": first["pa_file_update_time"],
        }
    return lifecycles


def simulate_polling_schedule(
    records: list[dict[str, Any]],
    poll_times_iso: list[str],
) -> list[dict[str, Any]]:
    """Algorithmically evaluate which advisory is visible at each polling instant."""
    results = []
    
    for pt_str in poll_times_iso:
        pt = datetime.fromisoformat(pt_str.replace("Z", "+00:00"))
        # Find latest snapshot at or before polling time
        eligible = [r for r in records if r["nominal_time"] <= pt]
        if not eligible:
            results.append({
                "poll_time_utc": pt_str,
                "visible_snapshot": None,
                "visible_advisory": None,
                "status": "before_first_archive_snapshot"
            })
            continue
            
        latest_snap = eligible[-1]
        results.append({
            "poll_time_utc": pt_str,
            "visible_snapshot": latest_snap["filename"],
            "visible_snapshot_time_utc": latest_snap["nominal_time_iso"],
            "visible_advisory": latest_snap["advisory_id"],
            "time_lag_minutes": (pt - latest_snap["nominal_time"]).total_seconds() / 60.0,
            "active_storms": latest_snap["active_storms"],
            "status": "advisory_conditionally_active"
        })
    return results


def run_frequency_simulations(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare OCHA's documented 6-hour schedule against 60m, 30m, and 15m polling grids."""
    # OCHA 6-hour schedule: 03:30, 09:30, 15:30, 21:30
    ocha_times = [
        "2026-10-01T03:30:00Z",
        "2026-10-01T09:30:00Z",
        "2026-10-01T15:30:00Z",
        "2026-10-01T21:30:00Z",
    ]
    ocha_sim = simulate_polling_schedule(records, ocha_times)
    ocha_captured = set(s["visible_advisory"] for s in ocha_sim if s["visible_advisory"])
    
    # Generate grids over the span of the day's snapshots: 02:30 to 23:30
    def make_grid(interval_minutes: int, offset_minutes: int = 0) -> list[str]:
        cur = datetime(2026, 10, 1, 2, 30, tzinfo=timezone.utc) + timedelta(minutes=offset_minutes)
        end = datetime(2026, 10, 1, 23, 45, tzinfo=timezone.utc)
        pts = []
        while cur <= end:
            pts.append(cur.strftime("%Y-%m-%dT%H:%M:%SZ"))
            cur += timedelta(minutes=interval_minutes)
        return pts

    grid_60_at_30 = make_grid(60, 0)   # :30 of every hour
    grid_60_at_00 = make_grid(60, 30)  # :00 of every hour
    grid_30 = make_grid(30, 0)         # :00 and :30
    grid_15 = make_grid(15, 0)         # every 15 min

    sim_60_30 = simulate_polling_schedule(records, grid_60_at_30)
    sim_60_00 = simulate_polling_schedule(records, grid_60_at_00)
    sim_30 = simulate_polling_schedule(records, grid_30)
    sim_15 = simulate_polling_schedule(records, grid_15)

    all_day_advisories = {"41A", "42", "42A", "43", "43A", "44", "44A", "45"}

    return {
        "ocha_6h": {
            "schedule_description": "4 runs/day at 03:30, 09:30, 15:30, 21:30 UTC",
            "polls": ocha_sim,
            "captured_advisories": sorted(list(ocha_captured)),
            "missed_advisories": sorted(list(all_day_advisories - ocha_captured)),
            "intermediate_capture_rate": len(ocha_captured & {"41A", "42A", "43A", "44A"}) / 4.0,
            "regular_capture_rate": len(ocha_captured & {"42", "43", "44", "45"}) / 4.0,
        },
        "hourly_at_30": {
            "schedule_description": "Hourly at :30 past the hour",
            "captured_advisories": sorted(list(set(s["visible_advisory"] for s in sim_60_30 if s["visible_advisory"]))),
            "missed_advisories": sorted(list(all_day_advisories - set(s["visible_advisory"] for s in sim_60_30 if s["visible_advisory"]))),
            "poll_count": len(sim_60_30),
        },
        "hourly_at_00": {
            "schedule_description": "Hourly at :00 (top of the hour)",
            "captured_advisories": sorted(list(set(s["visible_advisory"] for s in sim_60_00 if s["visible_advisory"]))),
            "missed_advisories": sorted(list(all_day_advisories - set(s["visible_advisory"] for s in sim_60_00 if s["visible_advisory"]))),
            "poll_count": len(sim_60_00),
        },
        "every_30min": {
            "schedule_description": "Every 30 minutes (:00 and :30)",
            "captured_advisories": sorted(list(set(s["visible_advisory"] for s in sim_30 if s["visible_advisory"]))),
            "missed_advisories": sorted(list(all_day_advisories - set(s["visible_advisory"] for s in sim_30 if s["visible_advisory"]))),
            "poll_count": len(sim_30),
        },
        "every_15min": {
            "schedule_description": "Every 15 minutes",
            "captured_advisories": sorted(list(set(s["visible_advisory"] for s in sim_15 if s["visible_advisory"]))),
            "missed_advisories": sorted(list(all_day_advisories - set(s["visible_advisory"] for s in sim_15 if s["visible_advisory"]))),
            "poll_count": len(sim_15),
        },
    }


def main():
    records, manifest = build_audit_records()
    lifecycles = derive_advisory_lifecycles(records)
    simulations = run_frequency_simulations(records)
    
    # Save independent-replay.json
    replay_data = {
        "schema_version": 1,
        "kind": "independent_nolo_archive_replay",
        "target_storm": "EP152026",
        "date_utc": "2026-10-01",
        "advisory_lifecycles": lifecycles,
        "polling_simulations": simulations,
        "all_snapshots_chronology": [
            {
                "filename": r["filename"],
                "nominal_utc": r["nominal_time_iso"],
                "sha256": r["sha256"],
                "advisory": r["advisory_id"],
                "file_update_time": r["pa_file_update_time"],
                "fa_adv_num": r["fa_adv_num"],
                "wsp_file_update_time": r["wsp_file_update_time"],
                "cone_adv_num": r["cone_adv_num"]
            }
            for r in records
        ]
    }
    
    out_json = REPO_ROOT / "independent-replay.json"
    out_json.write_text(json.dumps(replay_data, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {out_json}")


if __name__ == "__main__":
    main()
