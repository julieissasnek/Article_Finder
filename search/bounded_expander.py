# Version: 3.2.2
"""
Article Finder v3.2 - Bounded Expander
Wraps citation fetching with taxonomy-based relevance filtering.

This is the key component that prevents corpus pollution. Instead of blindly
adding all citations, it:
1. Fetches citations from OpenAlex
2. Scores each against the taxonomy
3. Only queues papers above the relevance threshold
4. Tracks expansion depth to prevent runaway growth
"""

import logging
import time
from typing import Optional, Dict, List, Any, Tuple, Generator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExpansionStats:
    """Statistics from an expansion run."""
    papers_processed: int = 0
    citations_discovered: int = 0
    references_discovered: int = 0
    scored: int = 0
    queued: int = 0
    rejected: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    
    # Breakdown by reason
    rejected_reasons: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'papers_processed': self.papers_processed,
            'citations_discovered': self.citations_discovered,
            'references_discovered': self.references_discovered,
            'scored': self.scored,
            'queued': self.queued,
            'rejected': self.rejected,
            'duplicates_skipped': self.duplicates_skipped,
            'errors': self.errors,
            'rejected_reasons': self.rejected_reasons,
            'acceptance_rate': self.queued / self.scored if self.scored > 0 else 0
        }


class BoundedExpander:
    """
    Expands the corpus via citations while staying within taxonomy boundaries.
    
    Key features:
    - Scores all discovered papers against taxonomy before queueing
    - Tracks expansion depth to prevent infinite growth
    - Deduplicates against existing corpus and queue
    - Provides detailed statistics on what was accepted/rejected
    """
    
    def __init__(
        self,
        database,
        email: str,
        relevance_threshold: float = 0.35,
        max_depth: int = 2,
        require_abstract_for_scoring: bool = False
    ):
        """
        Args:
            database: Database instance
            email: Email for API access
            relevance_threshold: Minimum taxonomy score to queue (0-1)
            max_depth: Maximum citation hops from seed corpus
            require_abstract_for_scoring: If True, fetch abstracts before scoring
        """
        self.db = database
        self.email = email
        self.threshold = relevance_threshold
        self.max_depth = max_depth
        self.require_abstract = require_abstract_for_scoring
        
        # Lazy-loaded components
        self._openalex = None
        self._scorer = None
        self._filter = None
        
        # Track what we've seen to avoid duplicates
        self._seen_dois = set()
        self._seen_titles = set()
    
    @property
    def openalex(self):
        """Lazy-load OpenAlex client."""
        if self._openalex is None:
            from ingest.doi_resolver import OpenAlexClient
            self._openalex = OpenAlexClient(email=self.email)
        return self._openalex
    
    @property
    def scorer(self):
        """Lazy-load expansion scorer."""
        if self._scorer is None:
            from search.expansion_scorer import ExpansionScorer
            self._scorer = ExpansionScorer(self.db)
        return self._scorer
    
    @property
    def relevance_filter(self):
        """Lazy-load relevance filter."""
        if self._filter is None:
            from search.expansion_scorer import RelevanceFilter
            self._filter = RelevanceFilter(
                threshold=self.threshold,
                require_abstract=self.require_abstract,
                max_depth=self.max_depth
            )
        return self._filter
    
    def _load_existing_identifiers(self):
        """Load existing papers into deduplicator index."""
        from search.deduplicator import Deduplicator
        
        self._deduplicator = Deduplicator(self.db)
        self._deduplicator.load_index()
        
        # Keep simple sets for quick checks too
        papers = self.db.search_papers(limit=50000)
        
        for paper in papers:
            if paper.get('doi'):
                self._seen_dois.add(paper['doi'].lower())
            if paper.get('title'):
                self._seen_titles.add(self._normalize_title(paper['title']))
        
        # Also load from expansion queue
        queue = self.db.get_expansion_queue(limit=50000)
        for item in queue:
            if item.get('doi'):
                self._seen_dois.add(item['doi'].lower())
            if item.get('title'):
                self._seen_titles.add(self._normalize_title(item['title']))
        
        logger.info(f"Loaded {len(self._seen_dois)} DOIs and {len(self._seen_titles)} titles for dedup")
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for duplicate detection."""
        import re
        # Lowercase, remove punctuation, collapse whitespace
        normalized = title.lower()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = ' '.join(normalized.split())
        return normalized
    
    def _is_duplicate(self, doi: Optional[str], title: Optional[str]) -> bool:
        """Check if paper is already in corpus or queue."""
        if doi and doi.lower() in self._seen_dois:
            return True
        if title and self._normalize_title(title) in self._seen_titles:
            return True
        return False
    
    def _mark_seen(self, doi: Optional[str], title: Optional[str]):
        """Mark a paper as seen."""
        if doi:
            self._seen_dois.add(doi.lower())
        if title:
            self._seen_titles.add(self._normalize_title(title))
    
    def expand_paper(
        self,
        paper_id: str,
        doi: str,
        current_depth: int = 0,
        fetch_citations: bool = True,
        fetch_references: bool = True
    ) -> ExpansionStats:
        """
        Expand from a single paper.
        
        Args:
            paper_id: ID of source paper
            doi: DOI of source paper
            current_depth: Current expansion depth
            fetch_citations: Fetch papers that cite this one
            fetch_references: Fetch papers this one cites
            
        Returns:
            ExpansionStats for this paper
        """
        stats = ExpansionStats()
        stats.papers_processed = 1
        
        candidates = []
        
        # Fetch citations (papers citing this one)
        if fetch_citations:
            try:
                citing = self.openalex.get_citations(doi, limit=100)
                for work in citing:
                    work['discovered_from'] = paper_id
                    work['discovery_type'] = 'cited_by'
                    work['discovery_depth'] = current_depth + 1
                    candidates.append(work)
                stats.citations_discovered = len(citing)
            except Exception as e:
                logger.warning(f"Failed to fetch citations for {doi}: {e}")
                stats.errors += 1
        
        # Fetch references (papers this one cites)
        if fetch_references:
            try:
                refs = self.openalex.get_references(doi)
                # References are just IDs, need to fetch full metadata
                for ref_id in refs[:50]:  # Limit to prevent explosion
                    try:
                        work = self.openalex.get_work_by_id(ref_id)
                        if work:
                            work['discovered_from'] = paper_id
                            work['discovery_type'] = 'references'
                            work['discovery_depth'] = current_depth + 1
                            candidates.append(work)
                    except Exception:
                        pass
                stats.references_discovered = len([c for c in candidates 
                                                   if c.get('discovery_type') == 'references'])
            except Exception as e:
                logger.warning(f"Failed to fetch references for {doi}: {e}")
                stats.errors += 1
        
        # Process candidates
        for candidate in candidates:
            self._process_candidate(candidate, stats)
        
        return stats
    
    def _process_candidate(self, candidate: Dict[str, Any], stats: ExpansionStats):
        """Process a single candidate paper."""
        doi = candidate.get('doi')
        title = candidate.get('title')
        
        # Deduplication check
        if self._is_duplicate(doi, title):
            stats.duplicates_skipped += 1
            return
        
        # Score against taxonomy
        stats.scored += 1
        scored = self.scorer.score_candidate(candidate)
        
        # Apply relevance filter
        should_queue, reason = self.relevance_filter.should_queue(scored)
        
        if should_queue:
            # Add to expansion queue
            self._add_to_queue(scored)
            self._mark_seen(doi, title)
            stats.queued += 1
        else:
            stats.rejected += 1
            # Track rejection reasons
            reason_key = reason.split('(')[0].strip()  # Simplify reason
            stats.rejected_reasons[reason_key] = stats.rejected_reasons.get(reason_key, 0) + 1
    
    def _add_to_queue(self, scored):
        """Add a scored paper to the expansion queue."""
        from search.expansion_scorer import ScoredPaper
        
        queue_entry = {
            'doi': scored.doi,
            'title': scored.title,
            'authors': scored.authors,
            'year': scored.year,
            'abstract': scored.abstract,
            'relevance_score': scored.relevance_score,
            'top_facets': scored.top_facets,
            'discovered_from': scored.discovered_from,
            'discovery_type': scored.discovery_type,
            'discovery_depth': scored.discovery_depth,
            'status': 'pending',
            'queued_at': datetime.utcnow().isoformat()
        }
        
        self.db.add_to_expansion_queue(queue_entry)
    
    def expand_corpus(
        self,
        limit: int = 50,
        papers_with_status: str = 'send_to_eater',
        progress_callback=None
    ) -> ExpansionStats:
        """
        Expand from multiple papers in the corpus.
        
        Args:
            limit: Maximum papers to expand from
            papers_with_status: Only expand from papers with this triage status
            progress_callback: Optional callback(current, total, stats)
            
        Returns:
            Aggregated ExpansionStats
        """
        # Load existing identifiers for dedup
        self._load_existing_identifiers()
        
        # Get papers to expand from
        papers = self.db.get_papers_by_status(papers_with_status, limit=limit)
        papers_with_doi = [p for p in papers if p.get('doi')]
        
        logger.info(f"Expanding from {len(papers_with_doi)} papers with status '{papers_with_status}'")
        
        total_stats = ExpansionStats()
        
        for i, paper in enumerate(papers_with_doi):
            try:
                paper_stats = self.expand_paper(
                    paper_id=paper['paper_id'],
                    doi=paper['doi'],
                    current_depth=0
                )
                
                # Aggregate stats
                total_stats.papers_processed += paper_stats.papers_processed
                total_stats.citations_discovered += paper_stats.citations_discovered
                total_stats.references_discovered += paper_stats.references_discovered
                total_stats.scored += paper_stats.scored
                total_stats.queued += paper_stats.queued
                total_stats.rejected += paper_stats.rejected
                total_stats.duplicates_skipped += paper_stats.duplicates_skipped
                total_stats.errors += paper_stats.errors
                
                for reason, count in paper_stats.rejected_reasons.items():
                    total_stats.rejected_reasons[reason] = \
                        total_stats.rejected_reasons.get(reason, 0) + count
                
            except Exception as e:
                logger.error(f"Error expanding {paper['paper_id']}: {e}")
                total_stats.errors += 1
            
            if progress_callback:
                progress_callback(i + 1, len(papers_with_doi), total_stats)
            
            # Rate limiting
            time.sleep(0.2)
        
        return total_stats
    
    def expand_iteratively(
        self,
        max_iterations: int = 3,
        papers_per_iteration: int = 20,
        min_queue_growth: int = 5,
        progress_callback=None
    ) -> List[ExpansionStats]:
        """
        Iteratively expand the corpus until saturation.
        
        Stops when:
        - Max iterations reached
        - Queue growth falls below threshold (saturation)
        
        Args:
            max_iterations: Maximum expansion iterations
            papers_per_iteration: Papers to process per iteration
            min_queue_growth: Stop if fewer papers queued
            progress_callback: Optional callback(iteration, stats)
            
        Returns:
            List of stats per iteration
        """
        all_stats = []
        
        for iteration in range(max_iterations):
            logger.info(f"=== Expansion Iteration {iteration + 1}/{max_iterations} ===")
            
            stats = self.expand_corpus(limit=papers_per_iteration)
            all_stats.append(stats)
            
            if progress_callback:
                progress_callback(iteration + 1, stats)
            
            # Check for saturation
            if stats.queued < min_queue_growth:
                logger.info(f"Saturation reached: only {stats.queued} new papers queued")
                break
            
            logger.info(f"Iteration {iteration + 1}: {stats.queued} papers queued, "
                       f"{stats.rejected} rejected")
        
        return all_stats


def expand_with_bounds(
    database,
    email: str,
    threshold: float = 0.35,
    max_depth: int = 2,
    limit: int = 50
) -> ExpansionStats:
    """Convenience function for bounded expansion."""
    expander = BoundedExpander(
        database=database,
        email=email,
        relevance_threshold=threshold,
        max_depth=max_depth
    )
    return expander.expand_corpus(limit=limit)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Bounded corpus expansion')
    parser.add_argument('--threshold', type=float, default=0.35, help='Relevance threshold')
    parser.add_argument('--depth', type=int, default=2, help='Max citation depth')
    parser.add_argument('--limit', type=int, default=20, help='Papers to expand from')
    parser.add_argument('--email', required=True, help='Email for API access')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    
    from core.database import Database
    from config.loader import get
    
    db = Database(Path(get('paths.database', 'data/article_finder.db')))
    
    print(f"Expanding with threshold={args.threshold}, depth={args.depth}")
    
    stats = expand_with_bounds(
        database=db,
        email=args.email,
        threshold=args.threshold,
        max_depth=args.depth,
        limit=args.limit
    )
    
    print("\n=== Expansion Results ===")
    print(f"Papers processed:    {stats.papers_processed}")
    print(f"Citations found:     {stats.citations_discovered}")
    print(f"References found:    {stats.references_discovered}")
    print(f"Scored:              {stats.scored}")
    print(f"Queued:              {stats.queued}")
    print(f"Rejected:            {stats.rejected}")
    print(f"Duplicates skipped:  {stats.duplicates_skipped}")
    print(f"Acceptance rate:     {stats.queued/stats.scored*100:.1f}%" if stats.scored else "N/A")
    
    if stats.rejected_reasons:
        print("\nRejection reasons:")
        for reason, count in sorted(stats.rejected_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
