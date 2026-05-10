"""Shared AF system-health helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    label: str
    ok: bool
    returncode: int
    stdout: str


def run_check(label: str, argv: list[str], cwd: Path = ROOT) -> CheckResult:
    proc = subprocess.run(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return CheckResult(label=label, ok=proc.returncode == 0, returncode=proc.returncode, stdout=proc.stdout)


def render_check(result: CheckResult) -> str:
    lines = [f"[af_system_health] Running {result.label} ...", result.stdout.rstrip()]
    lines.append(
        f"[af_system_health] {result.label} {'OK' if result.ok else f'FAILED (exit code {result.returncode})'}"
    )
    return "\n".join(line for line in lines if line)


def deep_check_specs() -> list[tuple[str, list[str]]]:
    return [
        ("doctor_deep", [sys.executable, str(ROOT / "cli" / "main.py"), "doctor", "--deep"]),
        ("validate_codebase", [sys.executable, str(ROOT / "scripts" / "validate_codebase.py")]),
        ("verify_af_integrity", [sys.executable, str(ROOT / "scripts" / "verify_af_integrity.py")]),
        ("verify_af_quarantine", [sys.executable, str(ROOT / "scripts" / "verify_af_quarantine.py")]),
        ("verify_af_semantic_integrity", [sys.executable, str(ROOT / "scripts" / "verify_af_semantic_integrity.py")]),
    ]


def run_deep_checks() -> list[CheckResult]:
    return [run_check(label, argv) for label, argv in deep_check_specs()]


def summarize_results(results: list[CheckResult]) -> dict[str, object]:
    checks = {result.label: "OK" if result.ok else "FAILED" for result in results}
    return {
        "status": "ok" if all(result.ok for result in results) else "fail",
        "checks": checks,
    }


def summarize_results_json(results: list[CheckResult]) -> str:
    return json.dumps(summarize_results(results), indent=2)
