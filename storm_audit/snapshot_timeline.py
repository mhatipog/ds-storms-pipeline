"""Evidence-aware NOAA CurrentStorms snapshot reconciliation (offline by default).

The source's ``publicAdvisory.issuance`` is a nominal advisory timestamp;
``fileUpdateTime`` is a source-product file timestamp; ``observed_at`` is a
*provided* snapshot capture timestamp. None proves the actual publication or
first-availability time without an independently audited collection log.

Only explicit, hashed JSON snapshots can contribute positive observations.
An absent storm in a CurrentStorms snapshot is NOT evidence that a particular
advisory was unavailable: the storm may not yet exist or may have ended.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

from .core import iso, parse_time

STORM_ID = re.compile(r"^(?:AL|EP|CP)\d{2}20\d{2}$", re.I)
ADV = re.compile(r"^0*([1-9]\d{0,2})([A-Z]?)$", re.I)
ARCHIVE_HOST = "www.nhc.noaa.gov"
INDEX_ROOT = "https://www.nhc.noaa.gov/archive/activeJson/"
MAX_BYTES = 2_000_000
MODES = {"synthetic_scenario", "retrospective_archive", "independent_poll_log"}


class SourceIntegrityError(ValueError):
    """Fail closed when an alleged source record cannot be audited."""


def canonical_advisory_id(value: str) -> str:
    if not isinstance(value, str):
        raise SourceIntegrityError("Advisory number must be a string")
    m = ADV.fullmatch(value.strip().upper())
    if not m:
        raise SourceIntegrityError(f"Invalid public-advisory number: {value!r}")
    return f"{int(m.group(1))}{m.group(2)}"


def parse_current_storms(raw: bytes) -> dict:
    """Extract public advisory identity from NOAA's documented feed schema.

    Do not mistake forecastAdvisory, windSpeedProbabilities or lastUpdate for
    new public-advisory events. Ignore missing publicAdvisory products but
    reject malformed active storm data rather than silently losing records.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise SourceIntegrityError("CurrentStorms JSON must be bytes <= 2 MB")
    try:
        obj = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as e:
        raise SourceIntegrityError("Invalid CurrentStorms JSON") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("activeStorms"), list):
        raise SourceIntegrityError("CurrentStorms root requires activeStorms array")
    seen_storms = set()
    out = {}
    for s in obj["activeStorms"]:
        if not isinstance(s, dict):
            raise SourceIntegrityError("Storm entry must be an object")
        storm_id = s.get("id")
        if not isinstance(storm_id, str) or not STORM_ID.fullmatch(storm_id):
            raise SourceIntegrityError(f"Invalid NOAA storm ID: {storm_id!r}")
        storm_id = storm_id.upper()
        if storm_id in seen_storms:
            raise SourceIntegrityError("Multiple activeStorms entries with same ID")
        seen_storms.add(storm_id)
        pa = s.get("publicAdvisory")
        if pa is None:
            continue
        if not isinstance(pa, dict):
            raise SourceIntegrityError("publicAdvisory must be an object or null")
        no, issue = pa.get("advNum"), pa.get("issuance")
        # NOAA uses strings such as "043" and "043A".
        if no is None or issue is None:
            raise SourceIntegrityError("Missing publicAdvisory identity fields")
        issued_at = iso(parse_time(issue))
        if int(issued_at[:4]) != int(storm_id[-4:]):
            raise SourceIntegrityError("Advisory year disagrees with storm ID")
        file_updated = pa.get("fileUpdateTime")
        if file_updated is not None:
            # Retain NOAA's sub-second file timestamp; this is source
            # metadata, NOT inferred first publication/availability.
            file_updated = (parse_time(file_updated).isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z"))
        out[storm_id] = {
            "product_id": canonical_advisory_id(no),
            "issued_at": issued_at,
            "file_update_time": file_updated,
        }
    return {"active_storm_ids": sorted(seen_storms), "public_advisories": out}


def _read_limited(path: Path) -> bytes:
    if path.stat().st_size > MAX_BYTES:
        raise SourceIntegrityError("Snapshot exceeds size limit")
    return path.read_bytes()


def read_snapshot_index(index: dict, base_dir: Path) -> dict:
    """Verify explicit, local snapshots with no path traversal or network I/O.

    Entries have ``path``, ``observed_at``, ``sha256`` and ``source_url``.
    ``observed_at`` is an *attested capture timestamp*, not automatically
    inferred from the archive's mutable directory Last-modified column.
    """
    if index.get("schema_version") != 1 or index.get("mode") not in MODES:
        raise SourceIntegrityError("Explicit version and capture mode required")
    entries = index.get("snapshots")
    if not isinstance(entries, list) or not entries:
        raise SourceIntegrityError("At least one snapshot is required")
    base_dir = Path(base_dir).resolve()
    result = []
    seen_time = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SourceIntegrityError("Malformed snapshot entry")
        raw_name = entry.get("path")
        if not isinstance(raw_name, str) or not raw_name or "\\" in raw_name:
            raise SourceIntegrityError("Unsafe snapshot path")
        rel = Path(raw_name)
        if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() != ".json":
            raise SourceIntegrityError("Snapshot path must be relative .json")
        resolved = (base_dir / rel).resolve()
        if not resolved.is_relative_to(base_dir):
            raise SourceIntegrityError("Snapshot escapes base directory")
        if not resolved.is_file():
            raise SourceIntegrityError(f"Snapshot does not exist: {raw_name}")
        at = iso(parse_time(entry["observed_at"]))
        if at in seen_time:
            raise SourceIntegrityError("Two snapshots claim the same capture instant")
        seen_time.add(at)
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise SourceIntegrityError("Every snapshot requires a SHA256 digest")
        url = entry.get("source_url")
        if index["mode"] == "retrospective_archive":
            if not isinstance(url, str) or not url.startswith(INDEX_ROOT):
                raise SourceIntegrityError("Archive source must be official NOAA URL")
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != ARCHIVE_HOST or not re.fullmatch(
                r"/archive/activeJson/20\d{2}/CurrentStorms_[^/]+\.json", parsed.path
            ) or parsed.query or parsed.fragment:
                raise SourceIntegrityError("Unexpected NOAA archive URL shape")
        else:
            if url is not None and not isinstance(url, str):
                raise SourceIntegrityError("source_url must be a string or null")
        data = _read_limited(resolved)
        actual = sha256(data).hexdigest()
        if actual.lower() != digest.lower():
            raise SourceIntegrityError(f"Snapshot hash mismatch for {raw_name}")
        normalized = parse_current_storms(data)
        result.append({"observed_at": at, "sha256": actual, "source_url": url,
                       "path": raw_name, **normalized})
    result.sort(key=lambda r: r["observed_at"])
    return {"mode": index["mode"], "snapshots": result,
            "snapshot_count": len(result), "hash_verified": len(result)}


def reconcile_timeline(advisory_manifest: dict, snapshots: dict) -> dict:
    """Join explicitly listed source products to hashed evidence snapshots.

    A positive snapshot proves observation at the *claimed capture time*.
    If an earlier successfully captured snapshot contains the same active storm
    with a DIFFERENT public advisory, the change is bracketed by these two
    captures. It does not prove actual NHC publication time.
    """
    expected = advisory_manifest.get("expected_advisories")
    if not isinstance(expected, list):
        raise SourceIntegrityError("Manifest requires expected_advisories")
    if snapshots.get("mode") not in MODES:
        raise SourceIntegrityError("Missing snapshot evidence mode")
    seq = snapshots.get("snapshots")
    if not isinstance(seq, list) or not seq:
        raise SourceIntegrityError("No verified snapshot sequence")
    modes = {"synthetic_scenario":"synthetic_only",
             "retrospective_archive":"retrospective_archived_capture",
             "independent_poll_log":"reported_original_poll_capture"}
    expected_keys = set()
    records = []
    for row in expected:
        storm_id = row.get("storm_id")
        if not isinstance(storm_id, str) or not STORM_ID.fullmatch(storm_id):
            raise SourceIntegrityError("Invalid expected storm ID")
        storm_id = storm_id.upper()
        issued_at = iso(parse_time(row["issued_at"]))
        product_id = canonical_advisory_id(row["product_id"])
        key = (storm_id, issued_at, product_id)
        if key in expected_keys:
            raise SourceIntegrityError("Duplicate expected advisory identity")
        expected_keys.add(key)
        first = None
        last_prior_other = None
        positives = 0
        disagreements = []
        update_times = []
        for snap in seq:
            at = snap["observed_at"]
            pa = snap["public_advisories"].get(storm_id)
            if pa is None:
                # An absent storm does not establish the advisory was absent.
                continue
            if pa["product_id"] == product_id:
                if pa["issued_at"] != issued_at:
                    disagreements.append({"capture_at":at,"reported_issue":pa["issued_at"]})
                    continue
                positives += 1
                update_times.append({"observed_at":at,
                                     "file_update_time":pa["file_update_time"]})
                if first is None:
                    first = snap
            elif first is None:
                last_prior_other = snap
        distinct_update_times = sorted({x["file_update_time"] for x in update_times
                                        if x["file_update_time"] is not None})
        # A changed NOAA product-file timestamp for the *same* advisory
        # identity may indicate an in-place revision. It is not proof
        # that the textual advisory content or forecast changed.
        revision_candidate = len(distinct_update_times) > 1
        result = {
            "storm_id": storm_id,
            "issued_at": issued_at,
            "product_id": product_id,
            "source_ref":row.get("source_ref"),
            "observed_in_snapshots": positives,
            "first_observed_at": first["observed_at"] if first else None,
            "first_observed_source": first["source_url"] if first else None,
            "first_observed_sha256":first["sha256"] if first else None,
            "last_explicitly_different_at":last_prior_other["observed_at"] if last_prior_other else None,
            "source_file_update_time": (
                first["public_advisories"][storm_id]["file_update_time"] if first else None
            ),
            "identity_conflicts":disagreements,
            "source_revision_candidate":revision_candidate,
            "source_file_update_times":distinct_update_times,
            "status": ("identity_conflict_needs_review" if disagreements else
                       "possible_source_revision_needs_review" if revision_candidate else
                       "observed_in_supplied_snapshots" if first else
                       "not_observed_coverage_unknown"),
            "interval_assurance":("bounded_between_captures_not_publication_time"
                                   if first and last_prior_other else
                                   "upper_bound_only_not_publication_time"
                                   if first else "no_positive_observation"),
        }
        records.append(result)
    records.sort(key=lambda r:(r["issued_at"],r["storm_id"],r["product_id"]))
    return {
        "schema_version":1,
        "kind":"verified_snapshot_observation_not_operational_ingestion",
        "evidence_mode":snapshots["mode"],
        "evidence_assurance":modes[snapshots["mode"]],
        "snapshot_count":len(seq),
        "expected_source_products":len(records),
        "observed_product_count":sum(r["first_observed_at"] is not None for r in records),
        "possible_revision_count":sum(r["source_revision_candidate"] for r in records),
        "not_observed_count":sum(r["status"]=="not_observed_coverage_unknown" for r in records),
        "identity_conflict_count":sum(bool(r["identity_conflicts"]) for r in records),
        "records":records,
        "limitations":[
            "Archived snapshot index timestamps are not NHC first publication times.",
            "The provided capture times are user-supplied metadata; SHA256 proves file integrity, not contemporaneous capture authenticity.",
            "NOAA's CurrentStorms is latest-per-storm: a product may exist and never appear in sparse captures.",
            "An absent storm cannot prove a public advisory was unavailable.",
            "Different fileUpdateTime values for one advisory are possible revision signals, not confirmed changed bulletin content.",
            "The directory archive may omit snapshots or backfill files; no unconditional completeness claim is possible.",
            "No OCHA ingestion, Databricks processing or downstream impact is observed.",
        ],
    }


class _DirectoryLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)


def noaa_directory_urls(index_html: str, year: int) -> list[str]:
    """Extract actual href targets, never display-shortened link labels.

    A catalog of hrefs is NOT evidence of archived file contents or
    publication times. No implicit network access.
    """
    if type(year) is not int or not 2020 <= year <= 2100:
        raise ValueError("Bad NOAA archive year")
    base = f"{INDEX_ROOT}{year}/"
    parser = _DirectoryLinks()
    parser.feed(index_html)
    found = set()
    for href in parser.hrefs:
        absolute = urljoin(base,href)
        parsed=urlsplit(absolute)
        if (parsed.scheme != "https" or parsed.netloc != ARCHIVE_HOST or
                parsed.query or parsed.fragment or not absolute.startswith(base)):
            continue
        filename=parsed.path.rsplit("/",1)[-1]
        if not re.fullmatch(r"CurrentStorms_20\d{2}-[^/]+\.json", filename):
            continue
        if not filename.startswith(f"CurrentStorms_{year}-"):
            continue
        found.add(absolute)
    return sorted(found)


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshots-index",required=True,help="Explicit hashed local snapshot manifest JSON")
    p.add_argument("--manifest",required=True,help="Expected NOAA public products")
    p.add_argument("--out",required=True,help="Report JSON path")
    args=p.parse_args(argv)
    ind=Path(args.snapshots_index)
    src=json.loads(ind.read_text(encoding="utf8"))
    snaps=read_snapshot_index(src,ind.parent)
    man=json.loads(Path(args.manifest).read_text(encoding="utf8"))
    report=reconcile_timeline(man,snaps)
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({k:report[k] for k in (
        "evidence_assurance","snapshot_count","observed_product_count","not_observed_count","identity_conflict_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
