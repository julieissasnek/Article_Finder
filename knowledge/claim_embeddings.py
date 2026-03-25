# Version: 3.2.2
"""
Article Finder v3.2.2 - Claim Embeddings
Embed and index extracted claims for semantic search and deduplication.

Enables:
- Searching claims by meaning ("reduces stress")
- Finding duplicate/similar claims across papers
- Clustering claims by topic
"""

import logging
import json
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ClaimMatch:
    """A claim search/similarity result."""
    claim_id: str
    paper_id: str
    statement: str
    score: float
    claim_type: Optional[str] = None
    paper_title: Optional[str] = None
    constructs: Optional[Dict] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'claim_id': self.claim_id,
            'paper_id': self.paper_id,
            'statement': self.statement,
            'score': self.score,
            'claim_type': self.claim_type,
            'paper_title': self.paper_title
        }


@dataclass
class ClaimCluster:
    """A cluster of semantically similar claims."""
    cluster_id: int
    centroid: np.ndarray
    claims: List[str]  # claim_ids
    representative_statement: str
    size: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cluster_id': self.cluster_id,
            'representative': self.representative_statement,
            'size': self.size,
            'claim_ids': self.claims
        }


@dataclass
class DuplicatePair:
    """A pair of potentially duplicate claims."""
    claim_id_1: str
    claim_id_2: str
    similarity: float
    statement_1: str
    statement_2: str
    paper_id_1: str
    paper_id_2: str
    relationship: str = "similar"  # similar, duplicate, contradiction
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'claim_1': self.claim_id_1,
            'claim_2': self.claim_id_2,
            'similarity': self.similarity,
            'relationship': self.relationship,
            'statements': [self.statement_1, self.statement_2]
        }


class ClaimEmbeddings:
    """
    Embed and index claims for semantic operations.
    
    Provides:
    - Claim search by semantic similarity
    - Similar claim detection (deduplication)
    - Claim clustering by topic
    """
    
    # Thresholds
    DUPLICATE_THRESHOLD = 0.92  # Very high similarity = likely duplicate
    SIMILAR_THRESHOLD = 0.75   # Moderate similarity = related findings
    
    def __init__(self, database, embedding_service=None):
        """
        Args:
            database: Database instance
            embedding_service: Optional embedding service
        """
        self.db = database
        self._embeddings = embedding_service
        self._claim_index = None  # claim_id -> embedding
        self._claim_metadata = None  # claim_id -> metadata
    
    @property
    def embeddings(self):
        """Lazy-load embedding service."""
        if self._embeddings is None:
            from triage.embeddings import get_embedding_service
            self._embeddings = get_embedding_service()
        return self._embeddings
    
    def _load_claims(self) -> List[Dict]:
        """Load all claims from database."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT c.*, p.title as paper_title 
                   FROM claims c
                   LEFT JOIN papers p ON c.paper_id = p.paper_id"""
            ).fetchall()
            return [self.db._row_to_dict(row) for row in rows]
    
    def _build_index(self, force_rebuild: bool = False):
        """Build claim embedding index."""
        if self._claim_index is not None and not force_rebuild:
            return
        
        logger.info("Building claim embedding index...")
        
        self._claim_index = {}
        self._claim_metadata = {}
        
        claims = self._load_claims()
        
        if not claims:
            logger.warning("No claims found in database")
            return
        
        for claim in claims:
            claim_id = claim.get('claim_id')
            statement = claim.get('statement', '')
            
            if not claim_id or not statement:
                continue
            
            # Check for stored embedding
            stored = self._get_stored_embedding(claim_id)
            
            if stored is not None:
                self._claim_index[claim_id] = stored
            else:
                # Compute embedding
                try:
                    embedding = self.embeddings.embed(statement)
                    self._claim_index[claim_id] = embedding
                    self._store_embedding(claim_id, embedding)
                except Exception as e:
                    logger.warning(f"Failed to embed claim {claim_id}: {e}")
                    continue
            
            # Store metadata
            self._claim_metadata[claim_id] = {
                'statement': statement,
                'paper_id': claim.get('paper_id'),
                'paper_title': claim.get('paper_title'),
                'claim_type': claim.get('claim_type'),
                'constructs': self._parse_json(claim.get('constructs'))
            }
        
        logger.info(f"Indexed {len(self._claim_index)} claims")
    
    def _parse_json(self, value) -> Optional[Dict]:
        """Parse JSON string if needed."""
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except:
            return None
    
    def _get_stored_embedding(self, claim_id: str) -> Optional[np.ndarray]:
        """Get stored claim embedding."""
        with self.db.connection() as conn:
            # Check if claim_embeddings table exists
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='claim_embeddings'"
            ).fetchone()
            
            if not table_exists:
                self._create_claim_embeddings_table(conn)
                return None
            
            row = conn.execute(
                "SELECT embedding FROM claim_embeddings WHERE claim_id = ?",
                (claim_id,)
            ).fetchone()
            
            if row and row['embedding']:
                return np.array(json.loads(row['embedding']))
        return None
    
    def _store_embedding(self, claim_id: str, embedding: np.ndarray):
        """Store claim embedding."""
        embedding_json = json.dumps(embedding.tolist())
        
        with self.db.connection() as conn:
            # Ensure table exists
            self._create_claim_embeddings_table(conn)
            
            conn.execute(
                """INSERT OR REPLACE INTO claim_embeddings 
                   (claim_id, embedding, model, created_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (claim_id, embedding_json, self.embeddings.model_name)
            )
    
    def _create_claim_embeddings_table(self, conn):
        """Create claim embeddings table if needed."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_embeddings (
                claim_id TEXT PRIMARY KEY,
                embedding TEXT,
                model TEXT,
                created_at TEXT
            )
        """)
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity."""
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
    
    def search(
        self,
        query: str,
        limit: int = 20,
        min_score: float = 0.0,
        claim_type: Optional[str] = None
    ) -> List[ClaimMatch]:
        """
        Search claims by semantic similarity.
        
        Args:
            query: Natural language query
            limit: Maximum results
            min_score: Minimum similarity score
            claim_type: Filter by claim type (causal, associational, etc.)
            
        Returns:
            List of ClaimMatch ordered by relevance
        """
        self._build_index()
        
        if not self._claim_index:
            return []
        
        query_embedding = self.embeddings.embed(query)
        
        scores = []
        for claim_id, claim_embedding in self._claim_index.items():
            similarity = self._cosine_similarity(query_embedding, claim_embedding)
            
            if similarity < min_score:
                continue
            
            metadata = self._claim_metadata.get(claim_id, {})
            
            if claim_type and metadata.get('claim_type') != claim_type:
                continue
            
            scores.append((claim_id, similarity, metadata))
        
        scores.sort(key=lambda x: -x[1])
        
        results = []
        for claim_id, score, metadata in scores[:limit]:
            results.append(ClaimMatch(
                claim_id=claim_id,
                paper_id=metadata.get('paper_id', ''),
                statement=metadata.get('statement', ''),
                score=float(score),
                claim_type=metadata.get('claim_type'),
                paper_title=metadata.get('paper_title'),
                constructs=metadata.get('constructs')
            ))
        
        return results
    
    def find_similar(
        self,
        claim_id: str,
        limit: int = 10,
        min_score: float = 0.5
    ) -> List[ClaimMatch]:
        """Find claims similar to a given claim."""
        self._build_index()
        
        if claim_id not in self._claim_index:
            logger.warning(f"Claim {claim_id} not in index")
            return []
        
        source_embedding = self._claim_index[claim_id]
        source_paper = self._claim_metadata.get(claim_id, {}).get('paper_id')
        
        scores = []
        for cid, embedding in self._claim_index.items():
            if cid == claim_id:
                continue
            
            similarity = self._cosine_similarity(source_embedding, embedding)
            
            if similarity < min_score:
                continue
            
            metadata = self._claim_metadata.get(cid, {})
            scores.append((cid, similarity, metadata))
        
        scores.sort(key=lambda x: -x[1])
        
        results = []
        for cid, score, metadata in scores[:limit]:
            results.append(ClaimMatch(
                claim_id=cid,
                paper_id=metadata.get('paper_id', ''),
                statement=metadata.get('statement', ''),
                score=float(score),
                claim_type=metadata.get('claim_type'),
                paper_title=metadata.get('paper_title')
            ))
        
        return results
    
    def find_duplicates(
        self,
        threshold: float = None
    ) -> List[DuplicatePair]:
        """
        Find potentially duplicate claims across papers.
        
        Returns pairs of claims with similarity above threshold.
        """
        self._build_index()
        
        if not self._claim_index:
            return []
        
        threshold = threshold or self.DUPLICATE_THRESHOLD
        
        claim_ids = list(self._claim_index.keys())
        duplicates = []
        seen_pairs: Set[Tuple[str, str]] = set()
        
        for i, cid1 in enumerate(claim_ids):
            emb1 = self._claim_index[cid1]
            meta1 = self._claim_metadata.get(cid1, {})
            
            for cid2 in claim_ids[i+1:]:
                # Skip same paper
                meta2 = self._claim_metadata.get(cid2, {})
                if meta1.get('paper_id') == meta2.get('paper_id'):
                    continue
                
                # Skip if already seen
                pair_key = tuple(sorted([cid1, cid2]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                
                emb2 = self._claim_index[cid2]
                similarity = self._cosine_similarity(emb1, emb2)
                
                if similarity >= threshold:
                    duplicates.append(DuplicatePair(
                        claim_id_1=cid1,
                        claim_id_2=cid2,
                        similarity=float(similarity),
                        statement_1=meta1.get('statement', ''),
                        statement_2=meta2.get('statement', ''),
                        paper_id_1=meta1.get('paper_id', ''),
                        paper_id_2=meta2.get('paper_id', ''),
                        relationship='duplicate' if similarity > 0.95 else 'similar'
                    ))
        
        duplicates.sort(key=lambda x: -x.similarity)
        return duplicates
    
    def cluster_claims(
        self,
        n_clusters: int = 10,
        min_cluster_size: int = 2
    ) -> List[ClaimCluster]:
        """
        Cluster claims by semantic similarity.
        
        Uses simple k-means clustering.
        """
        self._build_index()
        
        if len(self._claim_index) < n_clusters:
            logger.warning("Not enough claims to cluster")
            return []
        
        from sklearn.cluster import KMeans
        
        claim_ids = list(self._claim_index.keys())
        embeddings = np.array([self._claim_index[cid] for cid in claim_ids])
        
        # Cluster
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)
        
        # Build cluster objects
        clusters = []
        for cluster_id in range(n_clusters):
            mask = labels == cluster_id
            cluster_claim_ids = [cid for cid, m in zip(claim_ids, mask) if m]
            
            if len(cluster_claim_ids) < min_cluster_size:
                continue
            
            # Find claim closest to centroid
            centroid = kmeans.cluster_centers_[cluster_id]
            best_idx = None
            best_sim = -1
            for idx, cid in enumerate(cluster_claim_ids):
                sim = self._cosine_similarity(centroid, self._claim_index[cid])
                if sim > best_sim:
                    best_sim = sim
                    best_idx = cid
            
            representative = self._claim_metadata.get(best_idx, {}).get('statement', '')
            
            clusters.append(ClaimCluster(
                cluster_id=cluster_id,
                centroid=centroid,
                claims=cluster_claim_ids,
                representative_statement=representative[:200],
                size=len(cluster_claim_ids)
            ))
        
        clusters.sort(key=lambda x: -x.size)
        return clusters
    
    def get_stats(self) -> Dict[str, Any]:
        """Get claim embedding stats."""
        self._build_index()
        
        claim_types = defaultdict(int)
        for meta in self._claim_metadata.values():
            claim_types[meta.get('claim_type', 'unknown')] += 1
        
        return {
            'claims_indexed': len(self._claim_index),
            'by_type': dict(claim_types),
            'embedding_dimension': self.embeddings.dimension if self._claim_index else 0
        }


def search_claims(database, query: str, limit: int = 20) -> List[ClaimMatch]:
    """Convenience function for claim search."""
    ce = ClaimEmbeddings(database)
    return ce.search(query, limit=limit)


def find_duplicate_claims(database, threshold: float = 0.92) -> List[DuplicatePair]:
    """Convenience function for duplicate detection."""
    ce = ClaimEmbeddings(database)
    return ce.find_duplicates(threshold=threshold)
