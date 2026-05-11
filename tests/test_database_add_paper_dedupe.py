from __future__ import annotations

import sqlite3
from pathlib import Path

import core.database as database_module
from core.database import Database


def test_add_paper_materializes_ae_corpus_dedupe(monkeypatch, tmp_path: Path) -> None:
    def _stub_build_fields(paper, *, deduped_at):
        assert paper["title"] == "Known paper"
        return {
            "ae_corpus_match_status": "matched",
            "ae_corpus_match_basis": "exact_title",
            "ae_corpus_match_paper_id": "PDF-0009",
            "ae_corpus_match_confidence": 0.95,
            "ae_corpus_match_candidates_json": '["PDF-0009"]',
            "ae_corpus_deduped_at": deduped_at,
        }

    monkeypatch.setattr(database_module, "build_paper_dedupe_fields", _stub_build_fields)

    db_path = tmp_path / "article_finder.db"
    db = Database(db_path)
    paper_id = db.add_paper(
        {
            "doi": "10.1234/test",
            "title": "Known paper",
            "authors": ["A. Author"],
            "status": "candidate",
        }
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT paper_id, ae_corpus_match_status, ae_corpus_match_basis,
               ae_corpus_match_paper_id, ae_corpus_match_confidence,
               ae_corpus_match_candidates_json, ae_corpus_deduped_at
        FROM papers
        WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    con.close()

    assert row["paper_id"] == "doi:10.1234/test"
    assert row["ae_corpus_match_status"] == "matched"
    assert row["ae_corpus_match_basis"] == "exact_title"
    assert row["ae_corpus_match_paper_id"] == "PDF-0009"
    assert row["ae_corpus_match_confidence"] == 0.95
    assert row["ae_corpus_match_candidates_json"] == '["PDF-0009"]'
    assert row["ae_corpus_deduped_at"]
