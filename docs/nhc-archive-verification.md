# Independent primary-source advisory cross-check (partial)

This note documents **seven independently identified NHC/CPHC archive
products** corresponding to advisories in the synthetic September 24, 2026
incident fixture. Their existence is evidenced by official archive products.
It does **not** verify that OCHA's database missed them: that would require
an authorized, time-consistent historical database snapshot.

| Storm | UTC issuance | Official source |
|---|---|---|
| Fay (AL062026) | 03:00 | [NHC forecast advisory 016](https://www.nhc.noaa.gov/archive/2026/al06/al062026.fstadv.016.shtml) |
| Fay (AL062026) | 09:00 | [NHC forecast advisory 017](https://www.nhc.noaa.gov/archive/2026/al06/al062026.fstadv.017.shtml) |
| Fay (AL062026) | 15:00 | [NHC forecast advisory 018](https://www.nhc.noaa.gov/archive/2026/al06/al062026.fstadv.018.shtml) |
| Nolo (EP152026) | 09:00 | [CPHC/NHC public advisory 015](https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.015.shtml) |
| Nolo (EP152026) | 15:00 | [CPHC/NHC public advisory 016](https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public.016.shtml) |
| Nolo (EP152026) | 18:00 | [CPHC/NHC intermediate advisory 016A](https://www.nhc.noaa.gov/archive/2026/ep15/ep152026.public_a.016.shtml) |
| Odalys (EP162026) | 09:00 | [NHC forecast advisory 017](https://www.nhc.noaa.gov/archive/2026/ep16/ep162026.fstadv.017.shtml) |

**Remaining 13 of the 20** synthetic gap expectations still cite the OCHA
September outage account ([PR #53](https://github.com/OCHA-DAP/ds-storms-pipeline/pull/53)),
rather than individually cross-checked NOAA archive products. The fixture
also contains four **invented** post-outage output records solely to
exercise the propagation detector. Its overall `source_assurance` therefore
remains `illustrative`.

## Why this matters

- An external advisory source and an operational processing database
  provide two genuinely different classes of evidence.
- A verified archive product proves **publication**, not a pipeline gap.
- Even a real missing source input only signals **possible** downstream
  geometry/exposure staleness until an isolated historical replay measures it.
- The correct next validation step is a maintainer-approved read-only
  historical snapshot, with a blind source catalog and a fixed audit window.
