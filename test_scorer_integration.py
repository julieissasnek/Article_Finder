#!/usr/bin/env python3
"""
Test script for Taxonomy Scorer Integration Fix

This script tests:
1. Papers get deferred (not rejected) when scorer is unavailable
2. Building centroids auto-triggers scoring of deferred papers
3. Deferred papers get properly scored and promoted/rejected

Run this script and share the output with Claude to verify correctness.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import Database
from search.bibliographer import Bibliographer
from triage.taxonomy_loader import CentroidBuilder, TaxonomyLoader
from triage.scorer import HierarchicalScorer


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def get_status_counts(db):
    """Get paper counts by status."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM papers GROUP BY status"
        ).fetchall()
        return {row['status']: row['count'] for row in rows}


def get_sample_papers(db, status, limit=3):
    """Get sample papers with given status."""
    papers = db.get_papers_by_status(status)
    return papers[:limit] if papers else []


def main():
    print_section("TAXONOMY SCORER INTEGRATION TEST")
    print(f"Started: {datetime.now().isoformat()}")

    db_path = Path('data/article_finder.db')

    if not db_path.exists():
        print(f"\nERROR: Database not found at {db_path}")
        print("Please run the system first to create a database.")
        return 1

    db = Database(db_path)

    # =========================================================================
    # STEP 1: Check current state
    # =========================================================================
    print_section("STEP 1: Current Database State")

    status_counts = get_status_counts(db)
    print("\nPaper counts by status:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    total_papers = sum(status_counts.values())
    print(f"\nTotal papers: {total_papers}")

    # Check for deferred papers
    pending_scorer = status_counts.get('pending_scorer', 0)
    print(f"\nPapers pending scorer: {pending_scorer}")

    if pending_scorer > 0:
        print("\nSample pending_scorer papers:")
        for paper in get_sample_papers(db, 'pending_scorer'):
            print(f"  - {paper.get('title', 'No title')[:60]}...")
            print(f"    DOI: {paper.get('doi', 'N/A')}")
            print(f"    triage_score: {paper.get('triage_score')}")

    # =========================================================================
    # STEP 2: Check centroid state
    # =========================================================================
    print_section("STEP 2: Centroid State")

    builder = CentroidBuilder(db)
    centroids = builder.get_all_centroids()
    print(f"\nCentroids in database: {len(centroids)}")

    if len(centroids) > 0:
        print("\nSample centroid node IDs:")
        for node_id in list(centroids.keys())[:5]:
            print(f"  - {node_id}")

    # Check taxonomy nodes
    loader = TaxonomyLoader(db)
    nodes = loader.get_all_nodes()
    nodes_with_seeds = loader.get_nodes_with_seeds()
    print(f"\nTaxonomy nodes: {len(nodes)}")
    print(f"Nodes with seeds: {len(nodes_with_seeds)}")

    # =========================================================================
    # STEP 3: Test scorer availability
    # =========================================================================
    print_section("STEP 3: Scorer Availability Test")

    try:
        scorer = HierarchicalScorer(db)
        scorer._ensure_centroids()

        if scorer._centroids:
            print(f"\nScorer is AVAILABLE with {len(scorer._centroids)} centroids")

            # Test scoring a sample paper
            sample_paper = {
                'title': 'Effects of natural daylight on circadian rhythm and sleep quality',
                'abstract': 'This study examines how exposure to natural daylight affects circadian rhythm markers and subjective sleep quality in adults.'
            }

            try:
                result = scorer.score_paper(sample_paper)
                print(f"\nTest paper score: {result['triage_score']:.3f}")
                print(f"Decision: {result['triage_decision']}")
                print(f"Top reasons: {', '.join(result['triage_reasons'][:3])}")
            except Exception as e:
                print(f"\nScoring test failed: {e}")
        else:
            print("\nScorer has NO CENTROIDS - papers will be deferred")

    except ValueError as e:
        print(f"\nScorer not initialized: {e}")
        print("Papers will be deferred until centroids are built")
    except Exception as e:
        print(f"\nScorer error: {e}")

    # =========================================================================
    # STEP 4: Test deferred paper scoring (if applicable)
    # =========================================================================
    print_section("STEP 4: Deferred Paper Scoring")

    if pending_scorer > 0 and len(centroids) > 0:
        print(f"\nFound {pending_scorer} deferred papers and {len(centroids)} centroids")
        print("Running score_deferred_papers()...")

        scorer = HierarchicalScorer(db)
        stats = scorer.score_deferred_papers()

        print(f"\nResults:")
        print(f"  Total processed: {stats['total']}")
        print(f"  Successfully scored: {stats['scored']}")
        print(f"  Promoted to candidate: {stats['promoted']}")
        print(f"  Rejected: {stats['rejected']}")
        print(f"  Errors: {len(stats['errors'])}")

        if stats['errors']:
            print(f"\nFirst 3 errors:")
            for err in stats['errors'][:3]:
                print(f"  - {err}")

        print(f"\nBy decision:")
        for decision, count in stats['by_decision'].items():
            print(f"  {decision}: {count}")

    elif pending_scorer > 0:
        print(f"\nFound {pending_scorer} deferred papers but NO centroids")
        print("Build centroids first to score deferred papers")
        print("\nTo build centroids, run:")
        print("  python triage/taxonomy_loader.py --db data/article_finder.db --load --build")

    else:
        print("\nNo deferred papers to score")

    # =========================================================================
    # STEP 5: Final state
    # =========================================================================
    print_section("STEP 5: Final Database State")

    status_counts_after = get_status_counts(db)
    print("\nPaper counts by status (after):")
    for status, count in sorted(status_counts_after.items()):
        change = count - status_counts.get(status, 0)
        change_str = f" ({'+' if change > 0 else ''}{change})" if change != 0 else ""
        print(f"  {status}: {count}{change_str}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print_section("SUMMARY")

    issues = []
    successes = []

    # Check threshold
    bib = Bibliographer(db, email="test@example.com")
    if bib.threshold == 0.40:
        successes.append("Threshold correctly set to 0.40")
    else:
        issues.append(f"Threshold is {bib.threshold}, expected 0.40")

    # Check centroids
    if len(centroids) > 0:
        successes.append(f"Centroids available: {len(centroids)}")
    else:
        issues.append("No centroids built - scorer will defer all papers")

    # Check pending_scorer handling
    pending_after = status_counts_after.get('pending_scorer', 0)
    if pending_scorer > 0 and pending_after < pending_scorer:
        successes.append(f"Deferred papers reduced: {pending_scorer} → {pending_after}")
    elif pending_scorer > 0 and pending_after == pending_scorer:
        issues.append(f"Deferred papers unchanged at {pending_after}")

    print("\n✓ PASSED:")
    for s in successes:
        print(f"  - {s}")

    if issues:
        print("\n✗ ISSUES:")
        for i in issues:
            print(f"  - {i}")

    print(f"\nCompleted: {datetime.now().isoformat()}")

    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
