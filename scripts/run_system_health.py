#!/usr/bin/env python3
"""Run the deeper AF system health checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, argv: list[str]) -> bool:
    print(f"[af_system_health] Running {label} ...")
    proc = subprocess.run(
        argv,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"[af_system_health] {label} FAILED (exit code {proc.returncode})")
        return False
    print(f"[af_system_health] {label} OK")
    return True


def main() -> int:
    ok_doctor = _run("doctor_deep", [sys.executable, str(ROOT / "cli" / "main.py"), "doctor", "--deep"])
    ok_validate = _run("validate_codebase", [sys.executable, str(ROOT / "scripts" / "validate_codebase.py")])
    print("\n[af_system_health] SUMMARY")
    print(f" - doctor_deep: {'OK' if ok_doctor else 'FAILED'}")
    print(f" - validate_codebase: {'OK' if ok_validate else 'FAILED'}")
    return 0 if ok_doctor and ok_validate else 1


if __name__ == "__main__":
    raise SystemExit(main())
