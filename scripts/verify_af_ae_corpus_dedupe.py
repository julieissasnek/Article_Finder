#!/usr/bin/env python3
"""Verify that AF rows have truthful AE corpus dedupe materialization."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "article_finder.db"

ALLOWED_STATUSES = {"matched", "unmatched", "ambiguous"}
ALLOWED_BASES = {"exact_doi", "exact_title_year", "exact_title", "none"}


def _json_list(text: str | None) -> list[str] | None:
    if text is None:
        return []
    if not str(text).strip():
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    return [str(item) for item in payload]


def gather_metrics(db_path: Path = DB_PATH) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT paper_id, doi, title, atlas_classified_at,
               ae_corpus_match_status, ae_corpus_match_basis, ae_corpus_match_paper_id,
               ae_corpus_match_confidence, ae_corpus_match_candidates_json,
               ae_corpus_deduped_at
        FROM papers
        """
    ).fetchall()

    metrics = {
        "rows_total": len(rows),
        "missing_dedupe_rows": 0,
        "bad_status_rows": 0,
        "bad_basis_rows": 0,
        "matched_missing_paper_id_rows": 0,
        "matched_bad_confidence_rows": 0,
        "unmatched_with_paper_id_rows": 0,
        "ambiguous_missing_candidates_rows": 0,
        "bad_candidates_json_rows": 0,
        "missing_deduped_at_rows": 0,
    }

    for row in rows:
        has_identifier_surface = bool(str(row["doi"] or "").strip() or str(row["title"] or "").strip())
        if row["atlas_classified_at"] and has_identifier_surface and not row["ae_corpus_match_status"]:
            metrics["missing_dedupe_rows"] += 1
            continue

        status = str(row["ae_corpus_match_status"] or "").strip()
        if not status:
            continue
        if status not in ALLOWED_STATUSES:
            metrics["bad_status_rows"] += 1
        basis = str(row["ae_corpus_match_basis"] or "").strip()
        if basis not in ALLOWED_BASES:
            metrics["bad_basis_rows"] += 1
        if not str(row["ae_corpus_deduped_at"] or "").strip():
            metrics["missing_deduped_at_rows"] += 1
        candidates = _json_list(row["ae_corpus_match_candidates_json"])
        if candidates is None:
            metrics["bad_candidates_json_rows"] += 1
            candidates = []

        if status == "matched":
            if not str(row["ae_corpus_match_paper_id"] or "").strip():
                metrics["matched_missing_paper_id_rows"] += 1
            confidence = row["ae_corpus_match_confidence"]
            if confidence is None or float(confidence) <= 0 or float(confidence) > 1:
                metrics["matched_bad_confidence_rows"] += 1
        elif status == "unmatched":
            if str(row["ae_corpus_match_paper_id"] or "").strip():
                metrics["unmatched_with_paper_id_rows"] += 1
            if basis != "none":
                metrics["bad_basis_rows"] += 1
        elif status == "ambiguous":
            if not candidates:
                metrics["ambiguous_missing_candidates_rows"] += 1

    con.close()
    return metrics


def main() -> int:
    metrics = gather_metrics()
    hard_zero = [
        "missing_dedupe_rows",
        "bad_status_rows",
        "bad_basis_rows",
        "matched_missing_paper_id_rows",
        "matched_bad_confidence_rows",
        "unmatched_with_paper_id_rows",
        "ambiguous_missing_candidates_rows",
        "bad_candidates_json_rows",
        "missing_deduped_at_rows",
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
