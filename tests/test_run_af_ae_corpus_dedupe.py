from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.database import Database
from scripts.run_af_ae_corpus_dedupe import run_dedupe


def _init_ae_registry_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE papers (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER,
            doi TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO papers (paper_id, title, year, doi) VALUES (?, ?, ?, ?)",
        [
            ("PDF-0001", "Daylight and alertness", 2020, ""),
            ("PDF-0002", "Thermal comfort and stress", 2019, "10.1234/abc"),
        ],
    )
    con.commit()
    con.close()


def _init_ae_lifecycle_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE paper_supersessions (
            superseded_paper_id TEXT,
            canonical_paper_id TEXT,
            identity_kind TEXT,
            identity_value TEXT,
            rationale TEXT,
            superseded_at TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE paper_metadata (
            paper_id TEXT PRIMARY KEY,
            doi TEXT,
            title_authoritative TEXT,
            abstract_authoritative TEXT,
            authors_json TEXT,
            publication_year INTEGER,
            journal_or_venue TEXT,
            references_count INTEGER,
            cited_by_count INTEGER,
            fields_of_study_json TEXT,
            openalex_id TEXT,
            semantic_scholar_id TEXT,
            crossref_verified INTEGER,
            primary_source TEXT,
            fetched_at TEXT,
            raw_response_json TEXT,
            zotero_item_key TEXT,
            zotero_library_id TEXT,
            zotero_synced_at TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO paper_metadata (paper_id, doi, title_authoritative, publication_year) VALUES (?, ?, ?, ?)",
        [
            ("PDF-0001", "", "Daylight and alertness", 2020),
            ("PDF-0002", "", "Thermal comfort and stress", 2019),
        ],
    )
    con.commit()
    con.close()


def _init_ae_papers_root(root: Path) -> None:
    for paper_id in ("PDF-0001", "PDF-0002"):
        paper_dir = root / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "metadata.json").write_text(
            json.dumps({"paper_id": paper_id, "is_canonical": True}) + "\n",
            encoding="utf-8",
        )


def test_run_dedupe_matches_doi_and_title_year(tmp_path: Path) -> None:
    af_db = tmp_path / "article_finder.db"
    Database(af_db)
    con = sqlite3.connect(af_db)
    con.executemany(
        """
        INSERT INTO papers (
            paper_id, doi, title, year, status, triage_decision, atlas_article_type,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'candidate', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        [
            ("af-1", "10.1234/abc", "Thermal comfort and stress", 2019, "send_to_eater", "empirical_research"),
            ("af-2", "", "Daylight and alertness", 2020, "review", "theoretical"),
            ("af-3", "10.9999/miss", "Unmatched paper", 2022, "send_to_eater", "empirical_research"),
        ],
    )
    con.commit()
    con.close()

    registry_db = tmp_path / "ae_registry.db"
    lifecycle_db = tmp_path / "ae_lifecycle.db"
    papers_root = tmp_path / "ae_papers"
    _init_ae_registry_db(registry_db)
    _init_ae_lifecycle_db(lifecycle_db)
    _init_ae_papers_root(papers_root)

    report_dir = tmp_path / "reports"
    payload = run_dedupe(
        af_db=af_db,
        registry_db=registry_db,
        lifecycle_db=lifecycle_db,
        papers_root=papers_root,
        report_dir=report_dir,
    )

    assert payload["stats"]["matched"] == 2
    assert payload["stats"]["matched_exact_doi"] == 1
    assert payload["stats"]["matched_exact_title_year"] == 1
    assert payload["stats"]["unmatched"] == 1
    assert payload["stats"]["send_to_eater_without_pdf_unmatched"] == 1
    assert payload["stats"]["send_to_eater_without_pdf_empirical_unmatched"] == 1

    con = sqlite3.connect(af_db)
    con.row_factory = sqlite3.Row
    by_id = {
        row["paper_id"]: row
        for row in con.execute(
            """
            SELECT paper_id, ae_corpus_match_status, ae_corpus_match_basis,
                   ae_corpus_match_paper_id, ae_corpus_match_candidates_json
            FROM papers
            ORDER BY paper_id
            """
        ).fetchall()
    }
    con.close()

    assert by_id["af-1"]["ae_corpus_match_status"] == "matched"
    assert by_id["af-1"]["ae_corpus_match_basis"] == "exact_doi"
    assert by_id["af-1"]["ae_corpus_match_paper_id"] == "PDF-0002"

    assert by_id["af-2"]["ae_corpus_match_status"] == "matched"
    assert by_id["af-2"]["ae_corpus_match_basis"] == "exact_title_year"
    assert by_id["af-2"]["ae_corpus_match_paper_id"] == "PDF-0001"

    assert by_id["af-3"]["ae_corpus_match_status"] == "unmatched"
    assert by_id["af-3"]["ae_corpus_match_basis"] == "none"
    assert by_id["af-3"]["ae_corpus_match_paper_id"] is None
    assert json.loads(by_id["af-3"]["ae_corpus_match_candidates_json"]) == []
