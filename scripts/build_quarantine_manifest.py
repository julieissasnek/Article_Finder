#!/usr/bin/env python3
"""Build a manifest for the latest AF quarantine batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.quarantine import QUARANTINE_ROOT, build_manifest, latest_quarantine_batch, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a quarantine manifest.")
    parser.add_argument("--batch-dir", type=Path, default=None, help="Specific quarantine batch")
    parser.add_argument("--write", action="store_true", help="Write manifest.json into the batch directory")
    args = parser.parse_args()

    batch = args.batch_dir or latest_quarantine_batch(QUARANTINE_ROOT)
    if batch is None or not batch.exists():
        print(json.dumps({"status": "fail", "reason": "no_quarantine_batch"}, indent=2))
        return 1

    manifest = build_manifest(batch)
    payload = {"status": "ok", "manifest": manifest}
    if args.write:
        payload["manifest_path"] = str(write_manifest(batch, manifest))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
