# Version: 3.2.2
"""
Article Finder v3.2 - Expansion Scorer
Scores discovered papers against the taxonomy to filter expansion.

The key insight: we don't want to expand into every paper that cites or is cited by
our corpus. We want to stay within the neuroarchitecture domain. This module scores
discovered papers using their title + abstract against our taxonomy centroids, and
only queues papers that meet a relevance threshold.
"""

import logging
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ScoredPaper:
    """A discovered paper with its taxonomy relevance score."""
    paper_id: str
    doi: Optional[str]
    title: Optional[str]
    authors: List[str]
    year: Optional[int]
    abstract: Optional[str]
    
    # Scoring results
    relevance_score: float = 0.0
    top_facets: List[Tuple[str, float]] = field(default_factory=list)
    decision: str = "pending"  # pending, queue, reject
    
    # Discovery metadata
    discovered_from: Optional[str] = None
    discovery_type: str = "citation"  # citation, reference, search
    discovery_depth: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'paper_id': self.paper_id,
            'doi': self.doi,
            'title': self.title,
            'authors': self.authors,
            'year': self.year,
            'abstract': self.abstract,
            'relevance_score': self.relevance_score,
            'top_facets': self.top_facets,
            'decision': self.decision,
            'discovered_from': self.discovered_from,
            'discovery_type': self.discovery_type,
            'discovery_depth': self.discovery_depth
        }


class ExpansionScorer:
    """
    Scores discovered papers against the taxonomy to determine relevance.
    
    Uses the same embedding + centroid approach as the main classifier,
    but optimized for quick scoring of many candidates.
    """
    
    # Priority facets - papers matching these score higher
    PRIORITY_FACETS = ['environmental_factors', 'outcomes']
    
    # Facets that indicate core relevance
    CORE_FACETS = ['environmental_factors', 'outcomes', 'settings', 'methodology']
    
    def __init__(self, database, embedding_service=None):
        """
        Args:
            database: Database with taxonomy centroids
            embedding_service: Embedding service (lazy-loaded if None)
        """
        self.db = database
        self._embeddings = embedding_service
        self._centroids = None
        self._facet_weights = None
        
    @property
    def embeddings(self):
        """Lazy-load embedding service."""
        if self._embeddings is None:
            from triage.embeddings import get_embedding_service
            self._embeddings = get_embedding_service()
        return self._embeddings
    
    @property
    def centroids(self) -> Dict[str, Any]:
        """Load taxonomy centroids from database."""
        if self._centroids is None:
            self._centroids = {}
            nodes = self.db.get_taxonomy_nodes()
            for node in nodes:
                if node.get('centroid'):
                    self._centroids[node['id']] = {
                        'centroid': node['centroid'],
                        'facet': node.get('facet'),
                        'level': node.get('level', 1)
                    }
            logger.info(f"Loaded {len(self._centroids)} taxonomy centroids")
        return self._centroids
    
    def score_paper(
        self,
        title: Optional[str],
        abstract: Optional[str],
        min_text_length: int = 20
    ) -> Tuple[float, List[Tuple[str, float]]]:
        """
        Score a paper against the taxonomy.
        
        Args:
            title: Paper title
            abstract: Paper abstract (optional but improves accuracy)
            min_text_length: Minimum text length to attempt scoring
            
        Returns:
            (overall_score, [(facet_id, score), ...])
        """
        # Build text to embed
        text_parts = []
        if title:
            text_parts.append(title)
        if abstract:
            text_parts.append(abstract)
        
        text = ' '.join(text_parts)
        
        if len(text) < min_text_length:
            return 0.0, []
        
        # Get embedding
        try:
            embedding = self.embeddings.embed(text)
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            return 0.0, []
        
        # Score against all centroids
        scores_by_facet = {}
        
        for node_id, node_info in self.centroids.items():
            centroid = node_info['centroid']
            facet = node_info.get('facet', 'unknown')
            
            # Cosine similarity
            similarity = self._cosine_similarity(embedding, centroid)
            
            # Track best score per facet
            if facet not in scores_by_facet or similarity > scores_by_facet[facet]:
                scores_by_facet[facet] = similarity
        
        if not scores_by_facet:
            return 0.0, []
        
        # Calculate overall score with facet weighting
        # Priority facets count more
        weighted_sum = 0.0
        weight_total = 0.0
        
        for facet, score in scores_by_facet.items():
            if facet in self.PRIORITY_FACETS:
                weight = 2.0
            elif facet in self.CORE_FACETS:
                weight = 1.5
            else:
                weight = 1.0
            
            weighted_sum += score * weight
            weight_total += weight
        
        overall_score = weighted_sum / weight_total if weight_total > 0 else 0.0
        
        # Sort facets by score
        top_facets = sorted(scores_by_facet.items(), key=lambda x: -x[1])[:5]
        
        return overall_score, top_facets
    
    def score_candidate(self, candidate: Dict[str, Any]) -> ScoredPaper:
        """
        Score a candidate paper from citation discovery.
        
        Args:
            candidate: Dict with doi, title, abstract, etc.
            
        Returns:
            ScoredPaper with relevance score and decision
        """
        scored = ScoredPaper(
            paper_id=candidate.get('paper_id', f"doi:{candidate.get('doi', 'unknown')}"),
            doi=candidate.get('doi'),
            title=candidate.get('title'),
            authors=candidate.get('authors', []),
            year=candidate.get('year'),
            abstract=candidate.get('abstract'),
            discovered_from=candidate.get('discovered_from'),
            discovery_type=candidate.get('discovery_type', 'citation'),
            discovery_depth=candidate.get('discovery_depth', 0)
        )
        
        # Score against taxonomy
        score, top_facets = self.score_paper(scored.title, scored.abstract)
        
        scored.relevance_score = score
        scored.top_facets = top_facets
        
        return scored
    
    def batch_score(
        self,
        candidates: List[Dict[str, Any]],
        threshold: float = 0.3
    ) -> Tuple[List[ScoredPaper], List[ScoredPaper]]:
        """
        Score a batch of candidates and split into queue/reject.
        
        Args:
            candidates: List of candidate papers
            threshold: Minimum relevance score to queue
            
        Returns:
            (papers_to_queue, papers_rejected)
        """
        to_queue = []
        rejected = []
        
        for candidate in candidates:
            scored = self.score_candidate(candidate)
            
            if scored.relevance_score >= threshold:
                scored.decision = "queue"
                to_queue.append(scored)
            else:
                scored.decision = "reject"
                rejected.append(scored)
        
        # Sort queue by relevance
        to_queue.sort(key=lambda x: -x.relevance_score)
        
        logger.info(f"Batch scored {len(candidates)}: {len(to_queue)} queued, {len(rejected)} rejected")
        
        return to_queue, rejected
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot / (norm_a * norm_b)


class RelevanceFilter:
    """
    Configurable relevance filter for expansion decisions.
    """
    
    def __init__(
        self,
        threshold: float = 0.35,
        require_abstract: bool = False,
        max_depth: int = 3,
        priority_boost: float = 0.1
    ):
        """
        Args:
            threshold: Base relevance threshold
            require_abstract: If True, reject papers without abstracts
            max_depth: Maximum citation depth to allow
            priority_boost: Boost for papers with priority facet matches
        """
        self.threshold = threshold
        self.require_abstract = require_abstract
        self.max_depth = max_depth
        self.priority_boost = priority_boost
    
    def should_queue(self, scored: ScoredPaper) -> Tuple[bool, str]:
        """
        Decide whether to queue a scored paper.
        
        Returns:
            (should_queue, reason)
        """
        # Depth check
        if scored.discovery_depth > self.max_depth:
            return False, f"Exceeds max depth ({scored.discovery_depth} > {self.max_depth})"
        
        # Abstract requirement
        if self.require_abstract and not scored.abstract:
            return False, "No abstract available"
        
        # Calculate effective threshold
        effective_threshold = self.threshold
        
        # Boost if matches priority facets
        if scored.top_facets:
            priority_matches = [f for f, s in scored.top_facets 
                              if f in ExpansionScorer.PRIORITY_FACETS and s > 0.4]
            if priority_matches:
                effective_threshold -= self.priority_boost
        
        # Score check
        if scored.relevance_score < effective_threshold:
            return False, f"Below threshold ({scored.relevance_score:.2f} < {effective_threshold:.2f})"
        
        return True, f"Relevant ({scored.relevance_score:.2f})"
    
    def filter_batch(
        self,
        scored_papers: List[ScoredPaper]
    ) -> Tuple[List[ScoredPaper], List[Tuple[ScoredPaper, str]]]:
        """
        Filter a batch of scored papers.
        
        Returns:
            (accepted, [(rejected, reason), ...])
        """
        accepted = []
        rejected = []
        
        for paper in scored_papers:
            should_add, reason = self.should_queue(paper)
            if should_add:
                paper.decision = "queue"
                accepted.append(paper)
            else:
                paper.decision = "reject"
                rejected.append((paper, reason))
        
        return accepted, rejected
