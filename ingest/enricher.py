# Version: 3.2.2
"""
Article Finder v3.2 - Batch Enricher
Enrich papers with metadata from multiple APIs.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class BatchEnricher:
    """
    Enrich papers with metadata from CrossRef, OpenAlex, and Semantic Scholar.
    """
    
    def __init__(self, database, email: Optional[str] = None):
        """
        Args:
            database: Database instance
            email: Email for API polite pools
        """
        self.db = database
        self.email = email
        
        # Lazy-load resolvers
        self._resolver = None
        
        self.stats = {
            'processed': 0,
            'enriched': 0,
            'abstracts_added': 0,
            'authors_added': 0,
            'venues_added': 0,
            'errors': 0
        }
    
    @property
    def resolver(self):
        """Lazy-load DOI resolver."""
        if self._resolver is None:
            from .doi_resolver import DOIResolver
            self._resolver = DOIResolver(email=self.email)
        return self._resolver
    
    def enrich_paper(self, paper: Dict) -> Dict[str, Any]:
        """
        Enrich a single paper with metadata.
        
        Returns dict with what was added.
        """
        result = {
            'paper_id': paper.get('paper_id'),
            'enriched': False,
            'fields_added': []
        }
        
        doi = paper.get('doi')
        if not doi:
            return result
        
        try:
            metadata = self.resolver.resolve(doi)
            
            if not metadata:
                return result
            
            # Add missing fields
            updated = False
            
            if metadata.get('abstract') and not paper.get('abstract'):
                paper['abstract'] = metadata['abstract']
                result['fields_added'].append('abstract')
                self.stats['abstracts_added'] += 1
                updated = True
            
            if metadata.get('authors') and not paper.get('authors'):
                paper['authors'] = metadata['authors']
                result['fields_added'].append('authors')
                self.stats['authors_added'] += 1
                updated = True
            
            if metadata.get('venue') and not paper.get('venue'):
                paper['venue'] = metadata['venue']
                result['fields_added'].append('venue')
                self.stats['venues_added'] += 1
                updated = True
            
            if metadata.get('year') and not paper.get('year'):
                paper['year'] = metadata['year']
                result['fields_added'].append('year')
                updated = True
            
            if metadata.get('title') and not paper.get('title'):
                paper['title'] = metadata['title']
                result['fields_added'].append('title')
                updated = True
            
            # Add OA info if available
            if metadata.get('open_access') is not None:
                paper['open_access'] = metadata['open_access']
            if metadata.get('oa_url'):
                paper['oa_url'] = metadata['oa_url']
            
            # Update timestamp
            if updated:
                paper['enriched_at'] = datetime.utcnow().isoformat()
                result['enriched'] = True
                self.stats['enriched'] += 1
            
            # Save to database
            self.db.add_paper(paper)
            
        except Exception as e:
            logger.warning(f"Error enriching {doi}: {e}")
            result['error'] = str(e)
            self.stats['errors'] += 1
        
        self.stats['processed'] += 1
        return result
    
    def enrich_all(
        self,
        filter_missing: str = 'abstract',
        limit: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Enrich all papers missing specified field.
        
        Args:
            filter_missing: Only enrich papers missing this field ('abstract', 'authors', 'any')
            limit: Maximum papers to enrich
            progress_callback: Optional callback(current, total)
            
        Returns:
            Statistics dict
        """
        # Reset stats
        self.stats = {
            'processed': 0,
            'enriched': 0,
            'abstracts_added': 0,
            'authors_added': 0,
            'venues_added': 0,
            'errors': 0
        }
        
        # Get papers needing enrichment
        papers = self.db.search_papers(limit=10000)
        
        if filter_missing == 'abstract':
            papers = [p for p in papers if not p.get('abstract') and p.get('doi')]
        elif filter_missing == 'authors':
            papers = [p for p in papers if not p.get('authors') and p.get('doi')]
        elif filter_missing == 'any':
            papers = [p for p in papers if p.get('doi') and (
                not p.get('abstract') or not p.get('authors') or not p.get('venue')
            )]
        else:
            papers = [p for p in papers if p.get('doi')]
        
        if limit:
            papers = papers[:limit]
        
        total = len(papers)
        logger.info(f"Enriching {total} papers")
        
        for i, paper in enumerate(papers):
            self.enrich_paper(paper)
            
            if progress_callback:
                progress_callback(i + 1, total)
        
        return self.stats
    
    def enrich_by_title_search(
        self,
        papers: List[Dict],
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Enrich papers without DOI by searching CrossRef.
        
        Args:
            papers: Papers to enrich (must have title)
            limit: Maximum to process
            
        Returns:
            Statistics dict
        """
        stats = {
            'processed': 0,
            'found': 0,
            'enriched': 0,
            'errors': 0
        }
        
        # Filter to papers without DOI but with title
        candidates = [p for p in papers if not p.get('doi') and p.get('title')]
        
        if limit:
            candidates = candidates[:limit]
        
        for paper in candidates:
            stats['processed'] += 1
            
            try:
                # Search by title
                results = self.resolver.search_by_bibliographic(
                    title=paper['title'],
                    author=paper.get('authors', [None])[0] if paper.get('authors') else None,
                    year=paper.get('year'),
                    limit=3
                )
                
                if results:
                    # Find best match
                    best = self._best_match(paper, results)
                    
                    if best:
                        stats['found'] += 1
                        
                        # Update paper with found metadata
                        if best.get('doi'):
                            paper['doi'] = best['doi']
                            paper['paper_id'] = f"doi:{best['doi']}"
                        
                        if best.get('abstract') and not paper.get('abstract'):
                            paper['abstract'] = best['abstract']
                            stats['enriched'] += 1
                        
                        if best.get('authors') and not paper.get('authors'):
                            paper['authors'] = best['authors']
                        
                        if best.get('venue') and not paper.get('venue'):
                            paper['venue'] = best['venue']
                        
                        paper['enriched_at'] = datetime.utcnow().isoformat()
                        self.db.add_paper(paper)
                        
            except Exception as e:
                logger.warning(f"Error searching for {paper.get('title', '?')[:50]}: {e}")
                stats['errors'] += 1
        
        return stats
    
    def _best_match(self, paper: Dict, candidates: List[Dict]) -> Optional[Dict]:
        """Find the best matching candidate for a paper."""
        paper_title = (paper.get('title') or '').lower()
        paper_year = paper.get('year')
        
        best = None
        best_score = 0
        
        for candidate in candidates:
            score = 0
            
            # Title similarity
            cand_title = (candidate.get('title') or '').lower()
            if paper_title and cand_title:
                # Simple word overlap
                paper_words = set(paper_title.split())
                cand_words = set(cand_title.split())
                overlap = len(paper_words & cand_words) / max(len(paper_words), 1)
                score += overlap * 0.6
            
            # Year match
            if paper_year and candidate.get('year'):
                if paper_year == candidate['year']:
                    score += 0.3
                elif abs(paper_year - candidate['year']) <= 1:
                    score += 0.15
            
            # Has DOI bonus
            if candidate.get('doi'):
                score += 0.1
            
            if score > best_score:
                best_score = score
                best = candidate
        
        # Only return if score is reasonable
        if best_score >= 0.5:
            return best
        
        return None


def enrich_papers(database, email: str, limit: int = 100, **kwargs) -> Dict[str, Any]:
    """Convenience function for batch enrichment."""
    enricher = BatchEnricher(database, email=email)
    return enricher.enrich_all(limit=limit, **kwargs)
