"""Independent, conservative NOAA/NHC public-advisory archive acquisition.

- Only NOAA ``public`` and ``public_a`` etc. bulletin products count; forecast
  discussions / fstadv files are other representations of the same advisory.
- Product issuance time is NOT publication/first-available time.
- Catalogs may be incomplete and must not be used for false 'full coverage'
  claims without independent archive completeness review.
- No implicit network access: fetch only when ``--fetch`` is requested.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import argparse
import json
import re

from .core import iso, parse_time

HOST = "www.nhc.noaa.gov"
STORM_ID = re.compile(r"(?:AL|EP|CP)\d{2}\d{4}", re.I)
PRODUCT = re.compile(r"(?P<storm>(?:al|ep|cp)\d{2}\d{4})\.public(?P<suffix>_[a-z])?\.(?P<no>\d{3})\.shtml$", re.I)
DATE = re.compile(r"\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s+(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+(?P<year>20\d{2})\b", re.I)
HEADER = re.compile(r"(?P<clock>\d{3,4})\s*(?P<ampm>AM|PM)?\s+(?P<tz>UTC|GMT|HST|HAST|AST|ADT|EDT|EST|CDT|CST|MDT|MST|PDT|PST)\s+(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s+[A-Z]{3}\s+\d{1,2}\s+20\d{2}", re.I)
SUMMARY_UTC = re.compile(r"SUMMARY OF[^\n]*?\.{2,}\s*(?P<hhmm>\d{3,4})\s+UTC\b", re.I)
OFFSETS = {"UTC": 0, "GMT": 0, "HST": -10, "HAST": -10, "AST": -4, "ADT": -3, "EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7, "PDT": -7, "PST": -8}
MONTHS = {m: n for n, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.hrefs.extend(v for k, v in attrs if k.lower() == "href" and v)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(document: str) -> str:
    if "<" not in document:
        return document
    obj = _Text()
    obj.feed(document)
    return "".join(obj.parts)


def _clock(hhmm: str, ampm: str | None) -> tuple[int, int]:
    minutes = int(hhmm[-2:])
    hour = int(hhmm[:-2])
    if minutes > 59 or hour > (12 if ampm else 23) or hour == 0 and ampm:
        raise ValueError(f"Invalid NHC clock time: {hhmm} {ampm}")
    if ampm:
        hour = hour % 12 + (12 if ampm.upper() == "PM" else 0)
    return hour, minutes


def archive_directory(storm_id: str) -> str:
    if not STORM_ID.fullmatch(storm_id):
        raise ValueError("Storm ID must resemble AL062026 or EP152026")
    storm_id = storm_id.lower()
    return f"https://{HOST}/archive/{storm_id[-4:]}/{storm_id[:4]}/"


def product_urls(storm_id: str, index_html: str, limit: int = 250) -> list[str]:
    """Extract only matching storm's official public-advisory pages.

    Do not use directory modification timestamps as a proxy for actual
    publication times: archives are copied/updated after initial issuance.
    """
    base = archive_directory(storm_id)
    obj = _Links()
    obj.feed(index_html)
    urls = set()
    for href in obj.hrefs:
        url = urljoin(base, href)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != HOST or parsed.query or parsed.fragment:
            continue
        if not url.startswith(base):
            continue
        match = PRODUCT.fullmatch(parsed.path.rsplit("/", 1)[-1])
        if match and match.group("storm").upper() == storm_id.upper():
            urls.add(url)
    if len(urls) > limit:
        raise ValueError(f"Too many product files ({len(urls)}); increase --limit explicitly")
    return sorted(urls)


def parse_product(url: str, source: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != HOST:
        raise ValueError("NOAA product URL must use the approved HTTPS NOAA domain")
    match = PRODUCT.fullmatch(parsed.path.rsplit("/", 1)[-1])
    if not match:
        raise ValueError("Not a NOAA public advisory product file")
    storm_id = match.group("storm").upper()
    if not parsed.path.startswith(f"/archive/{storm_id[-4:]}/{storm_id[:4].lower()}/"):
        raise ValueError("Storm and NOAA product directory do not agree")
    text = _plain(source)
    # Storm ID and advisory number must be explicit in the product body.
    if not re.search(r"\b" + storm_id + r"\b", text, re.I):
        raise ValueError("Product body storm ID does not match filename")
    num = re.search(r"(?:INTERMEDIATE\s+)?ADVISORY\s+NUMBER[ \t]+(\d+)[ \t]*([A-Z])?", text, re.I)
    if not num or int(num.group(1)) != int(match.group("no")):
        raise ValueError("Advisory number absent or inconsistent")
    suffix = (match.group("suffix") or "").lstrip("_").upper()
    if (num.group(2) or "").upper() != suffix:
        raise ValueError("Intermediate advisory suffix differs from filename")
    dated = DATE.search(text)
    header = HEADER.search(text)
    if not dated or not header:
        raise ValueError("Could not independently parse NHC product timestamp")
    zone = header.group("tz").upper()
    hour, minute = _clock(header.group("clock"), header.group("ampm"))
    local_time = datetime(int(dated.group("year")), MONTHS[dated.group("month").upper()], int(dated.group("day")), hour, minute, tzinfo=timezone(timedelta(hours=OFFSETS[zone])))
    issued = local_time.astimezone(timezone.utc)
    # Extra independent UTC summary check, including cases crossing a date.
    utc_summary = SUMMARY_UTC.search(text)
    if utc_summary:
        sum_hour, sum_minute = _clock(utc_summary.group("hhmm"), None)
        if (issued.hour, issued.minute) != (sum_hour, sum_minute):
            raise ValueError("UTC summary contradicts local advisory issuance header")
    return {
        "storm_id": storm_id,
        "issued_at": iso(issued),
        "source_ref": url,
        "product_id": f"{int(match.group('no'))}{suffix}",
        "product_kind": "intermediate" if suffix else "regular",
        "time_basis": "nominal_issuance_utc_not_first_available",
    }


def manifest_from_documents(documents: list[tuple[str, str]], start: str, until: str) -> dict:
    lo, hi = parse_time(start), parse_time(until)
    if lo >= hi:
        raise ValueError("start must be before until")
    rows = {}
    for url, contents in documents:
        row = parse_product(url, contents)
        at = parse_time(row["issued_at"])
        if not lo <= at < hi:
            continue
        key = (row["storm_id"], row["issued_at"])
        if key in rows and rows[key]["source_ref"] != row["source_ref"]:
            raise ValueError(f"Multiple public products for same storm/time: {key}")
        rows[key] = row
    return {
        "schema_version": 1,
        "scope_start": iso(lo),
        "scope_until": iso(hi),
        "source_description": "NOAA archived NHC/CPHC public advisory products, individually parsed",
        "source_assurance": "source_documents_parsed_not_external_availability_audit",
        "catalog_completeness": "not_established",
        "expected_advisories": [dict(storm_id=r["storm_id"], issued_at=r["issued_at"], source_ref=r["source_ref"], product_id=r["product_id"], product_kind=r["product_kind"], required_stages=["raw_tracks"]) for r in sorted(rows.values(), key=lambda v: (v["issued_at"], v["storm_id"]))],
    }


def fetch_text(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != HOST or not parsed.path.startswith("/archive/"):
        raise ValueError("NOAA-only archive fetch")
    req = Request(url, headers={"User-Agent": "OpenSourceNHCCompletenessStudy/0.1 (+github.com/OCHA-DAP/ds-storms-pipeline)"})
    with urlopen(req, timeout=12) as response:
        if response.headers.get_content_type() not in {"text/html", "text/plain"}:
            raise ValueError("Unexpected NOAA response content type")
        data = response.read(500_001)
        if len(data) > 500_000:
            raise ValueError("NOAA response exceeded safe size")
    return data.decode("utf-8", errors="replace")


def fetch_noaa_manifest(storm_ids: list[str], start: str, until: str, limit: int = 250) -> dict:
    documents = []
    for storm_id in storm_ids:
        base = archive_directory(storm_id)
        urls = product_urls(storm_id, fetch_text(base), limit=limit)
        for url in urls:
            # NO fabrication or extrapolation from advisory numbering.
            documents.append((url, fetch_text(url)))
    return manifest_from_documents(documents, start, until)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--storm", action="append", required=True, help="ATCF ID; repeat")
    p.add_argument("--start", required=True, help="ISO-8601 UTC window start")
    p.add_argument("--until", required=True, help="ISO-8601 UTC exclusive end")
    p.add_argument("--output", required=True)
    p.add_argument("--fetch", action="store_true", help="Explicitly enable NOAA network retrieval")
    p.add_argument("--html-dir", type=Path, help="Parse previously saved official NOAA .shtml product pages offline")
    args = p.parse_args(argv)
    if args.fetch == (args.html_dir is not None):
        p.error("Choose exactly one of --fetch or --html-dir")
    if args.fetch:
        result = fetch_noaa_manifest(args.storm, args.start, args.until)
    else:
        if not args.html_dir.is_dir():
            p.error("--html-dir must be an existing directory")
        # Only accepted official product filenames enter the parser, and each
        # is validated against the reconstructed canonical NOAA URL.
        documents = []
        allowed = {s.upper() for s in args.storm}
        for path in sorted(args.html_dir.glob("*.shtml")):
            m = PRODUCT.fullmatch(path.name)
            if m and m.group("storm").upper() in allowed:
                base = archive_directory(m.group("storm"))
                documents.append((base + path.name, path.read_text(encoding="utf-8")))
        if not documents:
            p.error("No matching NOAA public product .shtml files found")
        result = manifest_from_documents(documents, args.start, args.until)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(result['expected_advisories'])} NOAA products; completeness not established")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
