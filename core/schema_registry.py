from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column_name: str, ddl_fragment: str
) -> None:
    if column_name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl_fragment}")


def _migration_add_pdf_source(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "papers", "pdf_source", "pdf_source TEXT")


def _migration_add_atlas_shared_classification_fields(conn: sqlite3.Connection) -> None:
    for column_name, ddl_fragment in (
        ("atlas_constitution_version", "atlas_constitution_version TEXT"),
        ("atlas_constitution_source", "atlas_constitution_source TEXT"),
        ("atlas_article_type", "atlas_article_type TEXT"),
        ("atlas_article_type_confidence", "atlas_article_type_confidence REAL"),
        ("atlas_article_type_source", "atlas_article_type_source TEXT"),
        ("atlas_evidence_stage", "atlas_evidence_stage TEXT"),
        ("atlas_overall_confidence", "atlas_overall_confidence REAL"),
        ("atlas_intake_decision", "atlas_intake_decision TEXT"),
        ("atlas_routing_target", "atlas_routing_target TEXT"),
        ("atlas_domain_relevance", "atlas_domain_relevance TEXT"),
        ("atlas_primary_topic", "atlas_primary_topic TEXT"),
        ("atlas_primary_bundle_id", "atlas_primary_bundle_id TEXT"),
        ("atlas_topic_candidates", "atlas_topic_candidates TEXT"),
        ("atlas_matched_question_ids", "atlas_matched_question_ids TEXT"),
        ("atlas_edge_case_kind", "atlas_edge_case_kind TEXT"),
        ("atlas_novelty_signal", "atlas_novelty_signal REAL"),
        ("atlas_topic_expansion_candidate", "atlas_topic_expansion_candidate INTEGER DEFAULT 0"),
        ("atlas_new_topic_candidate", "atlas_new_topic_candidate INTEGER DEFAULT 0"),
        ("atlas_proposed_topic_label", "atlas_proposed_topic_label TEXT"),
        ("atlas_adjacent_topics", "atlas_adjacent_topics TEXT"),
        ("atlas_analysis_steps_run", "atlas_analysis_steps_run TEXT"),
        ("atlas_next_action", "atlas_next_action TEXT"),
        ("atlas_needs_more_evidence", "atlas_needs_more_evidence INTEGER DEFAULT 0"),
        ("atlas_classification_payload_json", "atlas_classification_payload_json TEXT"),
        ("atlas_classified_at", "atlas_classified_at TEXT"),
    ):
        _add_column_if_missing(conn, "papers", column_name, ddl_fragment)


def _migration_add_topic_category(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "papers", "topic_category", "topic_category TEXT")


SCHEMA_MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(
        version=3,
        description="Add papers.pdf_source for PDF provenance tracking",
        apply=_migration_add_pdf_source,
    ),
    SchemaMigration(
        version=4,
        description="Add Atlas Shared pre-extraction classification fields to papers",
        apply=_migration_add_atlas_shared_classification_fields,
    ),
    SchemaMigration(
        version=5,
        description="Formalize papers.topic_category in migration registry",
        apply=_migration_add_topic_category,
    ),
)


def latest_schema_version() -> int:
    if not SCHEMA_MIGRATIONS:
        return 0
    return max(m.version for m in SCHEMA_MIGRATIONS)


def iter_schema_migrations() -> Iterable[SchemaMigration]:
    return SCHEMA_MIGRATIONS


def apply_pending_schema_migrations(conn: sqlite3.Connection) -> list[int]:
    applied_versions = {
        row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()
    }
    applied: list[int] = []
    for migration in sorted(SCHEMA_MIGRATIONS, key=lambda item: item.version):
        if migration.version in applied_versions:
            continue
        migration.apply(conn)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, description) VALUES (?, ?)",
            (migration.version, migration.description),
        )
        applied.append(migration.version)
    return applied
