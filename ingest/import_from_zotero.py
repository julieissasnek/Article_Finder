#!/usr/bin/env python3
"""
Import papers from Zotero into Article Finder database.

This script:
1. Reads papers from local Zotero database
2. Optionally filters for papers with PDFs
3. Imports them into Article Finder with proper metadata
4. Tracks sync state to detect new additions

Usage:
    # Import all papers with PDFs
    python ingest/import_from_zotero.py --import-all --with-pdf

    # Import only new papers since last sync
    python ingest/import_from_zotero.py --import-new

    # Dry run - show what would be imported
    python ingest/import_from_zotero.py --import-new --dry-run
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from ingest.zotero_connector import ZoteroConnector
from triage.scorer import HierarchicalScorer


def generate_paper_id(paper: Dict[str, Any]) -> str:
    """Generate a unique paper ID for a Zotero paper."""
    # Use Zotero key as base for reproducibility
    return f"zotero:{paper['zotero_key']}"


def import_paper(
    db: Database,
    paper: Dict[str, Any],
    scorer: Optional[HierarchicalScorer] = None
) -> Dict[str, Any]:
    """
    Import a single paper from Zotero into Article Finder.

    Returns dict with import status.
    """
    paper_id = generate_paper_id(paper)

    # Check if already exists
    existing = db.get_paper(paper_id)
    if existing:
        return {'status': 'exists', 'paper_id': paper_id}

    # Build paper record
    paper_data = {
        'paper_id': paper_id,
        'title': paper.get('title'),
        'authors': paper.get('authors'),
        'year': paper.get('year'),
        'venue': paper.get('venue'),
        'doi': paper.get('doi'),
        'abstract': paper.get('abstract'),
        'url': paper.get('url'),
        'source': 'zotero',
        'ingest_method': 'zotero_connector',
        'status': 'candidate',
    }

    # Add PDF path if available and exists
    if paper.get('pdf_exists') and paper.get('pdf_path'):
        paper_data['pdf_path'] = paper['pdf_path']

    # Score if scorer available
    if scorer and paper.get('abstract'):
        try:
            result = scorer.score_paper(paper)
            paper_data['triage_score'] = result['triage_score']
            paper_data['triage_decision'] = result['triage_decision']
            paper_data['triage_reasons'] = result.get('triage_reasons', [])

            if result['triage_decision'] == 'reject':
                paper_data['status'] = 'rejected'
        except Exception as e:
            # Scorer failed - mark as pending_scorer
            paper_data['status'] = 'pending_scorer'

    # Remove None values
    paper_data = {k: v for k, v in paper_data.items() if v is not None}

    # Add to database
    db.add_paper(paper_data)

    return {
        'status': 'imported',
        'paper_id': paper_id,
        'triage_decision': paper_data.get('triage_decision')
    }


def import_papers(
    db: Database,
    papers: List[Dict[str, Any]],
    scorer: Optional[HierarchicalScorer] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Import multiple papers from Zotero.

    Returns import statistics.
    """
    stats = {
        'total': len(papers),
        'imported': 0,
        'exists': 0,
        'rejected': 0,
        'errors': 0,
        'error_details': []
    }

    print(f"{'[DRY RUN] ' if dry_run else ''}Importing {len(papers)} papers from Zotero...")

    for i, paper in enumerate(papers):
        if dry_run:
            paper_id = generate_paper_id(paper)
            existing = db.get_paper(paper_id)
            if existing:
                stats['exists'] += 1
            else:
                stats['imported'] += 1
                pdf_marker = "📄" if paper.get('pdf_exists') else "  "
                print(f"  {pdf_marker} Would import: {paper['title'][:50]}...")
            continue

        try:
            result = import_paper(db, paper, scorer)

            if result['status'] == 'imported':
                stats['imported'] += 1
                if result.get('triage_decision') == 'reject':
                    stats['rejected'] += 1
            elif result['status'] == 'exists':
                stats['exists'] += 1

        except Exception as e:
            stats['errors'] += 1
            stats['error_details'].append(f"{paper.get('title', 'Unknown')[:30]}: {e}")

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{len(papers)}")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Import papers from Zotero to Article Finder')
    parser.add_argument('--db', type=Path, default='data/article_finder.db', help='Database path')

    # Import modes
    parser.add_argument('--import-all', action='store_true', help='Import all papers from Zotero')
    parser.add_argument('--import-new', action='store_true', help='Import only new papers since last sync')
    parser.add_argument('--since', type=str, help='Import papers added since date (YYYY-MM-DD)')

    # Filters
    parser.add_argument('--with-pdf', action='store_true', help='Only import papers with PDFs')
    parser.add_argument('--limit', type=int, help='Maximum papers to import')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without importing')
    parser.add_argument('--score', action='store_true', help='Score papers during import')
    parser.add_argument('--mark-synced', action='store_true', help='Mark sync point after import')

    args = parser.parse_args()

    # Initialize
    db = Database(args.db)

    try:
        zotero = ZoteroConnector()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    scorer = None
    if args.score:
        try:
            scorer = HierarchicalScorer(db)
            scorer._ensure_centroids()
            if not scorer._centroids:
                print("Warning: No centroids available. Papers will be marked pending_scorer.")
                scorer = None
        except Exception as e:
            print(f"Warning: Scorer unavailable ({e}). Papers will be marked pending_scorer.")

    # Get papers to import
    if args.import_all:
        print("Fetching all papers from Zotero...")
        papers = zotero.get_all_papers(with_pdf_only=args.with_pdf, limit=args.limit)

    elif args.import_new:
        print("Fetching new papers since last sync...")
        papers = zotero.get_new_papers_since_last_sync()
        if args.with_pdf:
            papers = [p for p in papers if p.get('pdf_exists')]
        if args.limit:
            papers = papers[:args.limit]

    elif args.since:
        print(f"Fetching papers added since {args.since}...")
        papers = zotero.get_papers_added_since(args.since)
        if args.with_pdf:
            papers = [p for p in papers if p.get('pdf_exists')]
        if args.limit:
            papers = papers[:args.limit]

    else:
        # Just show stats
        stats = zotero.get_stats()
        sync_status = zotero.get_sync_status()

        print("\nZotero Library:")
        print(f"  Total papers: {stats['total_papers']}")
        print(f"  With PDFs: {stats['pdf_attachments']}")

        print(f"\nSync Status:")
        print(f"  Last sync: {sync_status['last_sync'] or 'Never'}")
        print(f"  Pending: {sync_status['pending_papers']} papers")

        print("\nUse --import-all, --import-new, or --since to import papers.")
        return 0

    if not papers:
        print("No papers to import.")
        return 0

    # Import
    stats = import_papers(db, papers, scorer, dry_run=args.dry_run)

    # Summary
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Import Summary:")
    print(f"  Total: {stats['total']}")
    print(f"  Imported: {stats['imported']}")
    print(f"  Already exists: {stats['exists']}")
    if stats['rejected']:
        print(f"  Rejected by scorer: {stats['rejected']}")
    if stats['errors']:
        print(f"  Errors: {stats['errors']}")
        for err in stats['error_details'][:5]:
            print(f"    - {err}")

    # Mark synced
    if args.mark_synced and not args.dry_run and stats['imported'] > 0:
        zotero.mark_synced()
        print(f"\nMarked sync point at {datetime.now().isoformat()}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
