"""Optional PostgreSQL snapshot collector. Every SQL statement is read-only.

Requires sqlalchemy + a PostgreSQL read-only credential supplied via environment
variable. Designed for manual dev validation; no production access is needed
for the scenario replay.
"""
from __future__ import annotations

from datetime import timedelta, timezone, datetime
from typing import Any

from .core import STAGES, iso, validate_manifest

# Table and time column are strictly allow-listed identifiers; all data
# values are bound as SQL parameters. These schemas were inspected upstream.
TABLES = {
    "raw_tracks": ("storms.nhc_tracks_geo", "issued_time"),
    "forecast_buffers": ("storms.nhc_tracks_fcast_buffers", "issued_time"),
    "observed_buffers": ("storms.nhc_tracks_obsv_buffers", "valid_time"),
    "forecast_only_buffers": ("storms.nhc_tracks_fcastonly_buffers", "issued_time"),
    "forecast_exposure": ("storms.nhc_tracks_fcast_exposure", "issued_time"),
    "observed_exposure": ("storms.nhc_tracks_obsv_exposure", "valid_time"),
    "forecast_only_exposure": ("storms.nhc_tracks_fcastonly_exposure", "issued_time"),
}
assert set(TABLES) == set(STAGES)


def collect_postgres(manifest: dict[str, Any], dsn: str, lookahead_hours: int = 48) -> dict[str, Any]:
    if not dsn.startswith(("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://")):
        raise ValueError("Only PostgreSQL connections are supported")
    if not isinstance(lookahead_hours, int) or not 0 <= lookahead_hours <= 720:
        raise ValueError("lookahead_hours must be between 0 and 720")
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError("Install sqlalchemy and a PostgreSQL driver for --dsn-env mode") from exc
    expected, storms = validate_manifest(manifest)
    if not expected:
        raise ValueError("Cannot query a database without explicit expected advisories")
    start = min(k.issued_at for k in expected)
    end = max(k.issued_at for k in expected) + timedelta(hours=lookahead_hours, seconds=1)
    # Bind all storm identifiers as parameters, never interpolate input data.
    ids = sorted(storms)
    params = {"start": start, "end": end}
    binds = []
    for idx, storm in enumerate(ids):
        params[f"storm_{idx}"] = storm
        binds.append(f":storm_{idx}")
    in_sql = ", ".join(binds)
    observations = []
    scanned = []
    errors = []
    completion_markers = []
    completion_scanned = False
    engine = create_engine(dsn, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            with conn.begin():
                # PostgreSQL refuses INSERT/UPDATE/DELETE within this transaction.
                # All tables must be observed from the SAME PostgreSQL snapshot.
                # READ COMMITTED (the default) would allow concurrent
                # ingestion between SELECTs to create spurious gaps.
                conn.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                for stage, (table, time_col) in TABLES.items():
                    exists = conn.execute(text("SELECT to_regclass(:name)"), {"name": table}).scalar()
                    if exists is None:
                        errors.append(f"{stage}: table {table} does not exist or is not visible")
                        continue
                    sql = text(
                        f"SELECT atcf_id, {time_col} AS issued_at, COUNT(*) AS row_count "
                        f"FROM {table} "
                        f"WHERE atcf_id IN ({in_sql}) "
                        f"AND {time_col} >= :start AND {time_col} < :end "
                        f"GROUP BY atcf_id, {time_col} "
                        f"ORDER BY atcf_id, {time_col}"
                    )
                    # Permission/schema failures should fail closed. Do not
                    # misreport absent outputs if they could not be inspected.
                    try:
                        rows = conn.execute(sql, params).mappings().all()
                    except Exception as exc:
                        # On Postgres a statement error aborts the transaction;
                        # do not attempt further reads in a broken transaction.
                        raise RuntimeError(
                            f"Could not query {stage} ({table}). No audit conclusions should be drawn."
                        ) from exc
                    scanned.append(stage)
                    for row in rows:
                        t = row["issued_at"]
                        if t.tzinfo is None:
                            # These NHC database columns are UTC without tz.
                            t = t.replace(tzinfo=timezone.utc)
                        observations.append({
                            "storm_id": str(row["atcf_id"]).upper(),
                            "issued_at": iso(t),
                            "stage": stage,
                            "row_count": int(row["row_count"]),
                            "observed_source": f"read-only SELECT from {table}",
                        })

                # OCHA's exposure_completion table records a single timestamp
                # for all storms at that issuance. Never attribute a marker
                # to an individual storm ID.
                if conn.execute(text("SELECT to_regclass(:name)"), {
                    "name": "storms.exposure_completion"
                }).scalar() is not None:
                    table_to_stage = {
                        "nhc_tracks_fcast_exposure": "forecast_exposure",
                        "nhc_tracks_obsv_exposure": "observed_exposure",
                        "nhc_tracks_fcastonly_exposure": "forecast_only_exposure",
                    }
                    markers = conn.execute(text(
                        "SELECT out_table, key_val, admin_level "
                        "FROM storms.exposure_completion "
                        "WHERE key_val >= :start AND key_val < :end "
                        "AND out_table IN (:fcast, :obsv, :fonly)"
                    ), {"start": start, "end": end,
                        "fcast": "nhc_tracks_fcast_exposure",
                        "obsv": "nhc_tracks_obsv_exposure",
                        "fonly": "nhc_tracks_fcastonly_exposure"}).mappings().all()
                    completion_scanned = True
                    for row in markers:
                        t = row["key_val"]
                        if t.tzinfo is None:
                            t = t.replace(tzinfo=timezone.utc)
                        completion_markers.append({
                            "stage": table_to_stage[row["out_table"]],
                            "issued_at": iso(t),
                            "admin_level": int(row["admin_level"]),
                        })
                else:
                    errors.append("exposure_completion: table missing or inaccessible")
    finally:
        engine.dispose()
    return {
        "schema_version": 1,
        "as_of": iso(datetime.now(timezone.utc)),
        "snapshot_assurance": "database_read_only",
        "snapshot_description": (
            "PostgreSQL read-only table presence snapshot; no claims of computation completion"
        ),
        "scanned_stages": scanned,
        "scan_warnings": errors,
        "completion_scanned": completion_scanned,
        "completion_markers": completion_markers,
        "window": {"start_inclusive": iso(start), "end_exclusive": iso(end)},
        "observations": observations,
    }
