"""Convert a reviewed external advisory catalog CSV into audit expectations.

CSV is an independently sourced artifact. Never invent advisories from a
regular 3/6-hour cadence; special advisories have irregular timing.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .core import Key, STAGES


def build_from_csv(path: str, description: str = "Review source references before treating as authoritative",
                   assurance: str = "unverified") -> dict:
    if assurance not in ("unverified", "illustrative", "source_verified"):
        raise ValueError("assurance must be unverified, illustrative or source_verified")
    records = []
    seen = set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"storm_id", "issued_at", "source_ref"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV requires storm_id, issued_at, source_ref columns")
        for row in reader:
            key = Key.from_dict(row)
            if key in seen:
                raise ValueError(f"Duplicate advisory in catalog: {key.to_dict()}")
            seen.add(key)
            source_ref = row.get("source_ref", "").strip()
            if not source_ref:
                raise ValueError(f"Missing source_ref: {key.to_dict()}")
            stages = [x.strip() for x in (row.get("required_stages") or "raw_tracks").split("|")]
            if not stages or "raw_tracks" not in stages or not set(stages) <= set(STAGES):
                raise ValueError(f"Invalid required_stages for {key.to_dict()}")
            records.append({**key.to_dict(), "source_ref": source_ref, "required_stages": stages})
    return {"schema_version": 1, "source_description": description,
            "source_assurance": assurance,
            "expected_advisories": [x for x in sorted(records, key=lambda x: (x["storm_id"], x["issued_at"]))]}


def main():
    parser = argparse.ArgumentParser(description="Build expected-advisory manifest from reviewed CSV")
    parser.add_argument("csv", help="Independent advisory catalog; never infer cadence")
    parser.add_argument("output")
    parser.add_argument("--source-description", default="External advisory catalog")
    parser.add_argument("--source-assurance", default="unverified",
                        choices=["unverified", "illustrative", "source_verified"])
    args = parser.parse_args()
    result = build_from_csv(args.csv, args.source_description, args.source_assurance)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['expected_advisories'])} advisory expectations to {args.output}")


if __name__ == "__main__":
    main()
