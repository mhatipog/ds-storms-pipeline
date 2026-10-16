# Results: NOAA CurrentStorms Historical Evidence & OCHA Advisory Visibility Analysis

## Executive Summary

| Metric | Result | Epistemological Status |
| :--- | :--- | :--- |
| **Authentic NOAA JSON Files Retrieved & Verified** | **39 files** | **Verified Fact** (Level A Success Criteria Met) |
| **Integrity & Size Checks** | **100% Passed (39/39 SHA-256 verified)** | **Verified Fact** |
| **Nolo (`EP152026`) Presence in Snapshots** | **100% (39/39 snapshots contain Nolo)** | **Verified Fact** |
| **Nolo Public Advisories Discovered in Archive** | **9 advisories (41A, 42, 42A, 43, 43A, 44, 44A, 45, 45A)** | **Verified Fact** (All 8 expected day advisories + next-cycle 45A) |
| **Advisory Visibility at 4 OCHA Scheduled Runs** | **4 Regular Advisories Active; 4 Intermediate Overwritten** | **Conditional Reconstruction** (Level B Success Criteria Met) |
| **Evidence of Actual OCHA Processing Omissions** | **0 / 8 Advisories (No production export provided)** | **Unknown Fact** (`operational_evidence_unavailable`) |
| **Advancement of Event-Driven Recovery Proposal** | **Strongly Justified Architecturally** | **Engineering Inference** |
| **Single Remaining Obstacle** | **Authorized OCHA Databricks / DB Read-Only Export** | **Actionable Gap** |

---

## 1. Retrieved NOAA Data Inventory

A total of **39 authentic NOAA CurrentStorms JSON files** for **1 October 2026 UTC** were retrieved from `https://www.nhc.noaa.gov/archive/activeJson/2026/`.
- Network Diagnostics: No DNS failures and zero HTTP 403 blocks were encountered from this host. Both `www.nhc.noaa.gov` and `prod-east-nhc.woc.noaa.gov` returned HTTP 200 with standard TLS.
- Every file was verified against size bounds (< 2 MB) and cryptographically hashed (SHA-256).
- All 39 files contain active tracking data for Tropical Storm Nolo (`EP152026`), alongside Pacific storms Hurricane Rachel (`EP182026`) and `EP192026`.

### Full 39-Snapshot Inventory & Chronology

| Snapshot Filename | Nominal Filename UTC | SHA-256 Digest (Prefix) | Active Storms | Nolo Adv | Nolo Nominal Issuance | NOAA `fileUpdateTime` |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| `CurrentStorms_2026-10-01-0232.json` | 02:32:00Z | `1795970a08db...` | EP15, EP18, EP19 | **41A** | 2026-10-01T00:00:00Z | 2026-09-30T23:32:02.763Z |
| `CurrentStorms_2026-10-01-0234.json` | 02:34:00Z | `3d981f3cb713...` | EP15, EP18, EP19 | **41A** | 2026-10-01T00:00:00Z | 2026-09-30T23:32:02.763Z |
| `CurrentStorms_2026-10-01-0236.json` | 02:36:00Z | `75be6f5643fb...` | EP15, EP18, EP19 | **41A** | 2026-10-01T00:00:00Z | 2026-09-30T23:32:02.763Z |
| `CurrentStorms_2026-10-01-0238.json` | 02:38:00Z | `c54a2d7649e2...` | EP15, EP18, EP19 | **41A** | 2026-10-01T00:00:00Z | 2026-09-30T23:32:02.763Z |
| `CurrentStorms_2026-10-01-0240.json` | 02:40:00Z | `d6c5fc435cd6...` | EP15, EP18, EP19 | **41A** | 2026-10-01T00:00:00Z | 2026-09-30T23:32:02.763Z |
| `CurrentStorms_2026-10-01-0246.json` | 02:46:00Z | `92eb6383c81a...` | EP15, EP18, EP19 | **42** | 2026-10-01T03:00:00Z | 2026-10-01T02:44:35.282Z |
| `CurrentStorms_2026-10-01-0248.json` | 02:48:00Z | `6ad36cbfb607...` | EP15, EP18, EP19 | **42** | 2026-10-01T03:00:00Z | 2026-10-01T02:44:35.282Z |
| `CurrentStorms_2026-10-01-0250.json` | 02:50:00Z | `532e3ffb617b...` | EP15, EP18, EP19 | **42** | 2026-10-01T03:00:00Z | 2026-10-01T02:44:35.282Z |
| `CurrentStorms_2026-10-01-0324.json` | 03:24:00Z | `ca589634e402...` | EP15, EP18, EP19 | **42** | 2026-10-01T03:00:00Z | 2026-10-01T02:44:35.282Z |
| `CurrentStorms_2026-10-01-0540.json` | 05:40:00Z | `59d2426df5ef...` | EP15, EP18, EP19 | **42A** | 2026-10-01T06:00:00Z | 2026-10-01T05:38:42.663Z |
| `CurrentStorms_2026-10-01-0840.json` | 08:40:00Z | `fe96c21a3a41...` | EP15, EP18, EP19 | **42A** | 2026-10-01T06:00:00Z | 2026-10-01T05:38:42.663Z |
| `CurrentStorms_2026-10-01-0842.json` | 08:42:00Z | `04d6e90d2e8d...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0844.json` | 08:44:00Z | `062d6ea53eb6...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0846.json` | 08:46:00Z | `07d00bf7cf51...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0848.json` | 08:48:00Z | `e1b7d9766b61...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0850.json` | 08:50:00Z | `6cd5e7b9a2d8...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0852.json` | 08:52:00Z | `e42c21482d1b...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0854.json` | 08:54:00Z | `fb246c562e7d...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0902.json` | 09:02:00Z | `2da9086a7357...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-0924.json` | 09:24:00Z | `cc6ac2c4260a...` | EP15, EP18, EP19 | **43** | 2026-10-01T09:00:00Z | 2026-10-01T08:41:38.587Z |
| `CurrentStorms_2026-10-01-1142.json` | 11:42:00Z | `6f070ef797be...` | EP15, EP18, EP19 | **43A** | 2026-10-01T12:00:00Z | 2026-10-01T11:40:08.223Z |
| `CurrentStorms_2026-10-01-1238.json` | 12:38:00Z | `b2b6c9e24355...` | EP15, EP18, EP19 | **43A** | 2026-10-01T12:00:00Z | 2026-10-01T11:40:08.223Z |
| `CurrentStorms_2026-10-01-1444.json` | 14:44:00Z | `b36147fb0287...` | EP15, EP18, EP19 | **43A** | 2026-10-01T12:00:00Z | 2026-10-01T11:40:08.223Z |
| `CurrentStorms_2026-10-01-1446.json` | 14:46:00Z | `fea353bd29e8...` | EP15, EP18, EP19 | **43A** | 2026-10-01T12:00:00Z | 2026-10-01T11:40:08.223Z |
| `CurrentStorms_2026-10-01-1448.json` | 14:48:00Z | `b343f76ae578...` | EP15, EP18, EP19 | **43A** | 2026-10-01T12:00:00Z | 2026-10-01T11:40:08.223Z |
| `CurrentStorms_2026-10-01-1450.json` | 14:50:00Z | `8c29931f6677...` | EP15, EP18, EP19 | **44** | 2026-10-01T15:00:00Z | 2026-10-01T14:49:34.257Z |
| `CurrentStorms_2026-10-01-1452.json` | 14:52:00Z | `e6b9867b8422...` | EP15, EP18, EP19 | **44** | 2026-10-01T15:00:00Z | 2026-10-01T14:49:34.257Z |
| `CurrentStorms_2026-10-01-1454.json` | 14:54:00Z | `ec97069c129d...` | EP15, EP18, EP19 | **44** | 2026-10-01T15:00:00Z | 2026-10-01T14:49:34.257Z |
| `CurrentStorms_2026-10-01-1524.json` | 15:24:00Z | `a2123e393c05...` | EP15, EP18, EP19 | **44** | 2026-10-01T15:00:00Z | 2026-10-01T14:49:34.257Z |
| `CurrentStorms_2026-10-01-1544.json` | 15:44:00Z | `a598c04f8a06...` | EP15, EP18, EP19 | **44** | 2026-10-01T15:00:00Z | 2026-10-01T14:49:34.257Z |
| `CurrentStorms_2026-10-01-1756.json` | 17:56:00Z | `edee89d21522...` | EP15, EP18, EP19 | **44A** | 2026-10-01T18:00:00Z | 2026-10-01T17:54:37.970Z |
| `CurrentStorms_2026-10-01-2036.json` | 20:36:00Z | `1c5c58e7cb42...` | EP15, EP18, EP19 | **44A** | 2026-10-01T18:00:00Z | 2026-10-01T17:54:37.970Z |
| `CurrentStorms_2026-10-01-2038.json` | 20:38:00Z | `e8b6369baf33...` | EP15, EP18, EP19 | **44A** | 2026-10-01T18:00:00Z | 2026-10-01T17:54:37.970Z |
| `CurrentStorms_2026-10-01-2044.json` | 20:44:00Z | `0120c36c941d...` | EP15, EP18, EP19 | **45** | 2026-10-01T21:00:00Z | 2026-10-01T20:43:09.914Z |
| `CurrentStorms_2026-10-01-2046.json` | 20:46:00Z | `b713faba737a...` | EP15, EP18, EP19 | **45** | 2026-10-01T21:00:00Z | 2026-10-01T20:43:09.914Z |
| `CurrentStorms_2026-10-01-2048.json` | 20:48:00Z | `ce185dc5d83a...` | EP15, EP18, EP19 | **45** | 2026-10-01T21:00:00Z | 2026-10-01T20:43:09.914Z |
| `CurrentStorms_2026-10-01-2050.json` | 20:50:00Z | `7c97e6570152...` | EP15, EP18, EP19 | **45** | 2026-10-01T21:00:00Z | 2026-10-01T20:43:09.914Z |
| `CurrentStorms_2026-10-01-2122.json` | 21:22:00Z | `75e38ead545e...` | EP15, EP18, EP19 | **45** | 2026-10-01T21:00:00Z | 2026-10-01T20:43:09.914Z |
| `CurrentStorms_2026-10-01-2334.json` | 23:34:00Z | `7b2354a8e966...` | EP15, EP18, EP19 | **45A** | 2026-10-02T00:00:00Z | 2026-10-01T23:32:41.331Z |

*(Full details with complete 64-hex SHA-256 strings are delivered in `advisory-visibility.csv` and `advisory-visibility.json`.)*

---

## 2. Nolo Advisory Identification & Reconciliation

Comparing the parsed snapshot contents against the benchmark manifest (`examples/noaa_nolo_2026-10-01_public_day.json`), we establish:
- **All 8 expected public advisories** for 2026-10-01 appear in the authentic archived snapshots.
- **Plus 1 subsequent intermediate advisory** (`45A`, nominal issuance `2026-10-02T00:00:00Z`) was captured at `23:34 UTC` on 1 October.
- **Zero in-place revisions**: Each advisory exhibits exactly one unique internal `fileUpdateTime` across all snapshots where it is present.

### Nolo Public Advisory Reconciliation Matrix

| Advisory | Kind | Nominal Issuance UTC | Snapshots Count | First Snapshot (Nominal UTC) | Last Snapshot (Nominal UTC) | Internal `fileUpdateTime` |
| :---: | :---: | :--- | :---: | :--- | :--- | :--- |
| **41A** | Intermediate | 2026-10-01T00:00:00Z | 5 | `02:32:00Z` | `02:40:00Z` | 2026-09-30T23:32:02.763Z |
| **42** | Regular | 2026-10-01T03:00:00Z | 4 | `02:46:00Z` | `03:24:00Z` | 2026-10-01T02:44:35.282Z |
| **42A** | Intermediate | 2026-10-01T06:00:00Z | 2 | `05:40:00Z` | `08:40:00Z` | 2026-10-01T05:38:42.663Z |
| **43** | Regular | 2026-10-01T09:00:00Z | 9 | `08:42:00Z` | `09:24:00Z` | 2026-10-01T08:41:38.587Z |
| **43A** | Intermediate | 2026-10-01T12:00:00Z | 5 | `11:42:00Z` | `14:48:00Z` | 2026-10-01T11:40:08.223Z |
| **44** | Regular | 2026-10-01T15:00:00Z | 5 | `14:50:00Z` | `15:44:00Z` | 2026-10-01T14:49:34.257Z |
| **44A** | Intermediate | 2026-10-01T18:00:00Z | 3 | `17:56:00Z` | `20:38:00Z` | 2026-10-01T17:54:37.970Z |
| **45** | Regular | 2026-10-01T21:00:00Z | 5 | `20:44:00Z` | `21:22:00Z` | 2026-10-01T20:43:09.914Z |
| **45A** | Intermediate | 2026-10-02T00:00:00Z | 1 | `23:34:00Z` | `23:34:00Z` | 2026-10-01T23:32:41.331Z |

---

## 3. Assessment of the Four OCHA Polling Windows

OCHA's historical ingestion architecture executed batch extraction jobs every 6 hours, scheduled at:
**03:30, 09:30, 15:30, and 21:30 UTC**.

When we compare these scheduled run times against the state of the NOAA `CurrentStorms.json` feed, the evidence demonstrates the structural overwrite pattern:

```
00:00 UTC (Adv 41A issued)  ──────┐
                                   ├──> Feed holds 41A from ~23:32 to 02:40 UTC
02:44 UTC (Adv 42 generated) ─────┴──> Adv 42 OVERWRITES Adv 41A in feed!
03:00 UTC (Adv 42 nominal)
03:24 UTC ───────────────────────────> Feed holds Adv 42
03:30 UTC [OCHA BATCH RUN 1] ────────> OCHA polls feed: SEES ONLY ADV 42 (Adv 41A is GONE)

06:00 UTC (Adv 42A issued)  ──────┐
                                   ├──> Feed holds 42A from ~05:38 to 08:40 UTC
08:41 UTC (Adv 43 generated) ─────┴──> Adv 43 OVERWRITES Adv 42A in feed!
09:00 UTC (Adv 43 nominal)
09:24 UTC ───────────────────────────> Feed holds Adv 43
09:30 UTC [OCHA BATCH RUN 2] ────────> OCHA polls feed: SEES ONLY ADV 43 (Adv 42A is GONE)

12:00 UTC (Adv 43A issued)  ──────┐
                                   ├──> Feed holds 43A from ~11:40 to 14:48 UTC
14:49 UTC (Adv 44 generated) ─────┴──> Adv 44 OVERWRITES Adv 43A in feed!
15:00 UTC (Adv 44 nominal)
15:24 UTC ───────────────────────────> Feed holds Adv 44
15:30 UTC [OCHA BATCH RUN 3] ────────> OCHA polls feed: SEES ONLY ADV 44 (Adv 43A is GONE)

18:00 UTC (Adv 44A issued)  ──────┐
                                   ├──> Feed holds 44A from ~17:54 to 20:38 UTC
20:43 UTC (Adv 45 generated) ─────┴──> Adv 45 OVERWRITES Adv 44A in feed!
21:00 UTC (Adv 45 nominal)
21:22 UTC ───────────────────────────> Feed holds Adv 45
21:30 UTC [OCHA BATCH RUN 4] ────────> OCHA polls feed: SEES ONLY ADV 45 (Adv 44A is GONE)
```

### Detailed Polling Window Outcomes

1. **03:30 UTC Batch Run**:
   - `CurrentStorms_2026-10-01-0324.json` (6 minutes before scheduled poll) contains **Advisory 42**.
   - Advisory 42 was generated at `02:44:35 UTC` and appeared in the archive at `02:46 UTC`.
   - Intermediate **Advisory 41A** was already overwritten in the feed 44 minutes prior to the scheduled run.
   - **Conclusion**: Conditionally, a 03:30 UTC poll querying only `CurrentStorms.json` could never capture Advisory 41A.

2. **09:30 UTC Batch Run**:
   - `CurrentStorms_2026-10-01-0924.json` (6 minutes before scheduled poll) contains **Advisory 43**.
   - Advisory 43 was generated at `08:41:38 UTC` and appeared in the archive at `08:42 UTC`.
   - Intermediate **Advisory 42A** was already overwritten in the feed 48 minutes prior to the scheduled run.
   - **Conclusion**: Conditionally, a 09:30 UTC poll querying only `CurrentStorms.json` could never capture Advisory 42A.

3. **15:30 UTC Batch Run**:
   - `CurrentStorms_2026-10-01-1524.json` and `-1544.json` (bracketing the scheduled poll) contain **Advisory 44**.
   - Advisory 44 was generated at `14:49:34 UTC` and appeared in the archive at `14:50 UTC`.
   - Intermediate **Advisory 43A** was already overwritten in the feed 40 minutes prior to the scheduled run.
   - **Conclusion**: Conditionally, a 15:30 UTC poll querying only `CurrentStorms.json` could never capture Advisory 43A.

4. **21:30 UTC Batch Run**:
   - `CurrentStorms_2026-10-01-2122.json` (8 minutes before scheduled poll) contains **Advisory 45**.
   - Advisory 45 was generated at `20:43:09 UTC` and appeared in the archive at `20:44 UTC`.
   - Intermediate **Advisory 44A** was already overwritten in the feed 46 minutes prior to the scheduled run.
   - **Conclusion**: Conditionally, a 21:30 UTC poll querying only `CurrentStorms.json` could never capture Advisory 44A.

---

## 4. Answers to the Core Mission Questions

### Q1: How many authentic NOAA JSON files were retrieved and verified?
**Answer**: Exactly **39 authentic NOAA CurrentStorms JSON files** for 2026-10-01 UTC were downloaded from `https://www.nhc.noaa.gov/archive/activeJson/2026/`. Every file passed size-bound verification (< 2 MB) and was verified via SHA-256 digest. No files were truncated or corrupted. Zero DNS failures and zero HTTP 403 Forbidden errors were encountered.

### Q2: Which of Nolo's eight advisories appear in the retrieved snapshots?
**Answer**: **All eight** expected public advisories (`41A`, `42`, `42A`, `43`, `43A`, `44`, `44A`, `45`) appear in the retrieved snapshots. Furthermore, the first advisory of the next UTC cycle (`45A`, nominal issuance 2026-10-02T00:00:00Z) appears in snapshot `CurrentStorms_2026-10-01-2334.json`.

### Q3: Can we establish source visibility at each of the four historical polling times, or only a conditional reconstruction?
**Answer**: **Only a conditional reconstruction**.
We must maintain strict epistemic rigor: our retrieved data represents NOAA's retrospective web archive. We do not have contemporaneous network packet logs from 1 October 2026 showing the exact second packets crossed OCHA's edge routers. Our reconstruction is **conditional** upon the assumption that NOAA's archive files accurately reflect what was served on `CurrentStorms.json` during the corresponding filename and `fileUpdateTime` intervals. Under that well-founded conditional assumption, intermediate advisories were overwritten 40 to 48 minutes prior to each scheduled OCHA polling run.

### Q4: Do we have evidence of actual OCHA processing omissions?
**Answer**: **No**.
We possess zero production credentials, Databricks execution logs, or historical database exports from OCHA. Using `storm_audit.operational_evidence`, all 8 advisories are formally classified as `operational_evidence_unavailable`. We have proved the *structural vulnerability* of the polling architecture, but we cannot claim to know whether OCHA's historical systems processed these advisories (e.g. through separate feeds, manual interventions, or backfills) without authorized operational records.

### Q5: Does this justify advancing an event-driven recovery proposal?
**Answer**: **Yes, strongly justified from an architectural engineering perspective**.
The empirical evidence proves that NOAA's `CurrentStorms.json` is a state-replacement feed where intermediate advisories are ephemeral, remaining visible for only ~3 hours before being superseded by the next regular advisory. A fixed 6-hour polling schedule sampling a single state-replacement endpoint is mathematically incapable of observing ephemeral intermediate updates that live for < 3 hours. Advancing an event-driven ingestion design (e.g., webhook, RSS/ATOM monitoring, or polling every 30-60 minutes) directly resolves this structural blind spot.

### Q6: What is the single remaining obstacle to demonstrating real humanitarian or operational value?
**Answer**: **The absence of an authorized, read-only historical export of OCHA's operational database (`storms.nhc_tracks_geo`) and Databricks run history for 1 October 2026**.
Without this operational ground truth, the research demonstrates a source-side overwriting mechanism and theoretical omission, but cannot quantify whether any humanitarian exposure calculations (population affected, shelter needs) were actually missed or degraded in production.

---

## 5. Test Suite Verification & Reproduction Commands

### Environment Setup
```powershell
# From repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pytest sqlalchemy
```

### Harvest Execution (Re-downloading raw archive files)
```powershell
python -m storm_audit.archive_harvester --day 2026-10-01 --fetch --max-files 160 --out-dir ./noaa-archive
```

### Mandated Audit Test Suite
```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m pytest -q tests/test_archive_harvester.py tests/test_snapshot_timeline.py tests/test_operational_evidence.py
```
**Test Results**:
```
.........................s................................               [100%]
57 passed, 1 skipped in 0.58s
```
*(The 1 skipped test is `test_path_traversal_and_symlink_escape_rejected`, skipped only on unprivileged Windows environments where `os.symlink` requires elevated permissions).*

### Operational Evidence Join Verification
```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m storm_audit.operational_evidence `
  --manifest examples/noaa_nolo_2026-10-01_public_day.json `
  --reviewed-index examples/noaa_nolo_2026-10-01_index_control.json `
  --output operational-evidence-report.json
```
**Output**:
```json
{"source_listed": 8, "operational_export_assurance": "no_operational_export", "counts": {"operational_evidence_unavailable": 8}}
```

---

## 6. Formal Maintainer Request for Operational Evidence

To close the final gap and verify whether OCHA actually missed these four intermediate advisories in production, the pipeline maintainers or authorized Databricks administrators are requested to provide the following minimal, read-only artifacts:

### 1. Minimal SQL Database Export
Execute the following read-only query against the production PostgreSQL database:
```sql
SELECT 
    storm_id,
    advisory_number,
    issuance_timestamp,
    created_at AS ingestion_timestamp,
    COUNT(*) AS row_count
FROM storms.nhc_tracks_geo
WHERE storm_id = 'EP152026'
  AND issuance_timestamp >= '2026-10-01 00:00:00+00'
  AND issuance_timestamp <  '2026-10-02 00:00:00+00'
GROUP BY storm_id, advisory_number, issuance_timestamp, created_at
ORDER BY issuance_timestamp ASC;
```

### 2. Export Schema Packaging
Format the query results according to the existing contract (`examples/operational-export-contract-example.json`):
```json
{
  "schema_version": 1,
  "table": "storms.nhc_tracks_geo",
  "storm_id": "EP152026",
  "scope_start": "2026-10-01T00:00:00Z",
  "scope_until": "2026-10-02T00:00:00Z",
  "query_status": "succeeded",
  "coverage": "full_bounded_scan",
  "snapshot_type": "current_state",
  "exported_at": "YYYY-MM-DDTHH:MM:SSZ",
  "rows": [
    {
      "storm_id": "EP152026",
      "issued_at": "2026-10-01T00:00:00Z",
      "row_count": 12
    }
  ]
}
```

### 3. Databricks Run Metadata
- Export run history and trigger timestamps for the NHC ingestion pipeline job on `2026-10-01` UTC (specifically around the 03:30, 09:30, 15:30, and 21:30 execution windows).
- Check whether secondary ingestion triggers or retrospective backfill jobs were executed for Nolo on or after 2026-10-01.
