"""Quarantine manifest helpers for AF integrity residue."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QUARANTINE_ROOT = REPO_ROOT / "data" / "quarantine" / "integrity_orphans"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_quarantine_batch(root: Path = QUARANTINE_ROOT) -> Path | None:
    if not root.exists():
        return None
    batches = sorted(path for path in root.iterdir() if path.is_dir())
    return batches[-1] if batches else None


def build_manifest(batch_dir: Path) -> dict[str, object]:
    files = sorted(path for path in batch_dir.glob("*.pdf"))
    entries = []
    total_bytes = 0
    for path in files:
        size = path.stat().st_size
        total_bytes += size
        entries.append(
            {
                "name": path.name,
                "size_bytes": size,
                "sha256": _file_sha256(path),
            }
        )
    return {
        "batch_dir": str(batch_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "retention_policy": {
            "default_action": "review_then_archive_or_reingest",
            "notes": [
                "Quarantined PDFs are not deletion candidates by default.",
                "They should be reviewed for re-ingest or archived after provenance checks."
            ],
        },
        "files": entries,
    }


def write_manifest(batch_dir: Path, manifest: dict[str, object]) -> Path:
    target = batch_dir / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target
