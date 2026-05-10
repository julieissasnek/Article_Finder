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


SCHEMA_MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(
        version=3,
        description="Add papers.pdf_source for PDF provenance tracking",
        apply=_migration_add_pdf_source,
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
