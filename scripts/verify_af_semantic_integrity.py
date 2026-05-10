#!/usr/bin/env python3
"""Verify AF semantic state integrity beyond simple path existence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "article_finder.db"

ALLOWED_TRIAGE_DECISIONS = {"pending", "send_to_eater", "review", "reject"}
DEPRECATED_TRIAGE_DECISIONS = {"needs_review": "review"}
ALLOWED_AE_STATUSES = {"pending", "SUCCESS", "PARTIAL_SUCCESS", "FAIL"}
ALLOWED_STATUSES = {
    "candidate",
    "pending_scorer",
    "downloaded",
    "queued_for_eater",
    "sent_to_eater",
    "processed_success",
    "processed_partial",
    "processed_fail",
    "needs_human_review",
    "rejected",
}


def _resolve_path(stored_path: str | None, repo_root: Path) -> Path | None:
    if not stored_path:
        return None
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return repo_root / p


def _load_result_status(output_dir: Path) -> tuple[str | None, int | None, int | None, float | None]:
    result_path = output_dir / "result.json"
    if not result_path.exists():
        return None, None, None, None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None, None
    summary = payload.get("summary") or {}
    quality = payload.get("quality") or {}
    return (
        payload.get("status"),
        summary.get("n_claims"),
        summary.get("n_rules"),
        quality.get("confidence"),
    )


def gather_metrics(db_path: Path = DB_PATH, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    invalid_status_rows = cur.execute(
        f"""
        SELECT COUNT(*)
        FROM papers
        WHERE status IS NOT NULL
          AND TRIM(status) != ''
          AND status NOT IN ({",".join("?" for _ in ALLOWED_STATUSES)})
        """,
        tuple(sorted(ALLOWED_STATUSES)),
    ).fetchone()[0]

    invalid_triage_rows = cur.execute(
        f"""
        SELECT COUNT(*)
        FROM papers
        WHERE triage_decision IS NOT NULL
          AND TRIM(triage_decision) != ''
          AND triage_decision NOT IN ({",".join("?" for _ in (ALLOWED_TRIAGE_DECISIONS | set(DEPRECATED_TRIAGE_DECISIONS)))})
        """,
        tuple(sorted(ALLOWED_TRIAGE_DECISIONS | set(DEPRECATED_TRIAGE_DECISIONS))),
    ).fetchone()[0]

    deprecated_triage_rows = cur.execute(
        "SELECT COUNT(*) FROM papers WHERE triage_decision = 'needs_review'"
    ).fetchone()[0]

    pending_triage_invalid_status_rows = cur.execute(
        """
        SELECT COUNT(*)
        FROM papers
        WHERE triage_decision = 'pending'
          AND status NOT IN ('candidate', 'pending_scorer')
        """
    ).fetchone()[0]

    ae_pending_without_job_rows = cur.execute(
        """
        SELECT COUNT(*)
        FROM papers
        WHERE ae_status = 'pending'
          AND (ae_job_path IS NULL OR TRIM(ae_job_path) = '')
        """
    ).fetchone()[0]

    ae_terminal_without_output_rows = 0
    ae_pending_with_output_rows = 0
    ae_result_status_mismatch_rows = 0
    ae_result_summary_mismatch_rows = 0

    rows = cur.execute(
        """
        SELECT paper_id, ae_status, ae_job_path, ae_output_path, ae_n_claims, ae_n_rules, ae_confidence
        FROM papers
        WHERE ae_status IS NOT NULL AND TRIM(ae_status) != ''
        """
    ).fetchall()
    for row in rows:
        ae_status = row["ae_status"]
        if ae_status not in ALLOWED_AE_STATUSES:
            # Count under result mismatch family so the report stays compact.
            ae_result_status_mismatch_rows += 1
            continue
        output_path = _resolve_path(row["ae_output_path"], repo_root)
        output_exists = bool(output_path and output_path.exists())
        if ae_status in {"SUCCESS", "PARTIAL_SUCCESS", "FAIL"} and not output_exists:
            ae_terminal_without_output_rows += 1
            continue
        if ae_status == "pending" and output_exists:
            ae_pending_with_output_rows += 1
        if output_exists:
            result_status, n_claims, n_rules, confidence = _load_result_status(output_path)
            if result_status and result_status != ae_status:
                ae_result_status_mismatch_rows += 1
            if result_status and ae_status != "pending":
                if row["ae_n_claims"] is not None and n_claims is not None and int(row["ae_n_claims"]) != int(n_claims):
                    ae_result_summary_mismatch_rows += 1
                if row["ae_n_rules"] is not None and n_rules is not None and int(row["ae_n_rules"]) != int(n_rules):
                    ae_result_summary_mismatch_rows += 1
                if row["ae_confidence"] is not None and confidence is not None and abs(float(row["ae_confidence"]) - float(confidence)) > 1e-9:
                    ae_result_summary_mismatch_rows += 1

    metrics = {
        "papers_total": cur.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "pending_triage_rows": cur.execute("SELECT COUNT(*) FROM papers WHERE triage_decision = 'pending'").fetchone()[0],
        "pending_triage_with_pdf_rows": cur.execute(
            "SELECT COUNT(*) FROM papers WHERE triage_decision = 'pending' AND pdf_path IS NOT NULL AND TRIM(pdf_path) != ''"
        ).fetchone()[0],
        "pending_triage_with_abstract_rows": cur.execute(
            "SELECT COUNT(*) FROM papers WHERE triage_decision = 'pending' AND abstract IS NOT NULL AND TRIM(abstract) != ''"
        ).fetchone()[0],
        "invalid_status_rows": invalid_status_rows,
        "invalid_triage_rows": invalid_triage_rows,
        "deprecated_triage_rows": deprecated_triage_rows,
        "pending_triage_invalid_status_rows": pending_triage_invalid_status_rows,
        "ae_pending_without_job_rows": ae_pending_without_job_rows,
        "ae_terminal_without_output_rows": ae_terminal_without_output_rows,
        "ae_pending_with_output_rows": ae_pending_with_output_rows,
        "ae_result_status_mismatch_rows": ae_result_status_mismatch_rows,
        "ae_result_summary_mismatch_rows": ae_result_summary_mismatch_rows,
    }
    con.close()
    return metrics


def main() -> int:
    metrics = gather_metrics()
    hard_zero = [
        "invalid_status_rows",
        "invalid_triage_rows",
        "deprecated_triage_rows",
        "pending_triage_invalid_status_rows",
        "ae_pending_without_job_rows",
        "ae_terminal_without_output_rows",
        "ae_pending_with_output_rows",
        "ae_result_status_mismatch_rows",
        "ae_result_summary_mismatch_rows",
    ]
    failures = [key for key in hard_zero if metrics[key] != 0]
    payload = {
        "status": "ok" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
        "notes": {
            "pending_semantics": (
                "triage_decision='pending' means a discovered candidate not yet fully scored, "
                "not a downloaded PDF waiting for AE."
            )
        },
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
