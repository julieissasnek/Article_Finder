#!/usr/bin/env python3
"""Archive AF system-health outputs for weekly monitoring."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = REPO_ROOT / "data" / "health_reports"


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive AF health-report payloads.")
    parser.add_argument("--payload", type=Path, required=True, help="JSON payload to archive")
    args = parser.parse_args()

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = REPORT_ROOT / f"system_health_{stamp}.json"
    latest_path = REPORT_ROOT / "latest.json"

    data = json.loads(args.payload.read_text(encoding="utf-8"))
    archive_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    latest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "archive_path": str(archive_path), "latest_path": str(latest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
