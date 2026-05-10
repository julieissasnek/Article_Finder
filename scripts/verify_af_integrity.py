#!/usr/bin/env python3
"""Verify AF corpus and handoff integrity."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "article_finder.db"


def _resolve_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def gather_metrics(db_path: Path = DB_PATH) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    missing_pdf_path_files = 0
    pdf_sha256_mismatch_rows = 0
    missing_ae_job_paths = 0
    missing_ae_output_paths = 0
    referenced_pdf_paths: set[str] = set()

    for row in con.execute("SELECT pdf_path, pdf_sha256, ae_job_path, ae_output_path FROM papers"):
        pdf_path = _resolve_path(row["pdf_path"])
        if pdf_path is not None:
            referenced_pdf_paths.add(str(pdf_path.resolve(strict=False)))
            if not pdf_path.exists():
                missing_pdf_path_files += 1
            else:
                expected_sha = (row["pdf_sha256"] or "").strip().lower()
                if expected_sha:
                    actual_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
                    if actual_sha != expected_sha:
                        pdf_sha256_mismatch_rows += 1
        ae_job_path = _resolve_path(row["ae_job_path"])
        if ae_job_path is not None and not ae_job_path.exists():
            missing_ae_job_paths += 1
        ae_output_path = _resolve_path(row["ae_output_path"])
        if ae_output_path is not None and not ae_output_path.exists():
            missing_ae_output_paths += 1

    duplicate_pdf_sha_rows = con.execute(
        """
        SELECT COALESCE(SUM(c), 0)
        FROM (
          SELECT COUNT(*) - 1 AS c
          FROM papers
          WHERE pdf_sha256 IS NOT NULL AND trim(pdf_sha256) != ''
          GROUP BY pdf_sha256
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    orphan_pdf_files = 0
    pdf_dir = REPO_ROOT / "data" / "pdfs"
    if pdf_dir.exists():
        for path in pdf_dir.glob("*.pdf"):
            if str(path.resolve(strict=False)) not in referenced_pdf_paths:
                orphan_pdf_files += 1

    metrics = {
        "papers_total": con.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "queue_total": con.execute("SELECT COUNT(*) FROM expansion_queue").fetchone()[0],
        "with_pdf_path": con.execute(
            "SELECT COUNT(*) FROM papers WHERE pdf_path IS NOT NULL AND trim(pdf_path) != ''"
        ).fetchone()[0],
        "with_abstract": con.execute(
            "SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND trim(abstract) != ''"
        ).fetchone()[0],
        "missing_pdf_path_files": missing_pdf_path_files,
        "pdf_sha256_mismatch_rows": pdf_sha256_mismatch_rows,
        "duplicate_pdf_sha_rows": duplicate_pdf_sha_rows,
        "orphan_pdf_files": orphan_pdf_files,
        "missing_ae_job_paths": missing_ae_job_paths,
        "missing_ae_output_paths": missing_ae_output_paths,
    }
    con.close()
    return metrics


def main() -> int:
    metrics = gather_metrics()
    hard_zero = [
        "missing_pdf_path_files",
        "pdf_sha256_mismatch_rows",
        "duplicate_pdf_sha_rows",
        "orphan_pdf_files",
        "missing_ae_job_paths",
        "missing_ae_output_paths",
    ]
    failures = [key for key in hard_zero if metrics[key] != 0]
    payload = {
        "status": "ok" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
