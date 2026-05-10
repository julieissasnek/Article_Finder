#!/usr/bin/env python3
"""Verify AF schema governance and migration state."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.schema_registry import iter_schema_migrations, latest_schema_version

DB_PATH = REPO_ROOT / "data" / "article_finder.db"


def gather_metrics(db_path: Path = DB_PATH) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    schema_versions = sorted(
        row[0] for row in con.execute("SELECT version FROM schema_version").fetchall()
    )
    columns = {
        row[1] for row in con.execute("PRAGMA table_info(papers)").fetchall()
    }
    expected_versions = [migration.version for migration in iter_schema_migrations()]
    missing_versions = [version for version in expected_versions if version not in schema_versions]
    metrics = {
        "schema_version_rows": len(schema_versions),
        "schema_version_max": max(schema_versions) if schema_versions else 0,
        "expected_schema_version_max": latest_schema_version(),
        "missing_migration_versions": missing_versions,
        "papers_has_pdf_source": "pdf_source" in columns,
        "papers_has_topic_category": "topic_category" in columns,
        "papers_has_ae_corpus_match_status": "ae_corpus_match_status" in columns,
        "papers_has_ae_corpus_deduped_at": "ae_corpus_deduped_at" in columns,
    }
    con.close()
    return metrics


def main() -> int:
    metrics = gather_metrics()
    failures = []
    if metrics["schema_version_max"] < metrics["expected_schema_version_max"]:
        failures.append("schema_version_max")
    if metrics["missing_migration_versions"]:
        failures.append("missing_migration_versions")
    if not metrics["papers_has_pdf_source"]:
        failures.append("papers_has_pdf_source")
    if not metrics["papers_has_topic_category"]:
        failures.append("papers_has_topic_category")
    if not metrics["papers_has_ae_corpus_match_status"]:
        failures.append("papers_has_ae_corpus_match_status")
    if not metrics["papers_has_ae_corpus_deduped_at"]:
        failures.append("papers_has_ae_corpus_deduped_at")
    payload = {
        "status": "ok" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
