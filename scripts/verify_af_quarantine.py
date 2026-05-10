#!/usr/bin/env python3
"""Verify AF quarantine governance surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.quarantine import QUARANTINE_ROOT, latest_quarantine_batch


def gather_quarantine_metrics(root: Path = QUARANTINE_ROOT) -> dict[str, Any]:
    latest = latest_quarantine_batch(root)
    metrics: dict[str, Any] = {
        "quarantine_root_exists": root.exists(),
        "latest_batch_exists": latest is not None and latest.exists(),
        "latest_batch_path": str(latest) if latest else None,
        "latest_batch_manifest_exists": False,
        "latest_batch_file_count": 0,
    }
    if latest and latest.exists():
        metrics["latest_batch_manifest_exists"] = (latest / "manifest.json").exists()
        metrics["latest_batch_file_count"] = len(list(latest.glob("*.pdf")))
    return metrics


def main() -> int:
    metrics = gather_quarantine_metrics()
    failures = []
    if metrics["latest_batch_exists"] and not metrics["latest_batch_manifest_exists"]:
        failures.append("latest_batch_manifest_exists")
    payload = {
        "status": "ok" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
