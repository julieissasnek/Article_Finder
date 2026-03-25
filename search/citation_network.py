# Version: 3.2.2
"""
Article Finder v3 - Citation Network
Fetches citations and builds traversal network.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Set
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from ingest.doi_resolver import OpenAlexClient, DOIResolver
from config.loader import get


class CitationFetcher:
    """Fetch citations for papers using OpenAlex."""
    
    def __init__(self, database: Database, email: Optional[str] = None):
        self.db = database
        self.openalex = OpenAlexClient(email=email or get('apis.openalex.email'))
        self.resolver = DOIResolver(email=email)
    
    def fetch_citations_for_paper(self, paper_id: str) -> Dict[str, Any]:
        """
        Fetch forward (references) and backward (citations) for a paper.
        
        Returns stats about what was fetched.
        """
        paper = self.db.get_paper(paper_id)
        if not paper:
            return {'error': 'Paper not found'}
        
        doi = paper.get('doi')
        if not doi:
            return {'error': 'Paper has no DOI'}
        
        stats = {
            'paper_id': paper_id,
            'references_found': 0,
            'citations_found': 0,
            'added_to_queue': 0
        }
        
        # Fetch references (papers this paper cites)
        try:
            work = self.openalex.get_work_by_doi(doi)
            if work and work.get('referenced_works'):
                for ref_id in work['referenced_works'][:50]:  # Limit
                    try:
                        ref_work = self.openalex.get_work_by_id(ref_id)
                        if ref_work and ref_work.get('doi'):
                            self._add_citation(
                                paper_id,
                                ref_work['doi'],
                                ref_work.get('title'),
                                ref_work.get('year'),
                                'reference'
                            )
                            stats['references_found'] += 1
                    except Exception:
                        pass
        except Exception as e:
            stats['references_error'] = str(e)
        
        # Fetch citing papers (papers that cite this paper)
        try:
            citing = self.openalex.get_citations(doi, limit=50)
            for citing_work in citing:
                if citing_work.get('doi'):
                    self._add_citation(
                        paper_id,
                        citing_work['doi'],
                        citing_work.get('title'),
                        citing_work.get('year'),
                        'citing'
                    )
                    stats['citations_found'] += 1
        except Exception as e:
            stats['citations_error'] = str(e)
        
        return stats
    
    def _add_citation(
        self,
        source_paper_id: str,
        cited_doi: str,
        cited_title: Optional[str],
        cited_year: Optional[int],
        direction: str
    ) -> None:
        """Add a citation link and optionally queue the paper."""
        
        # Normalize DOI
        cited_doi = cited_doi.lower().strip()
        if cited_doi.startswith('https://doi.org/'):
            cited_doi = cited_doi[16:]
        
        # Check if paper exists in corpus
        existing = self.db.get_paper_by_doi(cited_doi)
        cited_paper_id = existing['paper_id'] if existing else None
        
        # Add citation link
        if direction == 'reference':
            # source_paper_id cites cited_doi
            self.db.add_citation(
                source_paper_id=source_paper_id,
                cited_doi=cited_doi,
                cited_title=cited_title,
                cited_year=cited_year,
                discovered_via='openalex'
            )
        else:
            # cited_doi cites source_paper_id
            # We need to add the reverse link
            citing_paper_id = f"doi:{cited_doi}"
            self.db.add_citation(
                source_paper_id=citing_paper_id,
                cited_doi=self.db.get_paper(source_paper_id).get('doi'),
                discovered_via='openalex_citing'
            )
        
        # Add to expansion queue if not in corpus
        if not existing:
            self.db.add_to_expansion_queue(
                doi=cited_doi,
                title=cited_title,
                discovered_from=source_paper_id,
                priority_score=0.5
            )
    
    def fetch_all(
        self,
        limit: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """Fetch citations for all papers with DOIs."""
        
        papers = self.db.search_papers(limit=10000)
        papers = [p for p in papers if p.get('doi')]
        
        if limit:
            papers = papers[:limit]
        
        stats = {
            'total': len(papers),
            'processed': 0,
            'total_references': 0,
            'total_citations': 0,
            'errors': []
        }
        
        print(f"Fetching citations for {len(papers)} papers...")
        
        for i, paper in enumerate(papers):
            if progress_callback:
                progress_callback(i + 1, len(papers))
            
            try:
                result = self.fetch_citations_for_paper(paper['paper_id'])
                stats['total_references'] += result.get('references_found', 0)
                stats['total_citations'] += result.get('citations_found', 0)
                stats['processed'] += 1
            except Exception as e:
                stats['errors'].append(f"{paper['paper_id']}: {e}")
            
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(papers)}")
        
        return stats


class ExpansionManager:
    """Manage the expansion queue for corpus growth."""
    
    def __init__(self, database: Database, email: Optional[str] = None):
        self.db = database
        self.resolver = DOIResolver(email=email or get('apis.openalex.email'))
        
        # Config
        self.min_citations = get('citations.min_corpus_citations', 2)
    
    def get_queue(self, limit: int = 50) -> List[Dict]:
        """Get prioritized expansion queue."""
        return self.db.get_expansion_queue(status='pending', limit=limit)
    
    def reprioritize_queue(self) -> int:
        """
        Recalculate priority scores based on corpus citations.
        
        Papers cited by more corpus papers get higher priority.
        """
        queue = self.db.get_expansion_queue(status='pending', limit=1000)
        updated = 0
        
        for item in queue:
            # Count how many corpus papers cite this
            citation_count = item.get('discovery_count', 1)
            
            # Higher priority for papers cited by more corpus papers
            priority = min(1.0, citation_count / 10.0)
            
            # Could also factor in relevance to taxonomy here
            
            with self.db.connection() as conn:
                conn.execute(
                    """UPDATE expansion_queue 
                       SET priority_score = ?, updated_at = ?
                       WHERE doi = ?""",
                    (priority, datetime.utcnow().isoformat(), item['doi'])
                )
            updated += 1
        
        return updated
    
    def import_from_queue(
        self,
        limit: int = 50,
        min_priority: float = 0.3,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Import high-priority papers from expansion queue to corpus.
        """
        queue = self.get_queue(limit=limit * 2)  # Get extra to filter
        queue = [q for q in queue if q.get('priority_score', 0) >= min_priority]
        queue = queue[:limit]
        
        stats = {
            'total': len(queue),
            'imported': 0,
            'failed': 0,
            'errors': []
        }
        
        print(f"Importing {len(queue)} papers from expansion queue...")
        
        for i, item in enumerate(queue):
            if progress_callback:
                progress_callback(i + 1, len(queue))
            
            try:
                # Fetch metadata
                metadata = self.resolver.resolve(item['doi'])
                
                if metadata:
                    # Create paper record
                    paper = {
                        'paper_id': f"doi:{item['doi']}",
                        'doi': item['doi'],
                        'title': metadata.get('title', item.get('title', 'Unknown')),
                        'authors': metadata.get('authors', []),
                        'year': metadata.get('year'),
                        'venue': metadata.get('venue'),
                        'publisher': metadata.get('publisher'),
                        'abstract': metadata.get('abstract'),
                        'url': metadata.get('url'),
                        'source': 'expansion_queue',
                        'ingest_method': 'citation_chase',
                        'status': 'candidate',
                        'retrieved_at': datetime.utcnow().isoformat()
                    }
                    
                    self.db.add_paper(paper)
                    
                    # Update queue status
                    with self.db.connection() as conn:
                        conn.execute(
                            "UPDATE expansion_queue SET status = 'fetched' WHERE doi = ?",
                            (item['doi'],)
                        )
                    
                    stats['imported'] += 1
                else:
                    # Mark as not found
                    with self.db.connection() as conn:
                        conn.execute(
                            "UPDATE expansion_queue SET status = 'not_found' WHERE doi = ?",
                            (item['doi'],)
                        )
                    stats['failed'] += 1
                    
            except Exception as e:
                stats['errors'].append(f"{item['doi']}: {e}")
                stats['failed'] += 1
            
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(queue)}")
        
        return stats
    
    def get_network_stats(self) -> Dict[str, Any]:
        """Get citation network statistics."""
        stats = self.db.get_corpus_stats()
        
        # Count papers with citations
        with self.db.connection() as conn:
            papers_with_refs = conn.execute(
                "SELECT COUNT(DISTINCT source_paper_id) FROM citations"
            ).fetchone()[0]
            
            papers_cited = conn.execute(
                "SELECT COUNT(DISTINCT cited_paper_id) FROM citations WHERE cited_paper_id IS NOT NULL"
            ).fetchone()[0]
        
        return {
            **stats,
            'papers_with_references': papers_with_refs,
            'papers_with_citations': papers_cited,
            'citation_links': stats.get('total_citations', 0)
        }


# CLI
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Citation network management')
    parser.add_argument('--db', type=Path, default='data/article_finder.db')
    parser.add_argument('--email', help='Email for API')
    parser.add_argument('--fetch', action='store_true', help='Fetch citations for all papers')
    parser.add_argument('--import-queue', action='store_true', help='Import from expansion queue')
    parser.add_argument('--reprioritize', action='store_true', help='Recalculate queue priorities')
    parser.add_argument('--stats', action='store_true', help='Show network statistics')
    parser.add_argument('--limit', type=int, default=50)
    
    args = parser.parse_args()
    
    db = Database(args.db)
    
    if args.fetch:
        fetcher = CitationFetcher(db, email=args.email)
        stats = fetcher.fetch_all(limit=args.limit)
        print(f"\nFetch complete:")
        print(f"  Papers processed: {stats['processed']}")
        print(f"  References found: {stats['total_references']}")
        print(f"  Citations found: {stats['total_citations']}")
    
    elif args.import_queue:
        manager = ExpansionManager(db, email=args.email)
        stats = manager.import_from_queue(limit=args.limit)
        print(f"\nImport complete:")
        print(f"  Imported: {stats['imported']}")
        print(f"  Failed: {stats['failed']}")
    
    elif args.reprioritize:
        manager = ExpansionManager(db, email=args.email)
        updated = manager.reprioritize_queue()
        print(f"Updated {updated} queue items")
    
    elif args.stats:
        manager = ExpansionManager(db, email=args.email)
        stats = manager.get_network_stats()
        print("\nCitation Network Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    else:
        parser.print_help()
