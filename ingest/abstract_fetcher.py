# Version: 3.2.2
"""
Article Finder v3.2 - Abstract Fetcher
Fetches abstracts for queued papers and updates topic decisions.
"""

import logging
from typing import Dict, Any, Optional, List

from core.database import Database
from ingest.doi_resolver import DOIResolver
from ingest.pdf_cataloger import PDFCataloger
from config.loader import get

logger = logging.getLogger(__name__)


class AbstractFetcher:
    """Fetch abstracts for queued papers and update topic decisions."""

    def __init__(self, database: Database, email: Optional[str] = None):
        self.db = database
        self.email = email
        self.resolver = DOIResolver(email=email)
        self.cataloger = PDFCataloger()

        self.stats = {
            'processed': 0,
            'matched': 0,
            'abstracts_added': 0,
            'not_found': 0,
            'errors': 0,
        }

    def _title_overlap(self, left: str, right: str) -> float:
        left_tokens = self.cataloger._tokenize_text(left)
        right_tokens = self.cataloger._tokenize_text(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = left_tokens & right_tokens
        return len(overlap) / max(len(left_tokens), 1)

    def _best_title_match(self, title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        if not title:
            return None
        results = self.resolver.search_by_bibliographic(
            title=title,
            author=None,
            year=year,
            limit=5,
        )
        best = None
        best_score = 0.0
        for result in results:
            score = self._title_overlap(title, result.get('title', ''))
            if score > best_score:
                best = result
                best_score = score
        if best_score >= 0.2:
            return best
        return None

    def _update_paper_from_metadata(self, paper: Dict[str, Any], metadata: Dict[str, Any]) -> bool:
        updated = False

        for field in ['doi', 'title', 'authors', 'year', 'venue', 'publisher', 'url']:
            if metadata.get(field) and not paper.get(field):
                paper[field] = metadata[field]
                updated = True

        if metadata.get('abstract') and not paper.get('abstract'):
            paper['abstract'] = metadata['abstract']
            updated = True
            self.stats['abstracts_added'] += 1

        if paper.get('abstract'):
            abstract = paper['abstract'].lower()
            score = self.cataloger._relevance_score(abstract)
            paper['topic_score'] = score
            paper['topic_stage'] = 'final'
            paper['topic_decision'] = 'on_topic' if score >= self.cataloger.OFF_TOPIC_THRESHOLD else 'off_topic'
            paper['off_topic_score'] = score
            paper['off_topic_flag'] = 1 if paper['topic_decision'] == 'off_topic' else 0
            updated = True

        if updated:
            self.db.add_paper(paper)

        return updated

    def reset_queue(self, status: str = 'not_found') -> int:
        """Reset queue items back to pending."""
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                UPDATE expansion_queue
                SET status = 'pending', rejection_reason = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE status = ?
                """,
                (status,),
            )
            return cur.rowcount


    def fetch_from_queue(self, limit: int = 50) -> Dict[str, Any]:
        queue = self.db.get_expansion_queue(status='pending', limit=limit)

        for item in queue:
            self.stats['processed'] += 1
            doi = item.get('doi')
            title = item.get('title')
            year = item.get('year')
            paper = None

            if item.get('discovered_from'):
                paper = self.db.get_paper(item['discovered_from'])

            if not paper and doi and not doi.startswith('title:'):
                paper = self.db.get_paper_by_doi(doi)

            if not paper:
                self._mark_queue(item, 'not_found', 'paper_missing')
                self.stats['not_found'] += 1
                continue

            try:
                metadata = None
                if doi and not doi.startswith('title:'):
                    metadata = self.resolver.resolve(doi)
                elif title:
                    metadata = self._best_title_match(title, year)
                else:
                    self._mark_queue(item, 'not_found', 'missing_title')
                    self.stats['not_found'] += 1
                    continue

                if metadata:
                    self.stats['matched'] += 1
                    updated = self._update_paper_from_metadata(paper, metadata)
                    if updated:
                        self._mark_queue(item, 'fetched', None)
                    else:
                        self._mark_queue(item, 'not_found', 'no_new_data')
                        self.stats['not_found'] += 1
                else:
                    self._mark_queue(item, 'not_found', 'no_match')
                    self.stats['not_found'] += 1
            except Exception as exc:
                logger.warning(f"Error fetching abstract for {doi or title}: {exc}")
                self._mark_queue(item, 'not_found', 'error')
                self.stats['errors'] += 1

        return self.stats

    def _mark_queue(self, item: Dict[str, Any], status: str, reason: Optional[str]) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE expansion_queue
                SET status = ?, rejection_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE doi = ?
                """,
                (status, reason, item.get('doi')),
            )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Fetch abstracts for queued papers')
    parser.add_argument('--limit', type=int, default=50, help='Max queue items to process')
    parser.add_argument('--retry-not-found', action='store_true', help='Retry items marked not_found')
    parser.add_argument('--email', type=str, help='Email for API polite pool')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    email = args.email or get('apis.openalex.email') or get('apis.crossref.email')
    if not email:
        print('Error: Valid email required for API access')
        return 1

    db = Database()
    fetcher = AbstractFetcher(db, email=email)
    if args.retry_not_found:
        reset = fetcher.reset_queue(status='not_found')
        print(f'Reset {reset} queue items to pending')
    stats = fetcher.fetch_from_queue(limit=args.limit)

    print("\n=== Abstract Fetch Results ===")
    print(f"Processed:        {stats['processed']}")
    print(f"Matched:          {stats['matched']}")
    print(f"Abstracts added:  {stats['abstracts_added']}")
    print(f"Not found:        {stats['not_found']}")
    print(f"Errors:           {stats['errors']}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
