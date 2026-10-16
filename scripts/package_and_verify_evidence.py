"""Package and independently verify the complete NOAA Nolo evidence bundle.

Creates nolo-noaa-evidence-2026-10-01.zip containing all original inputs,
manifests, reproduction scripts, and generated reports, alongside SHA256SUMS.txt.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = REPO_ROOT / "noaa-archive"
ZIP_PATH = REPO_ROOT / "nolo-noaa-evidence-2026-10-01.zip"
SHA256SUMS_PATH = REPO_ROOT / "SHA256SUMS.txt"


def generate_sha256sums() -> list[tuple[str, str]]:
    """Hash every raw and produced evidence artifact."""
    entries = []
    
    # 1. Directory HTML
    html_file = ARCHIVE_DIR / "index-2026.html"
    if html_file.exists():
        digest = sha256(html_file.read_bytes()).hexdigest()
        entries.append((digest, f"noaa-archive/{html_file.name}"))
        
    # 2. All 39 snapshots
    snapshots = sorted(list(ARCHIVE_DIR.glob("CurrentStorms_2026-10-01-*.json")))
    for s in snapshots:
        digest = sha256(s.read_bytes()).hexdigest()
        entries.append((digest, f"noaa-archive/{s.name}"))
        
    # 3. Advisory manifest
    manifest_file = REPO_ROOT / "examples" / "noaa_nolo_2026-10-01_public_day.json"
    if manifest_file.exists():
        digest = sha256(manifest_file.read_bytes()).hexdigest()
        entries.append((digest, "examples/noaa_nolo_2026-10-01_public_day.json"))
        
    # 4. Reports & logs
    for rname in [
        "retrieval-log.json",
        "advisory-visibility.csv",
        "advisory-visibility.json",
        "independent-replay.json",
        "methodology.md",
        "results.md",
        "independent-replay.md",
        "maintainer-request.md",
        "cost-and-architecture-comparison.md",
    ]:
        rf = REPO_ROOT / rname
        if rf.exists():
            digest = sha256(rf.read_bytes()).hexdigest()
            entries.append((digest, rname))
            
    # Write SHA256SUMS.txt
    lines = [f"{digest}  {path}\n" for digest, path in entries]
    SHA256SUMS_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {SHA256SUMS_PATH}")
    return entries


def create_evidence_zip():
    """Package the portable ZIP archive."""
    generate_sha256sums()
    
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # SHA256SUMS.txt
        zf.write(SHA256SUMS_PATH, arcname="SHA256SUMS.txt")
        
        # Original HTML
        html_file = ARCHIVE_DIR / "index-2026.html"
        if html_file.exists():
            zf.write(html_file, arcname="original-evidence/index-2026.html")
            
        # Original 39 JSON files
        snapshots = sorted(list(ARCHIVE_DIR.glob("CurrentStorms_2026-10-01-*.json")))
        for s in snapshots:
            zf.write(s, arcname=f"original-evidence/snapshots/{s.name}")
            
        # Retrieval log
        rlog = REPO_ROOT / "retrieval-log.json"
        if rlog.exists():
            zf.write(rlog, arcname="retrieval-log.json")
            
        # Manifest
        manifest_file = REPO_ROOT / "examples" / "noaa_nolo_2026-10-01_public_day.json"
        if manifest_file.exists():
            zf.write(manifest_file, arcname="examples/noaa_nolo_2026-10-01_public_day.json")
            
        # Scripts
        for sfile in (REPO_ROOT / "scripts").glob("*.py"):
            zf.write(sfile, arcname=f"scripts/{sfile.name}")
            
        # Reports
        for doc in [
            "methodology.md",
            "results.md",
            "independent-replay.md",
            "independent-replay.json",
            "advisory-visibility.csv",
            "advisory-visibility.json",
            "maintainer-request.md",
            "cost-and-architecture-comparison.md",
        ]:
            dp = REPO_ROOT / doc
            if dp.exists():
                zf.write(dp, arcname=doc)
                
    # Verify ZIP integrity
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        bad_file = zf.testzip()
        if bad_file:
            raise RuntimeError(f"Corrupt file in ZIP: {bad_file}")
        namelist = zf.namelist()
        print(f"Verified ZIP {ZIP_PATH.name}: {len(namelist)} entries, size={ZIP_PATH.stat().st_size} bytes")
        
    print(f"\nABSOLUTE_ZIP_PATH={ZIP_PATH.resolve()}")


if __name__ == "__main__":
    create_evidence_zip()
