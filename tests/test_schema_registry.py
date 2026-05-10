from __future__ import annotations

import sqlite3
from pathlib import Path

from core.database import Database, get_schema_sql
from scripts.verify_af_schema_governance import gather_metrics


def test_database_init_applies_registered_schema_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    Database(db_path)

    con = sqlite3.connect(db_path)
    versions = [row[0] for row in con.execute("SELECT version FROM schema_version ORDER BY version")]
    columns = {row[1] for row in con.execute("PRAGMA table_info(papers)")}
    con.close()

    assert versions == [1, 2, 3]
    assert "pdf_source" in columns


def test_schema_governance_verifier_detects_legacy_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "article_finder.db"
    con = sqlite3.connect(db_path)
    con.executescript(get_schema_sql())
    con.close()

    metrics = gather_metrics(db_path)

    assert metrics["schema_version_max"] == 2
    assert metrics["expected_schema_version_max"] == 3
    assert metrics["missing_migration_versions"] == [3]
    assert metrics["papers_has_pdf_source"] is False
