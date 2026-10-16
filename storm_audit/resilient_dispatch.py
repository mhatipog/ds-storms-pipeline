"""Offline reference design: durable, reconciling NHC advisory work queue.

NO Databricks, NOAA network, or production database integration. Merely
persisting a feed signal is not proof of full source coverage; archive
reconciliation is an independent required safety loop. Work receipts are not
verified processing outcomes until confirmed independently.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
import json
import re
from pathlib import Path
import sqlite3
import uuid
from urllib.parse import urlsplit

from .core import iso, parse_time

STREAMS = frozenset(("track", "wsp"))
SOURCES = frozenset(("feed", "archive"))
STATUSES = frozenset(("queued", "leased", "verification_required", "acknowledged", "verified", "quarantined"))


def _now(value: str) -> str:
    return iso(parse_time(value))


def _rows(records, stream):
    """Validate the whole batch BEFORE opening a write transaction."""
    if stream not in STREAMS:
        raise ValueError("Unknown source stream")
    result = []
    for row in records:
        storm = row.get("storm_id")
        product_id = row.get("product_id")
        if not isinstance(storm, str) or not storm.strip() or not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("Every product requires a storm_id and product_id")
        issued = _now(row["issued_at"])
        ref = row.get("source_ref")
        if not isinstance(ref, str) or not ref.startswith("https://www.nhc.noaa.gov/archive/"):
            raise ValueError("Require independently identifiable official NOAA archive reference")
        uri = urlsplit(ref)
        if uri.hostname != "www.nhc.noaa.gov" or uri.username or uri.password or uri.query or uri.fragment:
            raise ValueError("Unexpected NOAA reference form")
        storm = storm.strip().upper()
        product_id = product_id.strip().upper()
        key = f"{storm}|{issued}|{product_id}"
        # Fingerprint preserves origin/version conflict visibility; not a
        # cryptographic attestation that a published product was fetched.
        content_sha256 = row.get("content_sha256")
        if content_sha256 is not None:
            if not isinstance(content_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", content_sha256):
                raise ValueError("content_sha256 must be a 64-digit hexadecimal digest")
            content_sha256 = content_sha256.lower()
        # Products can be silently revised at the SAME URL. Include the
        # body hash when independently fetched; missing body hashes mean
        # revisions at unchanged URLs are NOT detectable in this prototype.
        canonical = json.dumps([stream, storm, issued, product_id, ref, content_sha256], separators=(",", ":"))
        digest = sha256(canonical.encode()).hexdigest()
        result.append((stream, key, storm, issued, product_id, ref, digest))
    # Fail closed if a single scan contains contradictory claims.
    seen = {}
    for row in result:
        key = row[:2]
        if key in seen and seen[key] != row:
            raise ValueError("Conflicting products with same identity in one batch")
        seen[key] = row
    return list(seen.values())


class AdvisoryQueue:
    """SQLite WAL queue, suited to a *single host* research prototype.

    The schema and lease token support multiple local workers, but an external
    durable store and provider-specific exactly-once effects are needed for
    a real multi-host Databricks integration.
    """

    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    stream TEXT NOT NULL, product_key TEXT NOT NULL,
                    storm_id TEXT NOT NULL, issued_at TEXT NOT NULL,
                    product_id TEXT NOT NULL, source_ref TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    seen_feed INTEGER NOT NULL DEFAULT 0,
                    seen_archive INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    lease_token TEXT, lease_until TEXT,
                    receipt TEXT, verification_ref TEXT, last_error TEXT,
                    PRIMARY KEY(stream, product_key)
                );
                CREATE INDEX IF NOT EXISTS idx_queue_claim
                ON products(stream, status, next_attempt_at, issued_at);
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    stream TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, state TEXT NOT NULL,
                    assurance TEXT NOT NULL, count INTEGER NOT NULL,
                    diagnostic TEXT
                );
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
        finally:
            conn.close()

    def ingest(self, records: list[dict], *, stream="track", source="feed", now: str,
               scan_complete: bool = False, assurance: str = "not_established") -> dict:
        """Durably record every seen product. A scan isn't a full archive
        merely because the HTTP request returned 200; upstream must prove it.
        """
        if source not in SOURCES:
            raise ValueError("Unknown source")
        if scan_complete and (source != "archive" or assurance != "externally_verified_complete"):
            raise ValueError("Complete coverage requires verified independent archive evidence")
        when = _now(now)
        parsed = _rows(records, stream)
        if any(parse_time(row[3]) > parse_time(when) for row in parsed):
            raise ValueError("Future issuance cannot be ingested before its nominal issuance time")
        run_id = str(uuid.uuid4())
        added = duplicates = conflicts = 0
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for s, key, storm, issued, pid, ref, digest in parsed:
                    cur = conn.execute("SELECT fingerprint, status FROM products WHERE stream=? AND product_key=?", (s, key)).fetchone()
                    if cur is None:
                        conn.execute("""INSERT INTO products
                            (stream,product_key,storm_id,issued_at,product_id,source_ref,
                             fingerprint,status,first_seen_at,last_seen_at,
                             seen_feed,seen_archive,next_attempt_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (s,key,storm,issued,pid,ref,digest,"queued",when,when,
                             int(source=="feed"),int(source=="archive"),when))
                        added += 1
                    elif cur["fingerprint"] != digest:
                        # Do not overwrite a previously accepted product,
                        # or automatically process an unexpected revision.
                        conn.execute("""UPDATE products SET status='quarantined',
                             last_error='Conflicting product identity: manual source review required',
                             lease_token=NULL, lease_until=NULL, last_seen_at=?
                             WHERE stream=? AND product_key=?""", (when,s,key))
                        conflicts += 1
                    else:
                        conn.execute(f"""UPDATE products SET last_seen_at=?, seen_{source}=1
                            WHERE stream=? AND product_key=?""", (when,s,key))
                        duplicates += 1
                conn.execute("""INSERT INTO scan_runs
                    (id,source,stream,started_at,finished_at,state,assurance,count)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (run_id,source,stream,when,when,
                     "complete_catalog" if scan_complete else "partial_observation",assurance,len(parsed)))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"run_id":run_id,"added":added,"duplicates":duplicates,
                "conflicts":conflicts,"scanned":len(parsed),"catalog_certified":scan_complete}

    def scan_failed(self, *, stream: str, source: str, now: str, diagnostic: str) -> None:
        """A failed scan must never erase evidence or advance coverage."""
        if stream not in STREAMS or source not in SOURCES:
            raise ValueError("Invalid scan")
        with self._conn() as conn:
            conn.execute("""INSERT INTO scan_runs
                (id,source,stream,started_at,state,assurance,count,diagnostic)
                VALUES (?,?,?,?,'failed','none',0,?)""",
                (str(uuid.uuid4()),source,stream,_now(now),str(diagnostic)[:500]))

    def _expire(self, conn, now):
        # Never replay an expensive job based only on its lease timeout.
        # The previous worker may have succeeded before losing its receipt.
        conn.execute("""UPDATE products SET status='verification_required',
            last_error='Lease expired: downstream completion must be checked',
            lease_token=NULL, lease_until=NULL
            WHERE status='leased' AND lease_until<=?""", (now,))

    def claim(self, *, now: str, stream="track", batch_size=20, lease_seconds=1800) -> list[dict]:
        if stream not in STREAMS or type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("Invalid stream or batch size")
        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 86400:
            raise ValueError("Invalid lease duration")
        when = _now(now)
        until = iso(parse_time(when)+timedelta(seconds=lease_seconds))
        claims=[]
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._expire(conn, when)
                rows = conn.execute("""SELECT stream, product_key, storm_id,issued_at,product_id,source_ref
                    FROM products WHERE stream=? AND status='queued' AND next_attempt_at<=?
                    ORDER BY issued_at, storm_id, product_id LIMIT ?""", (stream, when, batch_size)).fetchall()
                for r in rows:
                    token = str(uuid.uuid4())
                    conn.execute("""UPDATE products SET status='leased',lease_token=?,lease_until=?,attempts=attempts+1
                        WHERE stream=? AND product_key=? AND status='queued'""", (token,until,stream,r["product_key"]))
                    claims.append({**dict(r),"lease_token":token,"lease_until":until})
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return claims

    def report_outcome(self, *, stream: str, product_key: str, lease_token: str,
                       outcome: str, now: str, evidence: str = "") -> None:
        """outcome=acknowledged, definitely_not_started, or uncertain.

        A receipt is only a worker claim; not proof of completed data tables.
        """
        if outcome not in {"acknowledged","definitely_not_started","uncertain"}:
            raise ValueError("Invalid outcome")
        when=_now(now)
        if outcome=="acknowledged" and not evidence.strip():
            raise ValueError("Worker acknowledgement requires a nonempty receipt")
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row=conn.execute("SELECT status,lease_token,lease_until,attempts FROM products WHERE stream=? AND product_key=?",
                                 (stream,product_key)).fetchone()
                if row is None or row["status"]!="leased" or row["lease_token"]!=lease_token or row["lease_until"]<=when:
                    raise ValueError("Stale/expired lease token; result requires independent verification")
                if outcome=="definitely_not_started":
                    # Exponential, bounded delay; no spin on a down service.
                    seconds=min(3600, 30*(2**min(row["attempts"]-1,7)))
                    next_at=iso(parse_time(when)+timedelta(seconds=seconds))
                    conn.execute("""UPDATE products SET status='queued',lease_token=NULL,lease_until=NULL,
                        next_attempt_at=?,last_error='Confirmed dispatch failure before job started'
                        WHERE stream=? AND product_key=?""",(next_at,stream,product_key))
                else:
                    new_status="acknowledged" if outcome=="acknowledged" else "verification_required"
                    conn.execute("""UPDATE products SET status=?,lease_token=NULL,lease_until=NULL,
                        receipt=?,last_error=? WHERE stream=? AND product_key=?""",
                        (new_status,evidence or None,
                         None if outcome=="acknowledged" else "Outcome unknown: verify downstream before retry",
                         stream,product_key))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def verify(self, *, stream: str, product_key: str, outcome: str, now: str,
               independent_evidence: str = "") -> None:
        """Explicit reconciliation with downstream per-product evidence.

        Only 'verified_complete' or 'verified_not_started' may change state.
        An unknown result stays blocked for review; never auto-retry.
        """
        if outcome not in {"verified_complete", "verified_not_started", "unknown"}:
            raise ValueError("Invalid verification outcome")
        when = _now(now)
        if outcome != "unknown" and not independent_evidence.strip():
            raise ValueError("Independent verification reference required")
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row=conn.execute("SELECT status,attempts FROM products WHERE stream=? AND product_key=?",(stream,product_key)).fetchone()
                if row is None or row["status"] not in {"verification_required", "acknowledged"}:
                    raise ValueError("Product not awaiting verification")
                if outcome=="verified_complete":
                    conn.execute("""UPDATE products SET status='verified', verification_ref=?,last_error=NULL
                        WHERE stream=? AND product_key=?""", (independent_evidence,stream,product_key))
                elif outcome=="verified_not_started":
                    delay=min(3600,30*(2**min(row["attempts"]-1,7)))
                    conn.execute("""UPDATE products SET status='queued',next_attempt_at=?,
                        verification_ref=?,last_error='Confirmed no downstream work: retry permitted'
                        WHERE stream=? AND product_key=?""",(iso(parse_time(when)+timedelta(seconds=delay)),independent_evidence,stream,product_key))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def get(self, stream: str, product_key: str) -> dict | None:
        with self._conn() as conn:
            row=conn.execute("SELECT * FROM products WHERE stream=? AND product_key=?",(stream,product_key)).fetchone()
            return dict(row) if row else None

    def report(self, *, now: str, stream="track", max_verified_scan_age_hours=24) -> dict:
        if stream not in STREAMS:
            raise ValueError("Unknown stream")
        when=_now(now)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._expire(conn,when)
                counts={r["status"]:r["n"] for r in conn.execute(
                    "SELECT status,COUNT(*) n FROM products WHERE stream=? GROUP BY status",(stream,))}
                scan=conn.execute("""SELECT finished_at FROM scan_runs
                    WHERE source='archive' AND stream=? AND state='complete_catalog'
                    ORDER BY finished_at DESC LIMIT 1""",(stream,)).fetchone()
                last_scan=conn.execute("""SELECT state,finished_at,diagnostic FROM scan_runs
                    WHERE source='archive' AND stream=? ORDER BY started_at DESC,id DESC LIMIT 1""",(stream,)).fetchone()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        age=(parse_time(when)-parse_time(scan["finished_at"])).total_seconds()/3600 if scan else None
        healthy=(age is not None and 0<=age<=max_verified_scan_age_hours and last_scan["state"]=="complete_catalog")
        if counts.get("quarantined") or counts.get("verification_required"):
            state="needs_review"
        elif not healthy:
            state="coverage_unestablished"
        elif any(counts.get(x) for x in ("queued","leased","acknowledged")):
            state="backlog_or_unverified"
        else:
            state="no_known_backlog_within_certified_scope"
        return {"state":state,"stream":stream,"counts":dict(sorted(counts.items())),
                "verified_catalog_scan_at":scan["finished_at"] if scan else None,
                "verified_catalog_scan_age_hours":age,
                "latest_archive_scan_state":last_scan["state"] if last_scan else "never",
                "limitations":[
                    "No independent source catalog: an empty queue is not evidence of complete NOAA coverage.",
                    "URL-only records cannot reveal body revisions at unchanged NOAA URLs without an independently fetched content_sha256.",
                    "Complete archive flag requires external provenance review; API caller attestation is not independently checked here.",
                    "Worker acknowledgement is not proof of downstream per-product completion.",
                    "Existing OCHA completion markers are issuance-wide, not per-storm per-product verification.",
                    "No Databricks/NOAA/production execution; not an operational health status.",
                ]}


def main(argv=None) -> int:
    """Safe local CLI: ingestion and status only; NO production dispatch."""
    import argparse
    p=argparse.ArgumentParser(description="Offline advisory queue; no external jobs launched")
    p.add_argument("--db",required=True,help="Local SQLite state path")
    commands=p.add_subparsers(dest="command",required=True)
    add=commands.add_parser("ingest",help="Record source-listed advisories; never dispatch")
    add.add_argument("--manifest",required=True)
    add.add_argument("--source",choices=sorted(SOURCES),required=True)
    add.add_argument("--stream",choices=sorted(STREAMS),default="track")
    add.add_argument("--now",required=True,help="ISO-8601 current time")
    status=commands.add_parser("status",help="Inspect durable queue status")
    status.add_argument("--stream",choices=sorted(STREAMS),default="track")
    status.add_argument("--now",required=True)
    args=p.parse_args(argv)
    queue=AdvisoryQueue(args.db)
    if args.command=="ingest":
        manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        result=queue.ingest(manifest["expected_advisories"],source=args.source,
                 stream=args.stream,now=args.now,scan_complete=False,
                 assurance=manifest.get("catalog_completeness","not_established"))
    else:
        result=queue.report(now=args.now,stream=args.stream)
    print(json.dumps(result,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
