#!/usr/bin/env python3
"""Run the deeper AF system health checks."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.system_health import render_check, run_deep_checks


def main() -> int:
    results = run_deep_checks()
    for result in results:
        print(render_check(result))
    print("\n[af_system_health] SUMMARY")
    for result in results:
        print(f" - {result.label}: {'OK' if result.ok else 'FAILED'}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
