"""Run: python -m storm_audit --help"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .collector import collect_postgres
from .core import audit, markdown_report


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent read-only NHC advisory completeness audit")
    parser.add_argument("--manifest", required=True, help="Independent expected-advisories JSON")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot", help="JSON table-presence snapshot; does not need network/DB")
    src.add_argument("--dsn-env", help="Environment variable containing PostgreSQL DSN (never log it)")
    parser.add_argument("--lookahead-hours", type=int, default=48)
    parser.add_argument("--output", help="Write full JSON report here")
    parser.add_argument("--markdown", help="Write human-readable report here")
    parser.add_argument("--save-snapshot", help="Save collected JSON snapshot for reproducibility")
    parser.add_argument("--fail-on-gaps", action="store_true", help="Exit code 2 for a confirmed raw advisory gap")
    args = parser.parse_args(argv)
    try:
        manifest = load_json(args.manifest)
        if args.snapshot:
            snapshot = load_json(args.snapshot)
        else:
            dsn = os.environ.get(args.dsn_env, "")
            if not dsn:
                raise ValueError(f"Environment variable {args.dsn_env!r} is not set")
            snapshot = collect_postgres(manifest, dsn, args.lookahead_hours)
        result = audit(manifest, snapshot)
        if snapshot.get("scan_warnings"):
            result["scan_warnings"] = snapshot["scan_warnings"]
        report = markdown_report(result)
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if args.markdown:
            Path(args.markdown).write_text(report, encoding="utf-8")
        if args.save_snapshot:
            Path(args.save_snapshot).write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(report)
        if args.fail_on_gaps and result["counts"].get("EXPECTED_RAW_ABSENT", 0):
            return 2
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Audit not completed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
