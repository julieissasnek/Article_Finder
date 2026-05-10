#!/usr/bin/env python3
"""Run AF weekly system health and archive the result."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.system_health import render_check, run_deep_checks, summarize_results


def main() -> int:
    results = run_deep_checks()
    for result in results:
        print(render_check(result))
    payload = summarize_results(results)
    payload["outputs"] = {result.label: result.stdout for result in results}

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        payload_path = Path(handle.name)
        handle.write(json.dumps(payload, indent=2) + "\n")

    archive_script = REPO_ROOT / "scripts" / "archive_system_health_report.py"
    rc = subprocess.run([sys.executable, str(archive_script), "--payload", str(payload_path)]).returncode
    payload_path.unlink(missing_ok=True)
    return 0 if rc == 0 and payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
