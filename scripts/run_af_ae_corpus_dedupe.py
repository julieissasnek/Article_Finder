#!/usr/bin/env python3
"""Deduplicate AF candidate rows against the canonical AE corpus surface."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.database import Database

DEFAULT_AF_DB = REPO_ROOT / "data" / "article_finder.db"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "classification_reports" / "ae_corpus_dedupe"
DEFAULT_AE_REPO = REPO_ROOT.parent / "Article_Eater_PostQuinean_v1_recovery"
DEFAULT_AE_REGISTRY_DB = DEFAULT_AE_REPO / "data" / "pipeline_registry_unified.db"
DEFAULT_AE_LIFECYCLE_DB = DEFAULT_AE_REPO / "data" / "article_eater_lifecycle.db"
DEFAULT_AE_PAPERS_ROOT = DEFAULT_AE_REPO / "data" / "papers"

STATUS_MATCHED = "matched"
STATUS_UNMATCHED = "unmatched"
STATUS_AMBIGUOUS = "ambiguous"

BASIS_EXACT_DOI = "exact_doi"
BASIS_EXACT_TITLE_YEAR = "exact_title_year"
BASIS_EXACT_TITLE = "exact_title"
BASIS_NONE = "none"

TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9\s]")


@dataclass(frozen=True)
class AECorpusRecord:
    paper_id: str
    normalized_title: str
    year: int | None
    doi: str


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    out = str(value).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:", "DOI:"):
        if out.startswith(prefix.lower()):
            out = out[len(prefix):]
    return out.strip().rstrip(").,;]")


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    out = str(value).lower().replace("_", " ").replace("-", " ")
    out = TITLE_NORMALIZE_RE.sub("", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def load_canonical_paper_ids(papers_root: Path) -> set[str]:
    canonical_ids: set[str] = set()
    if not papers_root.exists():
        return canonical_ids
    for meta_path in sorted(papers_root.glob("PDF-*/metadata.json")):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper_id = str(payload.get("paper_id") or meta_path.parent.name).strip()
        if not paper_id:
            continue
        if bool(payload.get("is_canonical")):
            canonical_ids.add(paper_id)
    return canonical_ids


def load_superseded_ids(lifecycle_db: Path) -> set[str]:
    con = sqlite3.connect(lifecycle_db)
    cur = con.cursor()
    cur.execute(
        """
        SELECT superseded_paper_id
        FROM paper_supersessions
        WHERE superseded_paper_id IS NOT NULL AND TRIM(superseded_paper_id) != ''
        """
    )
    rows = {str(row[0]).strip() for row in cur.fetchall() if str(row[0]).strip()}
    con.close()
    return rows


def load_registry_rows(registry_db: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(registry_db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT paper_id, title, year, doi
        FROM papers
        """
    ).fetchall()
    con.close()
    return {str(row["paper_id"]).strip(): dict(row) for row in rows}


def load_lifecycle_title_rows(lifecycle_db: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(lifecycle_db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT paper_id, title_authoritative AS title, publication_year AS year, doi
        FROM paper_metadata
        """
    ).fetchall()
    con.close()
    return {str(row["paper_id"]).strip(): dict(row) for row in rows}


def build_ae_corpus_inventory(
    *,
    registry_db: Path = DEFAULT_AE_REGISTRY_DB,
    lifecycle_db: Path = DEFAULT_AE_LIFECYCLE_DB,
    papers_root: Path = DEFAULT_AE_PAPERS_ROOT,
) -> list[AECorpusRecord]:
    canonical_ids = load_canonical_paper_ids(papers_root)
    superseded_ids = load_superseded_ids(lifecycle_db)
    registry_rows = load_registry_rows(registry_db)
    lifecycle_rows = load_lifecycle_title_rows(lifecycle_db)
    if not canonical_ids:
        canonical_ids = set(registry_rows) - superseded_ids

    records: list[AECorpusRecord] = []
    for paper_id in sorted(canonical_ids):
        registry = registry_rows.get(paper_id, {})
        lifecycle = lifecycle_rows.get(paper_id, {})
        title = str(registry.get("title") or lifecycle.get("title") or "").strip()
        normalized_title = normalize_title(title)
        raw_year = registry.get("year") if registry.get("year") is not None else lifecycle.get("year")
        try:
            year = int(raw_year) if raw_year not in (None, "") else None
        except Exception:
            year = None
        doi = normalize_doi(str(registry.get("doi") or lifecycle.get("doi") or ""))
        records.append(
            AECorpusRecord(
                paper_id=paper_id,
                normalized_title=normalized_title,
                year=year,
                doi=doi,
            )
        )
    return records


def build_indexes(records: list[AECorpusRecord]) -> tuple[dict[str, list[AECorpusRecord]], dict[str, list[AECorpusRecord]]]:
    doi_index: dict[str, list[AECorpusRecord]] = {}
    title_index: dict[str, list[AECorpusRecord]] = {}
    for record in records:
        if record.doi:
            doi_index.setdefault(record.doi, []).append(record)
        if record.normalized_title:
            title_index.setdefault(record.normalized_title, []).append(record)
    return doi_index, title_index


def match_af_row(
    *,
    doi: str,
    title: str,
    year: int | None,
    doi_index: dict[str, list[AECorpusRecord]],
    title_index: dict[str, list[AECorpusRecord]],
) -> dict[str, Any]:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        doi_matches = doi_index.get(normalized_doi, [])
        if len(doi_matches) == 1:
            hit = doi_matches[0]
            return {
                "status": STATUS_MATCHED,
                "basis": BASIS_EXACT_DOI,
                "paper_id": hit.paper_id,
                "confidence": 1.0,
                "candidates": [hit.paper_id],
            }
        if len(doi_matches) > 1:
            return {
                "status": STATUS_AMBIGUOUS,
                "basis": BASIS_EXACT_DOI,
                "paper_id": None,
                "confidence": None,
                "candidates": [item.paper_id for item in doi_matches],
            }

    normalized_title = normalize_title(title)
    title_matches = title_index.get(normalized_title, []) if normalized_title else []
    if title_matches and year is not None:
        exact_year = [item for item in title_matches if item.year == year]
        if len(exact_year) == 1:
            hit = exact_year[0]
            return {
                "status": STATUS_MATCHED,
                "basis": BASIS_EXACT_TITLE_YEAR,
                "paper_id": hit.paper_id,
                "confidence": 0.98,
                "candidates": [hit.paper_id],
            }
        if len(exact_year) > 1:
            return {
                "status": STATUS_AMBIGUOUS,
                "basis": BASIS_EXACT_TITLE_YEAR,
                "paper_id": None,
                "confidence": None,
                "candidates": [item.paper_id for item in exact_year],
            }

    if len(title_matches) == 1:
        hit = title_matches[0]
        return {
            "status": STATUS_MATCHED,
            "basis": BASIS_EXACT_TITLE,
            "paper_id": hit.paper_id,
            "confidence": 0.95,
            "candidates": [hit.paper_id],
        }
    if len(title_matches) > 1:
        return {
            "status": STATUS_AMBIGUOUS,
            "basis": BASIS_EXACT_TITLE,
            "paper_id": None,
            "confidence": None,
            "candidates": [item.paper_id for item in title_matches],
        }
    return {
        "status": STATUS_UNMATCHED,
        "basis": BASIS_NONE,
        "paper_id": None,
        "confidence": None,
        "candidates": [],
    }


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
    inventory = build_ae_corpus_inventory(
        registry_db=registry_db,
        lifecycle_db=lifecycle_db,
        papers_root=papers_root,
    )
    doi_index, title_index = build_indexes(inventory)
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
        "canonical_ae_inventory_count": len(inventory),
        "canonical_ae_title_count": sum(1 for item in inventory if item.normalized_title),
        "canonical_ae_doi_count": sum(1 for item in inventory if item.doi),
    }
    examples: dict[str, list[dict[str, Any]]] = {"matched": [], "unmatched": [], "ambiguous": []}

    for row in rows:
        year = row["year"]
        try:
            norm_year = int(year) if year not in (None, "") else None
        except Exception:
            norm_year = None
        match = match_af_row(
            doi=str(row["doi"] or ""),
            title=str(row["title"] or ""),
            year=norm_year,
            doi_index=doi_index,
            title_index=title_index,
        )
        deduped_at = utc_now_iso()
        candidates_json = json.dumps(match["candidates"], ensure_ascii=False, sort_keys=True)
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
                match["status"],
                match["basis"],
                match["paper_id"],
                match["confidence"],
                candidates_json,
                deduped_at,
                deduped_at,
                row["paper_id"],
            ),
        )
        stats[match["status"]] += 1
        if match["status"] == STATUS_MATCHED:
            stats[f"matched_{match['basis']}"] += 1
        triage = str(row["triage_decision"] or "")
        has_pdf = bool(str(row["pdf_path"] or "").strip())
        atlas_type = str(row["atlas_article_type"] or "")
        if triage == "send_to_eater":
            if match["status"] == STATUS_MATCHED:
                stats["send_to_eater_matched"] += 1
            else:
                stats["send_to_eater_unmatched"] += 1
            if not has_pdf:
                if match["status"] == STATUS_MATCHED:
                    stats["send_to_eater_without_pdf_matched"] += 1
                else:
                    stats["send_to_eater_without_pdf_unmatched"] += 1
                    if atlas_type == "empirical_research":
                        stats["send_to_eater_without_pdf_empirical_unmatched"] += 1
        bucket = match["status"]
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
                    "match_basis": match["basis"],
                    "matched_paper_id": match["paper_id"],
                    "candidate_paper_ids": match["candidates"],
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
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload["report_path"] = str(report_path)
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
