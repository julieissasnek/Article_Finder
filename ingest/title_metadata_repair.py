# Version: 3.2.2
"""
Title-based bibliographic metadata repair.

This module exists for the gap where we have a paper title but do not yet have a
DOI, abstract, or stable bibliographic metadata. It uses the existing AF API
clients, adds a lightweight result cache, and picks the best candidate by
scoring title/year/author agreement.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.loader import get
from ingest.doi_resolver import APICache, DOIResolver
from search.bibliographer import SemanticScholarSearcher

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2
    }


def _clean_abstract(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", str(text))
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_author(author: Any) -> str:
    if isinstance(author, str):
        return author.strip()
    if isinstance(author, dict):
        return str(
            author.get("name")
            or author.get("display_name")
            or " ".join(str(author.get(k, "")).strip() for k in ("given", "family")).strip()
        ).strip()
    return str(author or "").strip()


class TitleMetadataRepairClient:
    """Find best bibliographic metadata for a title-only record."""

    def __init__(
        self,
        email: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        resolver: Optional[DOIResolver] = None,
        use_semantic_scholar: bool = True,
    ):
        self.email = email or get("apis.openalex.email") or get("apis.crossref.email")
        self.resolver = resolver or DOIResolver(email=self.email)
        self.cache = APICache(cache_dir or Path("data/cache/title_metadata_repair"), ttl_days=30)
        self.s2 = None
        if use_semantic_scholar:
            self.s2 = SemanticScholarSearcher(api_key=get("apis.semantic_scholar.api_key"))

    def lookup(
        self,
        title: str,
        author: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 5,
    ) -> Optional[Dict[str, Any]]:
        title = (title or "").strip()
        if not title:
            return None

        normalized_author = _normalize_author(author)
        cache_key = f"title={title.lower()}|author={normalized_author.lower()}|year={year or ''}|limit={limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        candidates: List[Dict[str, Any]] = []
        try:
            candidates.extend(self.resolver.search_by_bibliographic(title=title, author=normalized_author or None, year=year, limit=limit))
        except Exception as exc:
            logger.warning("Bibliographic title lookup failed for %s: %s", title[:80], exc)

        if self.s2 is not None:
            try:
                s2_results = self.s2.search(title, limit=limit)
                candidates.extend(s2_results)
            except Exception as exc:
                logger.warning("Semantic Scholar title lookup failed for %s: %s", title[:80], exc)

        best = self.best_match(title=title, author=normalized_author or None, year=year, candidates=candidates)
        self.cache.set(cache_key, best)
        return best

    def best_match(
        self,
        title: str,
        author: Optional[str],
        year: Optional[int],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        title_tokens = _tokenize(title)
        if not title_tokens:
            return None

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for candidate in candidates:
            candidate_title = candidate.get("title") or ""
            candidate_tokens = _tokenize(candidate_title)
            if not candidate_tokens:
                continue

            overlap = len(title_tokens & candidate_tokens)
            union = len(title_tokens | candidate_tokens) or 1
            score = overlap / union

            if year and candidate.get("year"):
                if int(candidate["year"]) == int(year):
                    score += 0.2
                elif abs(int(candidate["year"]) - int(year)) <= 1:
                    score += 0.05
                else:
                    score -= 0.15

            if author:
                author_l = author.lower()
                joined_authors = " ".join(candidate.get("authors") or []).lower()
                if author_l and author_l in joined_authors:
                    score += 0.1

            if candidate.get("abstract"):
                score += 0.08
            if candidate.get("doi"):
                score += 0.05

            if score > best_score:
                best_score = score
                best = dict(candidate)

        if not best or best_score < 0.35:
            return None

        best["abstract"] = _clean_abstract(best.get("abstract"))
        best["match_score"] = round(best_score, 3)

        doi = best.get("doi")
        if doi:
            try:
                resolved = self.resolver.resolve(doi)
            except Exception:
                resolved = None
            if resolved:
                merged = dict(best)
                for key, value in resolved.items():
                    if value and not merged.get(key):
                        merged[key] = value
                merged["abstract"] = _clean_abstract(merged.get("abstract"))
                merged["match_score"] = best["match_score"]
                best = merged

        return best
