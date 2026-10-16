"""Explicitly opt-in NOAA CurrentStorms archive collector.

The harvest log records when archival files were *retrieved now*, never when
those files were originally published. Requires an accessible NOAA connection.
Catalog-only mode is offline and safe to run with a saved directory index.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .core import iso
from .snapshot_timeline import MAX_BYTES, noaa_directory_urls, parse_current_storms, SourceIntegrityError

ARCHIVE_BASE = "https://www.nhc.noaa.gov/archive/activeJson/"
ALLOWED_NOAA_HOSTS = frozenset({"www.nhc.noaa.gov", "prod-east-nhc.woc.noaa.gov"})


class _NOAARedirectsOnly(HTTPRedirectHandler):
    """Reject cross-host redirects before following them, allowing only official NOAA hosts."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        if p.scheme != "https" or p.netloc not in ALLOWED_NOAA_HOSTS or not p.path.startswith("/archive/activeJson/"):
            raise SourceIntegrityError("NOAA archive download redirected outside allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_noaa(url: str) -> bytes:
    p = urlsplit(url)
    if (p.scheme != "https" or p.netloc not in ALLOWED_NOAA_HOSTS or
        not p.path.startswith("/archive/activeJson/") or p.query or p.fragment):
        raise SourceIntegrityError("Download requires official NOAA archive HTTPS URL")
    opener = build_opener(_NOAARedirectsOnly())
    request = Request(url, headers={"User-Agent":"OCHA-Research-Archive-Audit/0.1 (read-only; manual)"})
    with opener.open(request, timeout=15) as response:
        payload = response.read(MAX_BYTES+1)
    if len(payload)>MAX_BYTES:
        raise SourceIntegrityError("NOAA response exceeded size limit")
    return payload


def harvest(index_html: str, day: str, out_dir: Path, *, fetch: bool = False,
            max_files: int = 160, min_interval_seconds: float = 1.0,
            downloader=None, clock=None, sleeper=None) -> dict:
    """List/download one UTC day; source capture time remains UNKNOWN.

    Pass injected downloader/clock/sleeper to test deterministically. If a
    collection fails mid-way, incomplete files are never declared complete.
    """
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", day):
        raise ValueError("Day must be YYYY-MM-DD")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("Invalid calendar date") from e
    if type(max_files) is not int or not 1 <= max_files <= 1000:
        raise ValueError("max_files must be 1..1000")
    if not isinstance(min_interval_seconds,(int,float)) or not 0 <= min_interval_seconds <= 60:
        raise ValueError("Invalid request interval")
    url_prefix = f"CurrentStorms_{day}"
    urls = [u for u in noaa_directory_urls(index_html, int(day[:4]))
            if urlsplit(u).path.rsplit("/",1)[-1].startswith(url_prefix)]
    if len(urls)>max_files:
        raise SourceIntegrityError("Day exceeds max_files: fail closed rather than silently sample")
    if not urls:
        raise SourceIntegrityError("Zero matching archive hrefs: no coverage claim")
    out_dir=Path(out_dir)
    downloader=downloader or _download_noaa
    clock=clock or (lambda: datetime.now(timezone.utc))
    sleeper=sleeper or time.sleep
    rows=[]
    for index,url in enumerate(urls):
        basename = urlsplit(url).path.rsplit("/", 1)[-1]
        if fetch:
            if index:
                sleeper(min_interval_seconds)
            data=downloader(url)
            if not isinstance(data,bytes) or len(data)>MAX_BYTES:
                raise SourceIntegrityError("Downloaded snapshot is not safe JSON bytes")
            # Refuse to persist a misleading manifest or unparseable snapshot.
            parsed=parse_current_storms(data)
            out_dir.mkdir(parents=True, exist_ok=True)
            target=out_dir/basename
            if target.exists() and target.read_bytes()!=data:
                raise SourceIntegrityError("Same NOAA filename has changed bytes: inspect revision")
            if not target.exists():
                target.write_bytes(data)
            retrieved_at=iso(clock())
            rows.append({"filename":basename,"source_url":url,"sha256":sha256(data).hexdigest(),
                         "bytes":len(data),"retrieved_at":retrieved_at,
                         "active_storm_count":len(parsed["active_storm_ids"])})
        else:
            rows.append({"filename":basename,"source_url":url,"downloaded":False})
    report={"schema_version":1,"kind":"retrospective_noaa_archive_retrieval_log",
            "day":day,"discovered_href_count":len(urls),"downloaded_count":len(rows) if fetch else 0,
            "complete_for_filtered_href_list":True,
            "capture_time_assurance":"historical_capture_times_not_established",
            "publication_time_assurance":"not_established",
            "independent_poll_log":False,
            "files":rows,
            "limitations":[
                "This is only a list of hrefs present in the saved directory HTML, not proof the directory inventory is exhaustive.",
                "The downloaded_at timestamp measures retrospective retrieval now; it is NOT original snapshot capture or NHC first publication time.",
                "No per-advisory historical first-availability or OCHA ingestion outcome is inferred.",
                "A separately validated historical capture-time mapping is required for snapshot_timeline.",
            ]}
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day",required=True,help="UTC day YYYY-MM-DD")
    p.add_argument("--index-html",help="Offline copy of NOAA archive directory HTML")
    p.add_argument("--fetch",action="store_true",help="Explicit opt-in to downloading selected JSON files")
    p.add_argument("--max-files",type=int,default=160)
    p.add_argument("--out-dir",required=True)
    args=p.parse_args(argv)
    day=args.day
    if args.index_html:
        html=Path(args.index_html).read_text(encoding="utf8")
    elif args.fetch:
        html=_download_noaa(f"{ARCHIVE_BASE}{day[:4]}/").decode("utf8")
    else:
        p.error("Supply --index-html for offline discovery or --fetch to explicitly use the network")
    result=harvest(html,day,Path(args.out_dir),fetch=args.fetch,max_files=args.max_files)
    target=Path(args.out_dir)/"noaa-retrieval-log.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"hrefs":result["discovered_href_count"],"files":result["downloaded_count"],
                      "historical_first_availability_established":False}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
