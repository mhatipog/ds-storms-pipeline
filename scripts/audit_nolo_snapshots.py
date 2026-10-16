import json
from pathlib import Path
from hashlib import sha256

archive_dir = Path("./noaa-archive")
files = sorted(list(archive_dir.glob("CurrentStorms_*.json")))

print(f"Total snapshot files found: {len(files)}")

adv_payloads = {}
file_summaries = []

for fp in files:
    raw = fp.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    nolo = None
    for s in data["activeStorms"]:
        if s["id"].upper() == "EP152026":
            nolo = s
            break
    
    if not nolo:
        print(f"WARNING: EP152026 missing from {fp.name}")
        continue
    
    pa = nolo.get("publicAdvisory") or {}
    fa = nolo.get("forecastAdvisory") or {}
    lu = nolo.get("lastUpdate")
    adv_num = pa.get("advNum")
    
    adv_payloads.setdefault(adv_num, []).append({
        "file": fp.name,
        "sha256": sha256(raw).hexdigest(),
        "nolo_raw": nolo,
        "lastUpdate": lu,
        "publicAdvisory": pa,
        "forecastAdvisory": fa
    })
    
    file_summaries.append({
        "file": fp.name,
        "adv_num": adv_num,
        "lastUpdate": lu,
        "pa_issuance": pa.get("issuance"),
        "pa_fileUpdate": pa.get("fileUpdateTime"),
        "fa_advNum": fa.get("advNum"),
        "fa_issuance": fa.get("issuance"),
        "fa_url": fa.get("url")
    })

print(f"Total Nolo entries: {len(file_summaries)}")
print("\n" + "="*80)
print("INSPECTION OF NOLO FIELDS BY ADVISORY")
print("="*80)

for adv, entries in sorted(adv_payloads.items(), key=lambda x: str(x[0])):
    print(f"\n--- Advisory {adv} ({len(entries)} snapshots) ---")
    first = entries[0]
    print(f"Files: {entries[0]['file']} -> {entries[-1]['file']}")
    print(f"lastUpdate: {first['lastUpdate']}")
    print(f"publicAdvisory: {json.dumps(first['publicAdvisory'], indent=2)}")
    print(f"forecastAdvisory: {json.dumps(first['forecastAdvisory'], indent=2)}")
    
    # Check if Nolo object itself changed in any way across the snapshots
    first_nolo_str = json.dumps(first["nolo_raw"], sort_keys=True)
    all_nolo_identical = all(json.dumps(e["nolo_raw"], sort_keys=True) == first_nolo_str for e in entries)
    print(f"All {len(entries)} snapshots have IDENTICAL Nolo object: {all_nolo_identical}")
    if not all_nolo_identical:
        # Find differences
        for idx, e in enumerate(entries[1:], 1):
            diffs = []
            for k in set(first["nolo_raw"].keys()).union(e["nolo_raw"].keys()):
                if first["nolo_raw"].get(k) != e["nolo_raw"].get(k):
                    diffs.append((k, first["nolo_raw"].get(k), e["nolo_raw"].get(k)))
            if diffs:
                print(f"  Diff in {e['file']}: {diffs}")
