#!/usr/bin/env python3
"""
Production run gates for Article Finder.
Non-destructive: reads the DB, computes coverage, and flags reject candidates
that must be reviewed before pruning.
"""

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path


def normalize_venue(value: str) -> str:
    if not value:
        return ""
    value = value.lower().strip()
    value = value.replace("&", "and")
    value = re.sub(r"\s+", " ", value)
    return value


def load_allowlist(path: Path) -> set:
    if not path:
        return set()
    allowlist = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        allowlist.add(normalize_venue(line))
    return allowlist


def get_paper_columns(cursor) -> set:
    return {row[1] for row in cursor.execute("PRAGMA table_info(papers)")}


def get_citation_column(columns: set) -> str:
    for candidate in ("cited_by_count", "citation_count"):
        if candidate in columns:
            return candidate
    return ""


def fetch_local_citations(cursor) -> dict:
    cursor.execute(
        "SELECT cited_paper_id, COUNT(*) FROM citations "
        "WHERE cited_paper_id IS NOT NULL GROUP BY cited_paper_id"
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def coverage_fraction(count: int, total: int) -> float:
    return count / total if total else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Production run gates (non-destructive)")
    parser.add_argument("--db", default="data/article_finder.db", help="Path to Article Finder DB")
    parser.add_argument("--hbe-allowlist", default="config/hbe_journals_allowlist.txt",
                        help="HBE journal allowlist path")
    parser.add_argument("--neuro-allowlist", default="config/neuroscience_venues_allowlist.txt",
                        help="Neuroscience venues allowlist path")
    parser.add_argument("--high-cite-threshold", type=int, default=150,
                        help="High-citation threshold for extra caution")
    parser.add_argument("--min-abstract-coverage", type=float, default=0.70)
    parser.add_argument("--min-pdf-coverage", type=float, default=0.60)
    parser.add_argument("--min-venue-coverage", type=float, default=0.50)
    parser.add_argument("--export", help="Optional CSV path for reject candidates")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    columns = get_paper_columns(cur)
    citation_column = get_citation_column(columns)
    local_citations = {}
    citation_mode = "global" if citation_column else "local"
    if not citation_column:
        local_citations = fetch_local_citations(cur)

    hbe_allowlist = load_allowlist(Path(args.hbe_allowlist))
    neuro_allowlist = load_allowlist(Path(args.neuro_allowlist))

    cur.execute("SELECT COUNT(*) FROM papers")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND abstract != ''")
    with_abstract = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''")
    with_pdf = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM papers WHERE venue IS NOT NULL AND venue != ''")
    with_venue = cur.fetchone()[0]

    print("=== Production Gates ===")
    print(f"DB: {db_path}")
    print(f"Total papers: {total}")
    print(f"Abstract coverage: {with_abstract}/{total} ({coverage_fraction(with_abstract, total):.0%})")
    print(f"PDF coverage: {with_pdf}/{total} ({coverage_fraction(with_pdf, total):.0%})")
    print(f"Venue coverage: {with_venue}/{total} ({coverage_fraction(with_venue, total):.0%})")
    print(f"Citation mode: {citation_mode}")

    failures = []
    if coverage_fraction(with_abstract, total) < args.min_abstract_coverage:
        failures.append("abstract_coverage")
    if coverage_fraction(with_pdf, total) < args.min_pdf_coverage:
        failures.append("pdf_coverage")
    if coverage_fraction(with_venue, total) < args.min_venue_coverage:
        failures.append("venue_coverage")

    select_parts = [
        "paper_id", "title", "venue", "topic_decision", "triage_decision",
        "topic_score", "triage_score", "abstract", "pdf_path"
    ]
    if citation_column:
        select_parts.append(citation_column + " AS citation_count")
    query = "SELECT " + ", ".join(select_parts) + " FROM papers"
    cur.execute(query)
    rows = cur.fetchall()

    reject_candidates = []
    protected = []
    high_cite_rejects = []

    for row in rows:
        topic_decision = (row["topic_decision"] or "").lower()
        triage_decision = (row["triage_decision"] or "").lower()
        candidate = topic_decision == "off_topic" or triage_decision == "reject"
        if not candidate:
            continue

        venue = row["venue"] or ""
        venue_norm = normalize_venue(venue)
        protected_reasons = []

        if venue_norm in hbe_allowlist:
            protected_reasons.append("hbe_allowlist")
        if venue_norm in neuro_allowlist or re.search(r"\bneuro|\bbrain", venue_norm):
            protected_reasons.append("neuroscience")

        citation_count = 0
        if citation_column:
            citation_count = row["citation_count"] or 0
        else:
            citation_count = local_citations.get(row["paper_id"], 0)

        if citation_count >= args.high_cite_threshold:
            protected_reasons.append(f"high_citation>={args.high_cite_threshold}")

        record = {
            "paper_id": row["paper_id"],
            "title": row["title"],
            "venue": venue,
            "topic_decision": topic_decision,
            "triage_decision": triage_decision,
            "topic_score": row["topic_score"],
            "triage_score": row["triage_score"],
            "citation_count": citation_count,
            "protected_reasons": ";".join(protected_reasons),
        }

        reject_candidates.append(record)
        if protected_reasons:
            protected.append(record)
        if any(r.startswith("high_citation") for r in protected_reasons):
            high_cite_rejects.append(record)

    print(f"Reject candidates: {len(reject_candidates)}")
    print(f"Protected rejects (allowlist/neuro/high-cite): {len(protected)}")
    print(f"High-citation rejects: {len(high_cite_rejects)}")

    if high_cite_rejects:
        failures.append("high_citation_rejects")

    if args.export and reject_candidates:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        with export_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(reject_candidates[0].keys()))
            writer.writeheader()
            writer.writerows(reject_candidates)
        print(f"Exported reject candidates to {export_path}")
    if failures:
        print("\nGate failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nAll gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
