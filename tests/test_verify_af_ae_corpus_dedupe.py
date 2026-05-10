from __future__ import annotations

import sqlite3
from pathlib import Path

from core.database import Database
from scripts.verify_af_ae_corpus_dedupe import gather_metrics


def test_verify_af_ae_corpus_dedupe_detects_missing_last_mile(tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    Database(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO papers (
            paper_id, title, status, triage_decision, atlas_classified_at,
            created_at, updated_at
        ) VALUES (?, ?, 'candidate', 'review', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        ("p1", "Some titled row"),
    )
    con.commit()
    con.close()

    metrics = gather_metrics(db_path)

    assert metrics["rows_total"] == 1
    assert metrics["missing_dedupe_rows"] == 1


def test_verify_af_ae_corpus_dedupe_accepts_consistent_row(tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    Database(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """
        INSERT INTO papers (
            paper_id, doi, title, status, triage_decision, atlas_classified_at,
            ae_corpus_match_status, ae_corpus_match_basis, ae_corpus_match_paper_id,
            ae_corpus_match_confidence, ae_corpus_match_candidates_json, ae_corpus_deduped_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'candidate', 'send_to_eater', CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            "p2",
            "10.1234/x",
            "Known paper",
            "matched",
            "exact_doi",
            "PDF-0009",
            1.0,
            '["PDF-0009"]',
        ),
    )
    con.commit()
    con.close()

    metrics = gather_metrics(db_path)

    assert metrics["missing_dedupe_rows"] == 0
    assert metrics["bad_status_rows"] == 0
    assert metrics["matched_missing_paper_id_rows"] == 0
