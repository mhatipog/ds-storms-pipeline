# Methodology: NOAA CurrentStorms Historical Archive Retrieval and Advisory Visibility Reconstruction

## 1. Environment & Research Branch Setup

- **Repository**: `https://github.com/mhatipog/ds-storms-pipeline`
- **Starting Branch**: `origin/research/noaa-oct1-real-index-evidence` (commit `7fcf76b`)
- **Working Research Branch**: `research/noaa-oct1-laptop-evidence`
- **Execution Host**: Windows 11 Laptop, Python 3.11.15
- **Virtual Environment**: Isolated virtual environment (`.venv`) with minimal dependencies (`pytest`, `sqlalchemy`).
- **Cross-Platform Adaptations**:
  - Disabled Git line-ending conversion (`core.autocrlf false`) to ensure raw SHA-256 byte integrity against checked-in synthetic test scenarios.
  - Adapted `tests/test_snapshot_timeline.py` to handle Windows unprivileged environments gracefully where `os.symlink` requires elevated privileges (`SeCreateSymbolicLinkPrivilege`).
  - Implemented and verified a narrowly scoped safe NOAA host redirect allowlist (`{"www.nhc.noaa.gov", "prod-east-nhc.woc.noaa.gov"}`) in `storm_audit/archive_harvester.py` with accompanying regression tests in `tests/test_archive_harvester.py`.

---

## 2. Authentic NOAA Network Diagnostics & Data Retrieval

### 2.1 Connection & DNS Diagnostics
Previous retrieval attempts from restricted cloud/VPN environments (e.g., ChatGPT execution sandbox) reported DNS failures and HTTP 403 Forbidden responses. Direct diagnostics from this host confirmed clean network access to both official NOAA endpoints:
- **Primary Endpoint**: `https://www.nhc.noaa.gov/archive/activeJson/2026/`
  - DNS Resolution: Resolves to AWS CloudFront edge IP addresses (`18.164.52.8`, `18.164.52.23`, `18.164.52.48`, `18.164.52.81`).
  - HTTP Status: `200 OK`
  - Server: `Apache/2.4.37 (Red Hat Enterprise Linux)` via CloudFront
  - TLS Validation: Fully intact; strict standard certificate validation maintained.
- **Alternative Endpoint**: `https://prod-east-nhc.woc.noaa.gov/archive/activeJson/2026/`
  - DNS Resolution: Resolves directly to NOAA WOC infrastructure (`137.75.116.84`, `137.75.116.101`).
  - HTTP Status: `200 OK`
  - Server: `Apache/2.4.37 (Red Hat Enterprise Linux)`

### 2.2 Directory Index Preservation & Link Extraction
The complete 2026 directory listing HTML was retrieved and saved to `noaa-archive/index-2026.html` (722,764 bytes).
- Parsing was conducted using `storm_audit.snapshot_timeline.noaa_directory_urls`, which parses HTML `<a>` tags and extracts complete `href` target attributes (`CurrentStorms_2026-10-01-*.json`), rejecting truncated display labels.
- Exactly **39 unique archived snapshots** were identified for UTC day **2026-10-01**.

### 2.3 Automated Harvest Execution
The harvest was executed via `storm_audit.archive_harvester`:
```bash
python -m storm_audit.archive_harvester --day 2026-10-01 --fetch --max-files 160 --out-dir ./noaa-archive
```
- **Rate Limiting**: Enforced a minimum 1.0-second delay between consecutive HTTP requests.
- **Payload Constraints**: Enforced a 2,000,000-byte maximum file size limit (largest downloaded snapshot was 14,165 bytes).
- **Integrity Verification**: Calculated and recorded the cryptographic SHA-256 digest of each downloaded file immediately upon reception.
- **Output Audit Log**: Generated `retrieval-log.json` recording source URL, SHA-256 digest, byte count, and retrieval timestamp for all 39 files.

---

## 3. Snapshot Parsing & Timeline Reconstruction

Each downloaded snapshot was parsed using `storm_audit.snapshot_timeline.parse_current_storms` against the documented NOAA CurrentStorms schema:
1. Validated root structure and `activeStorms` array.
2. Verified presence and metadata of Tropical Storm Nolo (`EP152026`).
3. Extracted canonical public advisory numbers (`advNum`), nominal issuance timestamps (`issuance`), and product file generation timestamps (`fileUpdateTime`).
4. Reconciled extracted advisories against the control manifest of all eight public advisories published for Nolo on 2026-10-01 UTC (`examples/noaa_nolo_2026-10-01_public_day.json`).

---

## 4. Epistemological Framework & Temporal Boundaries

A rigorous scientific distinction is preserved across all timestamps and conclusions:
1. **Retrieval Timestamp (`retrieved_at`)**: `2026-10-16T07:51:33Z` to `07:52:26Z`. Measures when this machine retrieved the file. It provides zero evidence of historical timing.
2. **Archive Filename Timestamp**: E.g., `CurrentStorms_2026-10-01-0232.json` corresponds nominally to `2026-10-01 02:32 UTC`. This indicates when the NOAA Apache archive server saved the snapshot.
3. **Product `fileUpdateTime`**: Internal NOAA timestamp embedded in the JSON payload (e.g., `2026-10-01T02:44:35.282Z`). Reflects when the upstream NOAA product generation software rendered that advisory block.
4. **Nominal Issuance Timestamp (`issued_at`)**: Official meteorological advisory cycle time (e.g., `2026-10-01T03:00:00Z`).
5. **Historical First-Availability / Network Arrival Time**: **UNKNOWN / UNATTESTED**. Without contemporaneous packet captures or third-party real-time polling logs from 1 October 2026, original publication latency cannot be proven unconditionally.
6. **Verdict Nature**: All timeline reconstructions and OCHA visibility determinations are explicitly designated as **CONDITIONAL RECONSTRUCTIONS** based on the NOAA historical archive, not verified real-time network logs.

---

## 5. Operational Evidence Join & Maintainer Request Protocol

Evaluation of actual OCHA ingestion was executed via `storm_audit.operational_evidence`:
```bash
python -m storm_audit.operational_evidence \
  --manifest examples/noaa_nolo_2026-10-01_public_day.json \
  --reviewed-index examples/noaa_nolo_2026-10-01_index_control.json \
  --output operational-evidence-report.json
```
- In the absence of production credentials or an authorized read-only database export, the audit strictly reports `operational_evidence_unavailable` for all 8 advisories.
- A formal specification for the minimal required maintainer export is documented in Section 6 of `results.md`.
