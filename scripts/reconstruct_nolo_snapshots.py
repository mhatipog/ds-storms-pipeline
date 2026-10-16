import json
from pathlib import Path
import csv
from storm_audit.snapshot_timeline import parse_current_storms

archive_dir = Path("./noaa-archive")
retrieval_log_path = archive_dir / "noaa-retrieval-log.json"
manifest_path = Path("./examples/noaa_nolo_2026-10-01_public_day.json")

log = json.loads(retrieval_log_path.read_text(encoding="utf-8"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

expected_advisories = {a["product_id"]: a for a in manifest["expected_advisories"]}

rows = []
for entry in log["files"]:
    fn = entry["filename"]
    fp = archive_dir / fn
    data = fp.read_bytes()
    parsed = parse_current_storms(data)

    nolo_pa = parsed["public_advisories"].get("EP152026")
    contains_nolo = "EP152026" in parsed["active_storm_ids"]

    rows.append({
        "filename": fn,
        "source_url": entry["source_url"],
        "sha256": entry["sha256"],
        "retrieved_at": entry["retrieved_at"],
        "contains_nolo": contains_nolo,
        "active_storm_ids": ",".join(parsed["active_storm_ids"]),
        "nolo_advisory_id": nolo_pa["product_id"] if nolo_pa else "",
        "nolo_issuance": nolo_pa["issued_at"] if nolo_pa else "",
        "nolo_file_update_time": nolo_pa["file_update_time"] if nolo_pa else "",
    })

print(f"Total snapshots processed: {len(rows)}")
contains_count = sum(1 for r in rows if r["contains_nolo"])
print(f"Snapshots containing EP152026: {contains_count}")

# Check which expected advisories are seen
seen_advisories = set(r["nolo_advisory_id"] for r in rows if r["nolo_advisory_id"])
print(f"Unique Nolo advisories found in snapshots: {sorted(seen_advisories)}")
print(f"Expected advisories from manifest: {sorted(expected_advisories.keys())}")
missing = set(expected_advisories.keys()) - seen_advisories
print(f"Missing advisories: {sorted(missing)}")

# Group snapshots by advisory
advisory_to_files = {}
for r in rows:
    adv = r["nolo_advisory_id"] or "NONE"
    advisory_to_files.setdefault(adv, []).append(r["filename"])

for adv, files in sorted(advisory_to_files.items()):
    print(f"  Advisory {adv} ({len(files)} files): {files[0]} ... {files[-1]}")
