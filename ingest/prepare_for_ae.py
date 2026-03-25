#!/usr/bin/env python3
"""
Prepare papers for Article Eater (AE) processing.

This script:
1. Finds papers in the database that have PDFs
2. Creates job bundles in the format AE expects
3. Tracks which papers have been bundled

Usage:
    # Prepare all Zotero papers with PDFs
    python ingest/prepare_for_ae.py --source zotero

    # Prepare specific papers
    python ingest/prepare_for_ae.py --paper-ids zotero:FIZG8FDN zotero:HUH6KAQL

    # Dry run
    python ingest/prepare_for_ae.py --source zotero --dry-run
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from eater_interface.job_bundle_v2 import JobBundleBuilder, BatchBundleBuilder


# Default output directory for AE job bundles
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "ae_jobs"


def get_papers_with_pdfs(
    db: Database,
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Get papers that have PDF paths."""
    with db.connection() as conn:
        query = """
            SELECT * FROM papers
            WHERE pdf_path IS NOT NULL
              AND pdf_path != ''
        """
        params = []

        if source:
            query += " AND source = ?"
            params.append(source)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def check_pdf_exists(paper: Dict[str, Any]) -> bool:
    """Check if the PDF file exists."""
    pdf_path = paper.get('pdf_path')
    if not pdf_path:
        return False
    return Path(pdf_path).exists()


def prepare_papers_for_ae(
    db: Database,
    papers: List[Dict[str, Any]],
    output_dir: Path,
    dry_run: bool = False,
    validate: bool = True
) -> Dict[str, Any]:
    """
    Prepare job bundles for a list of papers.

    Returns statistics about the preparation.
    """
    stats = {
        'total': len(papers),
        'bundled': 0,
        'skipped_no_pdf': 0,
        'skipped_missing_file': 0,
        'errors': 0,
        'error_details': [],
        'bundles': []
    }

    if dry_run:
        print(f"[DRY RUN] Would prepare {len(papers)} papers for AE...")
    else:
        print(f"Preparing {len(papers)} papers for AE...")
        output_dir.mkdir(parents=True, exist_ok=True)

    builder = BatchBundleBuilder(output_dir) if not dry_run else None

    for i, paper in enumerate(papers):
        paper_id = paper.get('paper_id', 'unknown')
        pdf_path = paper.get('pdf_path')

        # Check PDF path
        if not pdf_path:
            stats['skipped_no_pdf'] += 1
            continue

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            stats['skipped_missing_file'] += 1
            stats['error_details'].append(f"{paper_id}: PDF not found at {pdf_path}")
            continue

        if dry_run:
            print(f"  Would bundle: {paper.get('title', 'Unknown')[:50]}...")
            print(f"    PDF: {pdf_path}")
            stats['bundled'] += 1
            continue

        try:
            bundle_path = builder.add_paper(
                paper,
                pdf_path,
                include_abstract=True,
                validate=validate
            )

            if bundle_path:
                stats['bundled'] += 1
                stats['bundles'].append(str(bundle_path))

                # Update paper status in database
                with db.connection() as conn:
                    conn.execute(
                        "UPDATE papers SET ae_job_path = ?, ae_status = 'pending' WHERE paper_id = ?",
                        (str(bundle_path), paper_id)
                    )
            else:
                stats['errors'] += 1

        except Exception as e:
            stats['errors'] += 1
            stats['error_details'].append(f"{paper_id}: {e}")

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(papers)}")

    if builder:
        summary = builder.get_summary()
        stats['run_id'] = summary['run_id']

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Prepare papers for Article Eater')
    parser.add_argument('--db', type=Path, default='data/article_finder.db', help='Database path')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT_DIR, help='Output directory for job bundles')

    # Selection
    parser.add_argument('--source', type=str, help='Only papers from this source (e.g., "zotero")')
    parser.add_argument('--status', type=str, help='Only papers with this status')
    parser.add_argument('--paper-ids', nargs='+', help='Specific paper IDs to prepare')
    parser.add_argument('--limit', type=int, help='Maximum papers to prepare')

    # Options
    parser.add_argument('--dry-run', action='store_true', help='Show what would be prepared')
    parser.add_argument('--no-validate', action='store_true', help='Skip schema validation')

    args = parser.parse_args()

    db = Database(args.db)

    # Get papers
    if args.paper_ids:
        papers = []
        for pid in args.paper_ids:
            paper = db.get_paper(pid)
            if paper:
                papers.append(paper)
            else:
                print(f"Warning: Paper not found: {pid}")
    else:
        papers = get_papers_with_pdfs(
            db,
            source=args.source,
            status=args.status,
            limit=args.limit
        )

    if not papers:
        print("No papers found matching criteria.")
        return 0

    print(f"Found {len(papers)} papers with PDFs")

    # Filter to only papers with existing PDFs
    papers_with_existing_pdfs = [p for p in papers if check_pdf_exists(p)]
    print(f"  {len(papers_with_existing_pdfs)} have existing PDF files")

    if not papers_with_existing_pdfs:
        print("No papers with existing PDFs found.")
        return 0

    # Prepare bundles
    stats = prepare_papers_for_ae(
        db,
        papers_with_existing_pdfs,
        args.output,
        dry_run=args.dry_run,
        validate=not args.no_validate
    )

    # Summary
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Preparation Summary:")
    print(f"  Total: {stats['total']}")
    print(f"  Bundled: {stats['bundled']}")
    if stats['skipped_no_pdf']:
        print(f"  Skipped (no PDF path): {stats['skipped_no_pdf']}")
    if stats['skipped_missing_file']:
        print(f"  Skipped (file missing): {stats['skipped_missing_file']}")
    if stats['errors']:
        print(f"  Errors: {stats['errors']}")
        for err in stats['error_details'][:5]:
            print(f"    - {err}")

    if not args.dry_run and stats['bundled'] > 0:
        print(f"\nJob bundles created in: {args.output}")
        print(f"Run ID: {stats.get('run_id', 'N/A')}")
        print(f"\nTo process with AE, run Article Eater on the bundles in {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
