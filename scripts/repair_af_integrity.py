#!/usr/bin/env python3
"""Repair AF integrity faults in a governed, narrow way."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "article_finder.db"
QUARANTINE_ROOT = REPO_ROOT / "data" / "quarantine" / "integrity_orphans"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingest.pdf_cataloger import extract_pdf_text  # type: ignore  # noqa: E402


def _resolve_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def _normalise(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def _content_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _score_title(title: str, content_title: str) -> float:
    title_n = _normalise(title)
    content_n = _normalise(content_title)
    if not title_n or not content_n:
        return 0.0
    return SequenceMatcher(None, title_n, content_n).ratio()


def _append_note(existing: str | None, note: str) -> str:
    if not existing:
        return note
    if note in existing:
        return existing
    return existing + "\n" + note


def _repair_missing_paths(con: sqlite3.Connection, apply: bool) -> dict[str, int]:
    remapped_output = 0
    cleared_output = 0
    cleared_missing_pdf = 0

    rows = con.execute(
        "SELECT paper_id, pdf_path, ae_output_path, human_notes FROM papers"
    ).fetchall()
    for row in rows:
        paper_id = row["paper_id"]
        note = row["human_notes"]

        pdf_path = _resolve_path(row["pdf_path"])
        if row["pdf_path"] and pdf_path is not None and not pdf_path.exists():
            basename = Path(row["pdf_path"]).name
            candidate = REPO_ROOT / "data" / "pdfs" / basename
            if candidate.exists():
                if apply:
                    con.execute(
                        "UPDATE papers SET pdf_path=?, updated_at=? WHERE paper_id=?",
                        (str(candidate), datetime.now(timezone.utc).isoformat(), paper_id),
                    )
                remapped_output += 0
            else:
                if apply:
                    con.execute(
                        """
                        UPDATE papers
                        SET pdf_path=NULL,
                            pdf_sha256=NULL,
                            pdf_bytes=NULL,
                            human_notes=?,
                            updated_at=?
                        WHERE paper_id=?
                        """,
                        (
                            _append_note(note, "Detached missing pdf_path during AF integrity repair 2026-05-10."),
                            datetime.now(timezone.utc).isoformat(),
                            paper_id,
                        ),
                    )
                cleared_missing_pdf += 1

        ae_output_path = _resolve_path(row["ae_output_path"])
        if row["ae_output_path"] and ae_output_path is not None and not ae_output_path.exists():
            candidate = REPO_ROOT / "data" / "ae_outputs" / Path(row["ae_output_path"]).name
            if candidate.exists():
                if apply:
                    con.execute(
                        "UPDATE papers SET ae_output_path=?, updated_at=? WHERE paper_id=?",
                        (str(candidate), datetime.now(timezone.utc).isoformat(), paper_id),
                    )
                remapped_output += 1
            else:
                if apply:
                    con.execute(
                        """
                        UPDATE papers
                        SET ae_output_path=NULL,
                            human_notes=?,
                            updated_at=?
                        WHERE paper_id=?
                        """,
                        (
                            _append_note(note, "Cleared stale ae_output_path during AF integrity repair 2026-05-10."),
                            datetime.now(timezone.utc).isoformat(),
                            paper_id,
                        ),
                    )
                cleared_output += 1

    return {
        "remapped_output_paths": remapped_output,
        "cleared_output_paths": cleared_output,
        "cleared_missing_pdf_paths": cleared_missing_pdf,
    }


def _repair_duplicate_attachments(con: sqlite3.Connection, apply: bool) -> dict[str, int]:
    groups = con.execute(
        """
        SELECT pdf_sha256
        FROM papers
        WHERE pdf_sha256 IS NOT NULL AND trim(pdf_sha256) != ''
        GROUP BY pdf_sha256
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    detached_rows = 0
    processed_groups = 0

    for group in groups:
        sha = group["pdf_sha256"]
        rows = con.execute(
            "SELECT paper_id, title, pdf_path, human_notes FROM papers WHERE pdf_sha256=? ORDER BY paper_id",
            (sha,),
        ).fetchall()
        if len(rows) < 2:
            continue

        processed_groups += 1
        scored_rows: list[tuple[float, str]] = []
        content_titles: dict[str, str] = {}
        for row in rows:
            pdf_path = _resolve_path(row["pdf_path"])
            if pdf_path is None or not pdf_path.exists():
                scored_rows.append((0.0, row["paper_id"]))
                continue
            text = extract_pdf_text(pdf_path, max_pages=2, max_chars=4000) or ""
            ctitle = _content_title(text)
            content_titles[row["paper_id"]] = ctitle
            scored_rows.append((_score_title(row["title"], ctitle), row["paper_id"]))

        scored_rows.sort(reverse=True)
        best_score, best_id = scored_rows[0]
        second_score = scored_rows[1][0] if len(scored_rows) > 1 else 0.0
        keep_id = best_id if best_score >= 0.45 and (best_score - second_score >= 0.08 or len(rows) == 2) else None

        for row in rows:
            if row["paper_id"] == keep_id:
                continue
            if apply:
                note = _append_note(
                    row["human_notes"],
                    f"Detached conflicting PDF attachment during AF integrity repair 2026-05-10; shared sha256 with group canonical {keep_id or 'none'}.",
                )
                con.execute(
                    """
                    UPDATE papers
                    SET pdf_path=NULL,
                        pdf_sha256=NULL,
                        pdf_bytes=NULL,
                        ae_job_path=NULL,
                        ae_output_path=NULL,
                        ae_run_id=NULL,
                        ae_profile=NULL,
                        ae_status=NULL,
                        ae_n_claims=NULL,
                        ae_n_rules=NULL,
                        ae_confidence=NULL,
                        triage_decision=COALESCE(triage_decision, 'review'),
                        human_notes=?,
                        updated_at=?
                    WHERE paper_id=?
                    """,
                    (note, datetime.now(timezone.utc).isoformat(), row["paper_id"]),
                )
            detached_rows += 1
    return {"duplicate_groups_processed": processed_groups, "detached_duplicate_rows": detached_rows}


def _quarantine_orphans(con: sqlite3.Connection, apply: bool) -> dict[str, int]:
    referenced: set[str] = set()
    for row in con.execute("SELECT pdf_path FROM papers WHERE pdf_path IS NOT NULL AND trim(pdf_path) != ''"):
        p = _resolve_path(row["pdf_path"])
        if p is not None:
            referenced.add(str(p.resolve(strict=False)))

    pdf_dir = REPO_ROOT / "data" / "pdfs"
    moved = 0
    if not pdf_dir.exists():
        return {"orphan_files_quarantined": 0}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_dir = QUARANTINE_ROOT / stamp
    if apply:
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    for path in pdf_dir.glob("*.pdf"):
        if str(path.resolve(strict=False)) in referenced:
            continue
        if apply:
            path.rename(quarantine_dir / path.name)
        moved += 1

    return {"orphan_files_quarantined": moved}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair AF integrity faults.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    apply = not args.dry_run

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        result: dict[str, Any] = {}
        result.update(_repair_missing_paths(con, apply=apply))
        result.update(_repair_duplicate_attachments(con, apply=apply))
        result.update(_quarantine_orphans(con, apply=apply))
        if apply:
            con.commit()
    finally:
        con.close()

    print(json.dumps({"apply": apply, "result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
