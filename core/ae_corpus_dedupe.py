from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AE_REPO = ROOT.parent / "Article_Eater_PostQuinean_v1_recovery"
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


def _canonical_paper_ids(papers_root: Path) -> set[str]:
    canonical_ids: set[str] = set()
    if not papers_root.exists():
        return canonical_ids
    for meta_path in sorted(papers_root.glob("PDF-*/metadata.json")):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper_id = str(payload.get("paper_id") or meta_path.parent.name).strip()
        if paper_id and bool(payload.get("is_canonical")):
            canonical_ids.add(paper_id)
    return canonical_ids


def _superseded_ids(lifecycle_db: Path) -> set[str]:
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


def _registry_rows(registry_db: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(registry_db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT paper_id, title, year, doi FROM papers").fetchall()
    con.close()
    return {str(row["paper_id"]).strip(): dict(row) for row in rows}


def _lifecycle_title_rows(lifecycle_db: Path) -> dict[str, dict[str, Any]]:
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


def _cache_key(registry_db: Path, lifecycle_db: Path, papers_root: Path) -> tuple[str, str, str, int, int, int]:
    return (
        str(registry_db),
        str(lifecycle_db),
        str(papers_root),
        int(registry_db.stat().st_mtime_ns) if registry_db.exists() else 0,
        int(lifecycle_db.stat().st_mtime_ns) if lifecycle_db.exists() else 0,
        int(papers_root.stat().st_mtime_ns) if papers_root.exists() else 0,
    )


@lru_cache(maxsize=4)
def _cached_inventory(
    registry_db_str: str,
    lifecycle_db_str: str,
    papers_root_str: str,
    _registry_mtime_ns: int,
    _lifecycle_mtime_ns: int,
    _papers_root_mtime_ns: int,
) -> tuple[dict[str, tuple[AECorpusRecord, ...]], dict[str, tuple[AECorpusRecord, ...]]]:
    registry_db = Path(registry_db_str)
    lifecycle_db = Path(lifecycle_db_str)
    papers_root = Path(papers_root_str)
    canonical_ids = _canonical_paper_ids(papers_root)
    superseded_ids = _superseded_ids(lifecycle_db)
    registry = _registry_rows(registry_db)
    lifecycle = _lifecycle_title_rows(lifecycle_db)
    if not canonical_ids:
        canonical_ids = set(registry) - superseded_ids

    records: list[AECorpusRecord] = []
    for paper_id in sorted(canonical_ids):
        reg = registry.get(paper_id, {})
        life = lifecycle.get(paper_id, {})
        title = str(reg.get("title") or life.get("title") or "").strip()
        normalized_title = normalize_title(title)
        raw_year = reg.get("year") if reg.get("year") is not None else life.get("year")
        try:
            year = int(raw_year) if raw_year not in (None, "") else None
        except Exception:
            year = None
        doi = normalize_doi(str(reg.get("doi") or life.get("doi") or ""))
        records.append(AECorpusRecord(paper_id=paper_id, normalized_title=normalized_title, year=year, doi=doi))

    doi_index: dict[str, list[AECorpusRecord]] = {}
    title_index: dict[str, list[AECorpusRecord]] = {}
    for record in records:
        if record.doi:
            doi_index.setdefault(record.doi, []).append(record)
        if record.normalized_title:
            title_index.setdefault(record.normalized_title, []).append(record)
    return (
        {k: tuple(v) for k, v in doi_index.items()},
        {k: tuple(v) for k, v in title_index.items()},
    )


def _inventory_indexes(
    *,
    registry_db: Path = DEFAULT_AE_REGISTRY_DB,
    lifecycle_db: Path = DEFAULT_AE_LIFECYCLE_DB,
    papers_root: Path = DEFAULT_AE_PAPERS_ROOT,
) -> tuple[dict[str, tuple[AECorpusRecord, ...]], dict[str, tuple[AECorpusRecord, ...]]]:
    return _cached_inventory(*_cache_key(registry_db, lifecycle_db, papers_root))


def match_against_ae_corpus(
    *,
    doi: str | None,
    title: str | None,
    year: int | None,
    registry_db: Path = DEFAULT_AE_REGISTRY_DB,
    lifecycle_db: Path = DEFAULT_AE_LIFECYCLE_DB,
    papers_root: Path = DEFAULT_AE_PAPERS_ROOT,
) -> dict[str, Any]:
    doi_index, title_index = _inventory_indexes(
        registry_db=registry_db,
        lifecycle_db=lifecycle_db,
        papers_root=papers_root,
    )

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        doi_matches = list(doi_index.get(normalized_doi, ()))
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
    title_matches = list(title_index.get(normalized_title, ())) if normalized_title else []
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


def build_paper_dedupe_fields(
    paper: Mapping[str, Any],
    *,
    registry_db: Path = DEFAULT_AE_REGISTRY_DB,
    lifecycle_db: Path = DEFAULT_AE_LIFECYCLE_DB,
    papers_root: Path = DEFAULT_AE_PAPERS_ROOT,
    deduped_at: str,
) -> dict[str, Any]:
    raw_year = paper.get("year")
    try:
        year = int(raw_year) if raw_year not in (None, "") else None
    except Exception:
        year = None
    match = match_against_ae_corpus(
        doi=paper.get("doi"),
        title=paper.get("title"),
        year=year,
        registry_db=registry_db,
        lifecycle_db=lifecycle_db,
        papers_root=papers_root,
    )
    return {
        "ae_corpus_match_status": match["status"],
        "ae_corpus_match_basis": match["basis"],
        "ae_corpus_match_paper_id": match["paper_id"],
        "ae_corpus_match_confidence": match["confidence"],
        "ae_corpus_match_candidates_json": json.dumps(match["candidates"], ensure_ascii=False, sort_keys=True),
        "ae_corpus_deduped_at": deduped_at,
    }
