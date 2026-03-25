# Version: 3.2.2
"""
Article Finder v3.2.2 - Semantic Search
Vector similarity search over paper embeddings.

Enables queries like:
- "daylight effects on mood"
- "acoustic privacy in open offices"
- "biophilic design cognitive benefits"

Returns papers ranked by semantic similarity to query.
"""

import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with relevance score."""
    paper_id: str
    title: str
    score: float
    doi: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    authors: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'paper_id': self.paper_id,
            'title': self.title,
            'score': self.score,
            'doi': self.doi,
            'year': self.year,
            'abstract': self.abstract[:200] + '...' if self.abstract and len(self.abstract) > 200 else self.abstract,
            'authors': self.authors
        }


class SemanticSearch:
    """
    Semantic search over paper corpus using embeddings.
    
    Embeds the query, compares to paper embeddings, returns ranked results.
    """
    
    def __init__(self, database, embedding_service=None):
        """
        Args:
            database: Database instance
            embedding_service: Optional embedding service (lazy-loaded if None)
        """
        self.db = database
        self._embeddings = embedding_service
        self._paper_index = None  # Cache of paper_id -> embedding
        self._paper_metadata = None  # Cache of paper_id -> metadata
    
    @property
    def embeddings(self):
        """Lazy-load embedding service."""
        if self._embeddings is None:
            from triage.embeddings import get_embedding_service
            self._embeddings = get_embedding_service()
        return self._embeddings
    
    def _build_index(self, force_rebuild: bool = False):
        """Build in-memory index of paper embeddings."""
        if self._paper_index is not None and not force_rebuild:
            return
        
        logger.info("Building paper embedding index...")
        
        self._paper_index = {}
        self._paper_metadata = {}
        
        papers = self.db.search_papers(limit=50000)
        
        embedded_count = 0
        for paper in papers:
            paper_id = paper.get('paper_id')
            if not paper_id:
                continue
            
            # Check if we have stored embedding
            stored_embedding = self._get_stored_embedding(paper_id)
            
            if stored_embedding is not None:
                self._paper_index[paper_id] = stored_embedding
            else:
                # Compute embedding from title + abstract
                title = paper.get('title', '')
                abstract = paper.get('abstract', '')
                
                if title or abstract:
                    text = f"{title}. {abstract}" if abstract else title
                    try:
                        embedding = self.embeddings.embed(text)
                        self._paper_index[paper_id] = embedding
                        self._store_embedding(paper_id, embedding)
                    except Exception as e:
                        logger.warning(f"Failed to embed {paper_id}: {e}")
                        continue
            
            # Store metadata for results
            self._paper_metadata[paper_id] = {
                'title': paper.get('title', 'Untitled'),
                'doi': paper.get('doi'),
                'year': paper.get('year'),
                'abstract': paper.get('abstract'),
                'authors': paper.get('authors', [])
            }
            
            embedded_count += 1
        
        logger.info(f"Indexed {embedded_count} papers")
    
    def _get_stored_embedding(self, paper_id: str) -> Optional[np.ndarray]:
        """Get stored embedding from database."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT embedding FROM paper_embeddings WHERE paper_id = ?",
                (paper_id,)
            ).fetchone()
            
            if row and row['embedding']:
                import json
                return np.array(json.loads(row['embedding']))
        return None
    
    def _store_embedding(self, paper_id: str, embedding: np.ndarray):
        """Store embedding in database."""
        import json
        embedding_json = json.dumps(embedding.tolist())
        
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO paper_embeddings 
                   (paper_id, embedding, model, created_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (paper_id, embedding_json, self.embeddings.model_name)
            )
    
    def search(
        self,
        query: str,
        limit: int = 20,
        min_score: float = 0.0,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        require_abstract: bool = False
    ) -> List[SearchResult]:
        """
        Search papers by semantic similarity to query.
        
        Args:
            query: Natural language query
            limit: Maximum results to return
            min_score: Minimum similarity score (0-1)
            year_min: Filter by minimum year
            year_max: Filter by maximum year
            require_abstract: Only return papers with abstracts
            
        Returns:
            List of SearchResult ordered by relevance
        """
        self._build_index()
        
        if not self._paper_index:
            logger.warning("No papers indexed")
            return []
        
        # Embed query
        query_embedding = self.embeddings.embed(query)
        
        # Score all papers
        scores = []
        for paper_id, paper_embedding in self._paper_index.items():
            similarity = self._cosine_similarity(query_embedding, paper_embedding)
            
            if similarity < min_score:
                continue
            
            metadata = self._paper_metadata.get(paper_id, {})
            
            # Apply filters
            if year_min and metadata.get('year') and metadata['year'] < year_min:
                continue
            if year_max and metadata.get('year') and metadata['year'] > year_max:
                continue
            if require_abstract and not metadata.get('abstract'):
                continue
            
            scores.append((paper_id, similarity, metadata))
        
        # Sort by score
        scores.sort(key=lambda x: -x[1])
        
        # Build results
        results = []
        for paper_id, score, metadata in scores[:limit]:
            results.append(SearchResult(
                paper_id=paper_id,
                title=metadata.get('title', 'Untitled'),
                score=float(score),
                doi=metadata.get('doi'),
                year=metadata.get('year'),
                abstract=metadata.get('abstract'),
                authors=metadata.get('authors', [])
            ))
        
        return results
    
    def find_similar(
        self,
        paper_id: str,
        limit: int = 10,
        exclude_self: bool = True
    ) -> List[SearchResult]:
        """
        Find papers similar to a given paper.
        
        Args:
            paper_id: ID of source paper
            limit: Maximum results
            exclude_self: Exclude the source paper from results
            
        Returns:
            List of similar papers
        """
        self._build_index()
        
        if paper_id not in self._paper_index:
            logger.warning(f"Paper {paper_id} not in index")
            return []
        
        source_embedding = self._paper_index[paper_id]
        
        # Score all papers
        scores = []
        for pid, embedding in self._paper_index.items():
            if exclude_self and pid == paper_id:
                continue
            
            similarity = self._cosine_similarity(source_embedding, embedding)
            metadata = self._paper_metadata.get(pid, {})
            scores.append((pid, similarity, metadata))
        
        # Sort by score
        scores.sort(key=lambda x: -x[1])
        
        # Build results
        results = []
        for pid, score, metadata in scores[:limit]:
            results.append(SearchResult(
                paper_id=pid,
                title=metadata.get('title', 'Untitled'),
                score=float(score),
                doi=metadata.get('doi'),
                year=metadata.get('year'),
                abstract=metadata.get('abstract'),
                authors=metadata.get('authors', [])
            ))
        
        return results
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if isinstance(a, list):
            a = np.array(a)
        if isinstance(b, list):
            b = np.array(b)
        
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot / (norm_a * norm_b))
    
    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the search index."""
        self._build_index()
        
        return {
            'papers_indexed': len(self._paper_index),
            'papers_with_abstract': sum(
                1 for m in self._paper_metadata.values() if m.get('abstract')
            ),
            'embedding_dimension': self.embeddings.dimension if self._paper_index else 0
        }


def search_papers(database, query: str, limit: int = 20, **kwargs) -> List[SearchResult]:
    """Convenience function for semantic search."""
    searcher = SemanticSearch(database)
    return searcher.search(query, limit=limit, **kwargs)


def find_similar_papers(database, paper_id: str, limit: int = 10) -> List[SearchResult]:
    """Convenience function to find similar papers."""
    searcher = SemanticSearch(database)
    return searcher.find_similar(paper_id, limit=limit)
