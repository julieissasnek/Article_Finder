#!/usr/bin/env python3
"""Deduplicate AF candidate rows against the canonical AE corpus surface."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.ae_corpus_dedupe import (
    DEFAULT_AE_LIFECYCLE_DB,
    DEFAULT_AE_PAPERS_ROOT,
    DEFAULT_AE_REGISTRY_DB,
    STATUS_MATCHED,
    build_paper_dedupe_fields,
)
from core.database import Database


DEFAULT_AF_DB = REPO_ROOT / "data" / "article_finder.db"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "classification_reports" / "ae_corpus_dedupe"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def run_dedupe(
    *,
    af_db: Path = DEFAULT_AF_DB,
    registry_db: Path = DEFAULT_AE_REGISTRY_DB,
    lifecycle_db: Path = DEFAULT_AE_LIFECYCLE_DB,
    papers_root: Path = DEFAULT_AE_PAPERS_ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
    limit: int | None = None,
) -> dict[str, Any]:
    Database(af_db)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"ae_corpus_dedupe_{stamp}.json"

    con = sqlite3.connect(af_db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    query = """
        SELECT paper_id, doi, title, year, triage_decision, pdf_path, atlas_article_type, atlas_primary_topic
        FROM papers
        ORDER BY updated_at ASC, created_at ASC
    """
    params: list[Any] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = list(cur.execute(query, params).fetchall())

    stats = {
        "selected": len(rows),
        "matched": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "matched_exact_doi": 0,
        "matched_exact_title_year": 0,
        "matched_exact_title": 0,
        "send_to_eater_matched": 0,
        "send_to_eater_unmatched": 0,
        "send_to_eater_without_pdf_matched": 0,
        "send_to_eater_without_pdf_unmatched": 0,
        "send_to_eater_without_pdf_empirical_unmatched": 0,
        "canonical_ae_inventory_count": 0,
        "canonical_ae_title_count": 0,
        "canonical_ae_doi_count": 0,
    }
    examples: dict[str, list[dict[str, Any]]] = {"matched": [], "unmatched": [], "ambiguous": []}

    first_record = True
    for row in rows:
        deduped_at = utc_now_iso()
        fields = build_paper_dedupe_fields(
            dict(row),
            registry_db=registry_db,
            lifecycle_db=lifecycle_db,
            papers_root=papers_root,
            deduped_at=deduped_at,
        )
        if first_record:
            # force-load cache statistics only once from helper internals by reading the indexes indirectly
            from core.ae_corpus_dedupe import _inventory_indexes  # local import to avoid exporting internals

            doi_index, title_index = _inventory_indexes(
                registry_db=registry_db,
                lifecycle_db=lifecycle_db,
                papers_root=papers_root,
            )
            seen_ids = {item.paper_id for records in title_index.values() for item in records}
            stats["canonical_ae_inventory_count"] = len(seen_ids)
            stats["canonical_ae_title_count"] = len({k for k in title_index})
            stats["canonical_ae_doi_count"] = len({k for k in doi_index})
            first_record = False

        cur.execute(
            """
            UPDATE papers
            SET ae_corpus_match_status = ?,
                ae_corpus_match_basis = ?,
                ae_corpus_match_paper_id = ?,
                ae_corpus_match_confidence = ?,
                ae_corpus_match_candidates_json = ?,
                ae_corpus_deduped_at = ?,
                updated_at = ?
            WHERE paper_id = ?
            """,
            (
                fields["ae_corpus_match_status"],
                fields["ae_corpus_match_basis"],
                fields["ae_corpus_match_paper_id"],
                fields["ae_corpus_match_confidence"],
                fields["ae_corpus_match_candidates_json"],
                fields["ae_corpus_deduped_at"],
                deduped_at,
                row["paper_id"],
            ),
        )

        status = fields["ae_corpus_match_status"]
        basis = fields["ae_corpus_match_basis"]
        stats[status] += 1
        if status == STATUS_MATCHED:
            stats[f"matched_{basis}"] += 1

        triage = str(row["triage_decision"] or "")
        has_pdf = bool(str(row["pdf_path"] or "").strip())
        atlas_type = str(row["atlas_article_type"] or "")
        if triage == "send_to_eater":
            if status == STATUS_MATCHED:
                stats["send_to_eater_matched"] += 1
            else:
                stats["send_to_eater_unmatched"] += 1
            if not has_pdf:
                if status == STATUS_MATCHED:
                    stats["send_to_eater_without_pdf_matched"] += 1
                else:
                    stats["send_to_eater_without_pdf_unmatched"] += 1
                    if atlas_type == "empirical_research":
                        stats["send_to_eater_without_pdf_empirical_unmatched"] += 1

        bucket = status
        candidates = json.loads(fields["ae_corpus_match_candidates_json"])
        if len(examples[bucket]) < 10:
            examples[bucket].append(
                {
                    "paper_id": row["paper_id"],
                    "doi": row["doi"],
                    "title": row["title"],
                    "year": row["year"],
                    "triage_decision": triage,
                    "atlas_article_type": atlas_type,
                    "atlas_primary_topic": row["atlas_primary_topic"],
                    "match_basis": basis,
                    "matched_paper_id": fields["ae_corpus_match_paper_id"],
                    "candidate_paper_ids": candidates,
                }
            )

    con.commit()
    con.close()

    payload = {
        "generated_at": utc_now_iso(),
        "af_db": str(af_db),
        "ae_registry_db": str(registry_db),
        "ae_lifecycle_db": str(lifecycle_db),
        "ae_papers_root": str(papers_root),
        "stats": stats,
        "examples": examples,
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--af-db", type=Path, default=DEFAULT_AF_DB)
    parser.add_argument("--ae-registry-db", type=Path, default=DEFAULT_AE_REGISTRY_DB)
    parser.add_argument("--ae-lifecycle-db", type=Path, default=DEFAULT_AE_LIFECYCLE_DB)
    parser.add_argument("--ae-papers-root", type=Path, default=DEFAULT_AE_PAPERS_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    payload = run_dedupe(
        af_db=args.af_db,
        registry_db=args.ae_registry_db,
        lifecycle_db=args.ae_lifecycle_db,
        papers_root=args.ae_papers_root,
        report_dir=args.report_dir,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
