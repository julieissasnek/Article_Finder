# Version: 3.2.2
"""
Article Finder v3 - Hierarchical Centroid Classifier
Classifies papers against the multi-tree taxonomy using embedding centroids
"""

import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import json
import pickle
from collections import defaultdict

# Embedding model - can be swapped for different models
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDER_AVAILABLE = True
except ImportError:
    EMBEDDER_AVAILABLE = False
    print("Warning: sentence-transformers not available. Install with: pip install sentence-transformers")


@dataclass
class TaxonomyNode:
    """A node in the taxonomy tree."""
    node_id: str
    name: str
    level: int
    parent_id: Optional[str]
    facet_id: str
    seeds: List[str] = field(default_factory=list)
    centroid: Optional[np.ndarray] = None
    exemplar_papers: List[str] = field(default_factory=list)
    children: List[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    """Result of classifying a paper against the taxonomy."""
    paper_id: str
    scores: Dict[str, float]  # node_id -> score
    top_nodes: List[Tuple[str, float]]  # Top N (node_id, score) pairs
    facet_summary: Dict[str, List[Tuple[str, float]]]  # facet_id -> top nodes in facet
    domain_score: float  # Overall neuroarchitecture relevance
    triage_decision: str  # send_to_eater | review | reject
    triage_reasons: List[str]


class HierarchicalClassifier:
    """
    Classifies papers against a multi-tree taxonomy using embedding centroids.
    
    Each taxonomy node has a centroid computed from:
    1. Seed phrases defined in the taxonomy
    2. Exemplar paper abstracts
    3. Parent centroid (with inheritance weighting)
    """
    
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    
    # Triage thresholds
    DOMAIN_THRESHOLD_ACCEPT = 0.5   # Above this, likely in domain
    DOMAIN_THRESHOLD_REJECT = 0.3   # Below this, likely out of domain
    L2_THRESHOLD_STRONG = 0.7       # Strong L2 match
    L3_THRESHOLD_STRONG = 0.65      # Strong L3 match
    
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: Optional[Path] = None
    ):
        """
        Initialize the classifier.
        
        Args:
            model_name: Name of the sentence-transformers model
            cache_dir: Directory for caching embeddings
        """
        self.model_name = model_name
        self.cache_dir = cache_dir
        
        if EMBEDDER_AVAILABLE:
            self.embedder = SentenceTransformer(model_name)
            self.embedding_dim = self.embedder.get_sentence_embedding_dimension()
        else:
            self.embedder = None
            self.embedding_dim = 384  # Default for MiniLM
        
        self.nodes: Dict[str, TaxonomyNode] = {}
        self.facets: Dict[str, List[str]] = defaultdict(list)  # facet_id -> node_ids
        self.root_nodes: List[str] = []
        
        # Domain-level centroid (for overall neuroarchitecture relevance)
        self.domain_centroid: Optional[np.ndarray] = None
        self.domain_seeds = [
            "neuroarchitecture",
            "cognitive architecture",
            "environmental psychology",
            "built environment and human behavior",
            "architecture and wellbeing",
            "building design affects cognition",
            "space affects mood and emotion",
            "indoor environment quality and health",
            "biophilic design",
            "evidence-based design",
            "healing environments",
            "architecture neuroscience",
            "spatial cognition",
            "environmental factors human outcomes"
        ]
    
    def load_taxonomy(self, taxonomy_data: Dict) -> None:
        """
        Load taxonomy from parsed YAML data.
        
        Args:
            taxonomy_data: Parsed taxonomy YAML
        """
        self.nodes.clear()
        self.facets.clear()
        self.root_nodes.clear()
        
        # Load each facet tree
        facet_keys = [
            'environmental_factors', 'outcomes', 'subjects', 'settings',
            'methodology', 'modality', 'cross_modal', 'theory', 'evidence_strength'
        ]
        
        for facet_key in facet_keys:
            if facet_key in taxonomy_data:
                self._load_nodes_recursive(taxonomy_data[facet_key], facet_key, None)
        
        print(f"Loaded {len(self.nodes)} taxonomy nodes across {len(self.facets)} facets")
    
    def _load_nodes_recursive(
        self,
        nodes: List[Dict],
        facet_id: str,
        parent_id: Optional[str]
    ) -> None:
        """Recursively load taxonomy nodes."""
        for node_data in nodes:
            node_id = node_data['id']
            
            node = TaxonomyNode(
                node_id=node_id,
                name=node_data['name'],
                level=node_data.get('level', 0),
                parent_id=parent_id,
                facet_id=facet_id,
                seeds=node_data.get('seeds', [])
            )
            
            self.nodes[node_id] = node
            self.facets[facet_id].append(node_id)
            
            if parent_id is None:
                self.root_nodes.append(node_id)
            else:
                # Add to parent's children
                if parent_id in self.nodes:
                    self.nodes[parent_id].children.append(node_id)
            
            # Recurse
            if 'children' in node_data:
                self._load_nodes_recursive(node_data['children'], facet_id, node_id)
    
    def build_centroids(
        self,
        paper_abstracts: Optional[Dict[str, str]] = None,
        node_exemplars: Optional[Dict[str, List[str]]] = None,
        parent_weight: float = 0.3
    ) -> None:
        """
        Build centroid embeddings for all taxonomy nodes.
        
        Args:
            paper_abstracts: Dict of paper_id -> abstract text
            node_exemplars: Dict of node_id -> list of paper_ids as exemplars
            parent_weight: Weight for parent centroid inheritance (0-1)
        """
        if not EMBEDDER_AVAILABLE:
            raise RuntimeError("sentence-transformers required for building centroids")
        
        paper_abstracts = paper_abstracts or {}
        node_exemplars = node_exemplars or {}
        
        # Build domain centroid first
        domain_embeddings = self.embedder.encode(self.domain_seeds)
        self.domain_centroid = np.mean(domain_embeddings, axis=0)
        self.domain_centroid = self.domain_centroid / np.linalg.norm(self.domain_centroid)
        
        # Process nodes level by level (so parents are computed before children)
        max_level = max(n.level for n in self.nodes.values()) if self.nodes else 0
        
        for level in range(max_level + 1):
            level_nodes = [n for n in self.nodes.values() if n.level == level]
            
            for node in level_nodes:
                self._compute_node_centroid(
                    node, paper_abstracts, node_exemplars, parent_weight
                )
        
        print(f"Built centroids for {sum(1 for n in self.nodes.values() if n.centroid is not None)} nodes")
    
    def _compute_node_centroid(
        self,
        node: TaxonomyNode,
        paper_abstracts: Dict[str, str],
        node_exemplars: Dict[str, List[str]],
        parent_weight: float
    ) -> None:
        """Compute centroid for a single node."""
        embeddings = []
        
        # 1. Embed seed phrases
        if node.seeds:
            seed_embeddings = self.embedder.encode(node.seeds)
            embeddings.extend(seed_embeddings)
        
        # 2. Embed exemplar paper abstracts
        exemplar_ids = node_exemplars.get(node.node_id, [])
        for paper_id in exemplar_ids:
            if paper_id in paper_abstracts:
                abstract = paper_abstracts[paper_id]
                if abstract:
                    emb = self.embedder.encode([abstract])[0]
                    embeddings.append(emb)
                    node.exemplar_papers.append(paper_id)
        
        if not embeddings:
            # No seeds or exemplars - inherit from parent if available
            if node.parent_id and node.parent_id in self.nodes:
                parent = self.nodes[node.parent_id]
                if parent.centroid is not None:
                    node.centroid = parent.centroid.copy()
            return
        
        # Compute raw centroid
        raw_centroid = np.mean(embeddings, axis=0)
        
        # 3. Blend with parent centroid if available
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            if parent.centroid is not None:
                # Weight towards the distinctive part of this node
                raw_centroid = (1 - parent_weight) * raw_centroid + parent_weight * parent.centroid
        
        # Normalize
        node.centroid = raw_centroid / np.linalg.norm(raw_centroid)
    
    def classify_paper(
        self,
        paper_id: str,
        title: str,
        abstract: Optional[str] = None,
        top_n: int = 10
    ) -> ClassificationResult:
        """
        Classify a paper against the taxonomy.
        
        Args:
            paper_id: Paper identifier
            title: Paper title
            abstract: Paper abstract (optional but recommended)
            top_n: Number of top nodes to return per facet
            
        Returns:
            ClassificationResult with scores and triage decision
        """
        if not EMBEDDER_AVAILABLE:
            raise RuntimeError("sentence-transformers required for classification")
        
        # Combine title and abstract
        text = title
        if abstract:
            text = f"{title}. {abstract}"
        
        # Embed the paper
        paper_embedding = self.embedder.encode([text])[0]
        paper_embedding = paper_embedding / np.linalg.norm(paper_embedding)
        
        # Compute domain score
        domain_score = 0.0
        if self.domain_centroid is not None:
            domain_score = float(np.dot(paper_embedding, self.domain_centroid))
        
        # Compute scores against all nodes
        scores = {}
        for node_id, node in self.nodes.items():
            if node.centroid is not None:
                score = float(np.dot(paper_embedding, node.centroid))
                scores[node_id] = max(0, score)  # Clip negative scores
        
        # Get top nodes overall
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_nodes = sorted_scores[:top_n]
        
        # Get top nodes per facet
        facet_summary = {}
        for facet_id, node_ids in self.facets.items():
            facet_scores = [(nid, scores.get(nid, 0)) for nid in node_ids]
            facet_scores.sort(key=lambda x: x[1], reverse=True)
            facet_summary[facet_id] = facet_scores[:3]  # Top 3 per facet
        
        # Make triage decision
        triage_decision, triage_reasons = self._make_triage_decision(
            domain_score, scores, facet_summary
        )
        
        return ClassificationResult(
            paper_id=paper_id,
            scores=scores,
            top_nodes=top_nodes,
            facet_summary=facet_summary,
            domain_score=domain_score,
            triage_decision=triage_decision,
            triage_reasons=triage_reasons
        )
    
    def _make_triage_decision(
        self,
        domain_score: float,
        scores: Dict[str, float],
        facet_summary: Dict[str, List[Tuple[str, float]]]
    ) -> Tuple[str, List[str]]:
        """
        Make a triage decision based on classification scores.
        
        Returns:
            (decision, reasons) tuple
        """
        reasons = []
        
        # Check domain relevance
        if domain_score < self.DOMAIN_THRESHOLD_REJECT:
            reasons.append(f"Low domain relevance: {domain_score:.2f}")
            return 'reject', reasons
        
        reasons.append(f"Domain score: {domain_score:.2f}")
        
        # Check for strong L2/L3 matches
        l2_matches = []
        l3_matches = []
        
        for node_id, score in scores.items():
            node = self.nodes.get(node_id)
            if node:
                if node.level == 2 and score >= self.L2_THRESHOLD_STRONG:
                    l2_matches.append((node_id, score))
                elif node.level == 3 and score >= self.L3_THRESHOLD_STRONG:
                    l3_matches.append((node_id, score))
        
        # Strong L3 match -> definitely process
        if l3_matches:
            top_l3 = sorted(l3_matches, key=lambda x: x[1], reverse=True)[:3]
            reasons.append(f"Strong L3 matches: {[f'{n}:{s:.2f}' for n,s in top_l3]}")
            return 'send_to_eater', reasons
        
        # Strong L2 match -> process
        if l2_matches:
            top_l2 = sorted(l2_matches, key=lambda x: x[1], reverse=True)[:3]
            reasons.append(f"Strong L2 matches: {[f'{n}:{s:.2f}' for n,s in top_l2]}")
            return 'send_to_eater', reasons
        
        # In domain but no strong matches -> review
        if domain_score >= self.DOMAIN_THRESHOLD_ACCEPT:
            reasons.append("In domain but no strong facet matches")
            return 'review', reasons
        
        # Marginal domain score
        reasons.append(f"Marginal domain score: {domain_score:.2f}")
        return 'review', reasons
    
    def classify_batch(
        self,
        papers: List[Dict[str, Any]],
        title_field: str = 'title',
        abstract_field: str = 'abstract',
        id_field: str = 'paper_id'
    ) -> List[ClassificationResult]:
        """
        Classify multiple papers.
        
        Args:
            papers: List of paper dicts
            title_field: Key for title in paper dict
            abstract_field: Key for abstract in paper dict
            id_field: Key for paper_id in paper dict
            
        Returns:
            List of ClassificationResults
        """
        results = []
        
        for paper in papers:
            result = self.classify_paper(
                paper_id=paper.get(id_field, 'unknown'),
                title=paper.get(title_field, ''),
                abstract=paper.get(abstract_field)
            )
            results.append(result)
        
        return results
    
    def save_centroids(self, path: Path) -> None:
        """Save computed centroids to file."""
        data = {
            'model_name': self.model_name,
            'domain_centroid': self.domain_centroid.tolist() if self.domain_centroid is not None else None,
            'nodes': {}
        }
        
        for node_id, node in self.nodes.items():
            data['nodes'][node_id] = {
                'centroid': node.centroid.tolist() if node.centroid is not None else None,
                'exemplar_papers': node.exemplar_papers
            }
        
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def load_centroids(self, path: Path) -> None:
        """Load precomputed centroids from file."""
        with open(path, 'r') as f:
            data = json.load(f)
        
        if data.get('model_name') != self.model_name:
            print(f"Warning: Centroid model ({data.get('model_name')}) differs from current ({self.model_name})")
        
        if data.get('domain_centroid'):
            self.domain_centroid = np.array(data['domain_centroid'])
        
        for node_id, node_data in data.get('nodes', {}).items():
            if node_id in self.nodes:
                if node_data.get('centroid'):
                    self.nodes[node_id].centroid = np.array(node_data['centroid'])
                self.nodes[node_id].exemplar_papers = node_data.get('exemplar_papers', [])
    
    def get_node_stats(self) -> Dict[str, Any]:
        """Get statistics about the taxonomy."""
        total = len(self.nodes)
        with_centroids = sum(1 for n in self.nodes.values() if n.centroid is not None)
        with_seeds = sum(1 for n in self.nodes.values() if n.seeds)
        with_exemplars = sum(1 for n in self.nodes.values() if n.exemplar_papers)
        
        by_level = defaultdict(int)
        for node in self.nodes.values():
            by_level[node.level] += 1
        
        by_facet = {fid: len(nodes) for fid, nodes in self.facets.items()}
        
        return {
            'total_nodes': total,
            'with_centroids': with_centroids,
            'with_seeds': with_seeds,
            'with_exemplars': with_exemplars,
            'by_level': dict(by_level),
            'by_facet': by_facet
        }


class TriageFilter:
    """
    High-level triage filter that uses the classifier to filter papers.
    """
    
    def __init__(self, classifier: HierarchicalClassifier, database=None):
        """
        Initialize triage filter.
        
        Args:
            classifier: HierarchicalClassifier instance
            database: Optional Database for storing results
        """
        self.classifier = classifier
        self.db = database
    
    def triage_paper(
        self,
        paper_id: str,
        title: str,
        abstract: Optional[str] = None,
        store_results: bool = True
    ) -> ClassificationResult:
        """
        Triage a single paper.
        
        Args:
            paper_id: Paper identifier
            title: Paper title
            abstract: Paper abstract
            store_results: Whether to store scores in database
            
        Returns:
            ClassificationResult
        """
        result = self.classifier.classify_paper(paper_id, title, abstract)
        
        if store_results and self.db:
            # Store facet scores
            for node_id, score in result.scores.items():
                if score >= 0.3:  # Only store meaningful scores
                    self.db.set_paper_facet_score(paper_id, node_id, score, 'embedding')
            
            # Update paper with triage info
            paper = self.db.get_paper(paper_id)
            if paper:
                paper['triage_score'] = result.domain_score
                paper['triage_decision'] = result.triage_decision
                paper['triage_reasons'] = result.triage_reasons
                
                # Convert top_nodes to facet_scores for AE
                paper['facet_scores'] = {n: s for n, s in result.top_nodes}
                
                self.db.add_paper(paper)
        
        return result
    
    def triage_batch(
        self,
        papers: List[Dict[str, Any]],
        store_results: bool = True
    ) -> Dict[str, List[str]]:
        """
        Triage a batch of papers.
        
        Args:
            papers: List of paper dicts with paper_id, title, abstract
            store_results: Whether to store results
            
        Returns:
            Dict with lists of paper_ids by decision
        """
        decisions = {
            'send_to_eater': [],
            'review': [],
            'reject': []
        }
        
        for paper in papers:
            result = self.triage_paper(
                paper_id=paper.get('paper_id', 'unknown'),
                title=paper.get('title', ''),
                abstract=paper.get('abstract'),
                store_results=store_results
            )
            
            decisions[result.triage_decision].append(result.paper_id)
        
        return decisions
