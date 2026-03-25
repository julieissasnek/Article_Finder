# Version: 3.2.2
"""
Article Finder v3.2.2 - Claim Knowledge Graph
Builds a queryable graph connecting papers, claims, and constructs.

Graph Structure:
- Paper nodes (from papers table)
- Claim nodes (from claims table)  
- Construct nodes (IVs, DVs, mediators, moderators)
- Edges: paper->claim, claim->construct, construct->construct

Enables traversal queries:
- "What affects [outcome]?"
- "What does [IV] affect?"
- "Show all claims about [construct]"
"""

import logging
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class NodeType(Enum):
    PAPER = "paper"
    CLAIM = "claim"
    CONSTRUCT = "construct"


class EdgeType(Enum):
    HAS_CLAIM = "has_claim"           # paper -> claim
    ABOUT_IV = "about_iv"             # claim -> construct (independent variable)
    ABOUT_DV = "about_dv"             # claim -> construct (dependent variable)
    MEDIATES = "mediates"             # claim -> construct (mediator)
    MODERATES = "moderates"           # claim -> construct (moderator)
    AFFECTS = "affects"               # construct -> construct (derived from claims)
    CITES = "cites"                   # paper -> paper


@dataclass
class GraphNode:
    """A node in the knowledge graph."""
    node_id: str
    node_type: NodeType
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.node_id,
            'type': self.node_type.value,
            'label': self.label,
            'properties': self.properties
        }


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""
    source: str
    target: str
    edge_type: EdgeType
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'target': self.target,
            'type': self.edge_type.value,
            'properties': self.properties
        }


@dataclass
class PathResult:
    """A path through the graph."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'nodes': [n.to_dict() for n in self.nodes],
            'edges': [e.to_dict() for e in self.edges]
        }


class ClaimGraph:
    """
    Knowledge graph built from papers and extracted claims.
    
    Uses NetworkX for graph operations but abstracts the interface.
    """
    
    def __init__(self, database, cache_dir: Optional[Path] = None):
        """
        Args:
            database: Database instance
            cache_dir: Directory for graph cache (optional)
        """
        self.db = database
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/cache/graph")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._graph = None
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        
        # Indexes for fast lookup
        self._nodes_by_type: Dict[NodeType, Set[str]] = defaultdict(set)
        self._edges_from: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._edges_to: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._construct_claims: Dict[str, Set[str]] = defaultdict(set)  # construct -> claim_ids
    
    def _get_networkx(self):
        """Get or create NetworkX graph."""
        if self._graph is None:
            try:
                import networkx as nx
                self._graph = nx.DiGraph()
            except ImportError:
                logger.warning("NetworkX not available, using basic graph")
                self._graph = None
        return self._graph
    
    def build(self, force_rebuild: bool = False) -> Dict[str, int]:
        """
        Build the knowledge graph from database.
        
        Returns stats about the built graph.
        """
        cache_path = self.cache_dir / "claim_graph.pkl"
        
        if not force_rebuild and cache_path.exists():
            try:
                self._load_cache(cache_path)
                return self.get_stats()
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
        
        logger.info("Building knowledge graph...")
        
        # Clear existing
        self._nodes.clear()
        self._edges.clear()
        self._nodes_by_type.clear()
        self._edges_from.clear()
        self._edges_to.clear()
        self._construct_claims.clear()
        
        stats = {
            'papers': 0,
            'claims': 0,
            'constructs': 0,
            'edges': 0
        }
        
        # 1. Add paper nodes
        papers = self.db.search_papers(limit=50000)
        for paper in papers:
            paper_id = paper.get('paper_id')
            if not paper_id:
                continue
            
            node = GraphNode(
                node_id=paper_id,
                node_type=NodeType.PAPER,
                label=paper.get('title', 'Untitled')[:100],
                properties={
                    'doi': paper.get('doi'),
                    'year': paper.get('year'),
                    'authors': paper.get('authors', [])
                }
            )
            self._add_node(node)
            stats['papers'] += 1
        
        # 2. Add claims and construct edges
        claims = self._load_claims()
        for claim in claims:
            claim_id = claim.get('claim_id')
            paper_id = claim.get('paper_id')
            
            if not claim_id:
                continue
            
            # Add claim node
            claim_node = GraphNode(
                node_id=claim_id,
                node_type=NodeType.CLAIM,
                label=claim.get('statement', '')[:100],
                properties={
                    'claim_type': claim.get('claim_type'),
                    'statement': claim.get('statement'),
                    'effect_size': self._extract_effect_size(claim),
                    'p_value': self._extract_p_value(claim)
                }
            )
            self._add_node(claim_node)
            stats['claims'] += 1
            
            # Edge: paper -> claim
            if paper_id and paper_id in self._nodes:
                self._add_edge(GraphEdge(
                    source=paper_id,
                    target=claim_id,
                    edge_type=EdgeType.HAS_CLAIM
                ))
                stats['edges'] += 1
            
            # Parse constructs and add edges
            constructs = self._parse_constructs(claim)
            
            for iv in constructs.get('ivs', []):
                construct_id = self._add_construct_node(iv)
                self._add_edge(GraphEdge(
                    source=claim_id,
                    target=construct_id,
                    edge_type=EdgeType.ABOUT_IV,
                    properties={'role': iv.get('role')}
                ))
                self._construct_claims[construct_id].add(claim_id)
                stats['edges'] += 1
            
            for dv in constructs.get('dvs', []):
                construct_id = self._add_construct_node(dv)
                self._add_edge(GraphEdge(
                    source=claim_id,
                    target=construct_id,
                    edge_type=EdgeType.ABOUT_DV,
                    properties={'role': dv.get('role')}
                ))
                self._construct_claims[construct_id].add(claim_id)
                stats['edges'] += 1
            
            for med in constructs.get('mediators', []):
                construct_id = self._add_construct_node(med)
                self._add_edge(GraphEdge(
                    source=claim_id,
                    target=construct_id,
                    edge_type=EdgeType.MEDIATES
                ))
                self._construct_claims[construct_id].add(claim_id)
                stats['edges'] += 1
            
            for mod in constructs.get('moderators', []):
                construct_id = self._add_construct_node(mod)
                self._add_edge(GraphEdge(
                    source=claim_id,
                    target=construct_id,
                    edge_type=EdgeType.MODERATES,
                    properties={'value': mod.get('value')}
                ))
                self._construct_claims[construct_id].add(claim_id)
                stats['edges'] += 1
        
        stats['constructs'] = len(self._nodes_by_type[NodeType.CONSTRUCT])
        
        # 3. Build derived IV->DV edges
        self._build_affects_edges()
        
        # 4. Add citation edges if available
        citation_edges = self._build_citation_edges()
        stats['edges'] += citation_edges
        
        # Save cache
        self._save_cache(cache_path)
        
        logger.info(f"Graph built: {stats}")
        return stats
    
    def _load_claims(self) -> List[Dict]:
        """Load claims from database."""
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM claims").fetchall()
            return [self.db._row_to_dict(row) for row in rows]
    
    def _parse_constructs(self, claim: Dict) -> Dict[str, List[Dict]]:
        """Parse constructs from claim record."""
        constructs_raw = claim.get('constructs')
        
        if not constructs_raw:
            return {'ivs': [], 'dvs': [], 'mediators': [], 'moderators': []}
        
        if isinstance(constructs_raw, str):
            try:
                constructs_raw = json.loads(constructs_raw)
            except:
                return {'ivs': [], 'dvs': [], 'mediators': [], 'moderators': []}
        
        return {
            'ivs': constructs_raw.get('environment_factors', []),
            'dvs': constructs_raw.get('outcomes', []),
            'mediators': constructs_raw.get('mediators', []),
            'moderators': constructs_raw.get('moderators', [])
        }
    
    def _extract_effect_size(self, claim: Dict) -> Optional[float]:
        """Extract effect size from claim."""
        stats = claim.get('statistics')
        if isinstance(stats, str):
            try:
                stats = json.loads(stats)
            except:
                return None
        
        if not stats:
            return None
        
        es = stats.get('effect_size', {})
        if isinstance(es, dict):
            return es.get('value')
        return None
    
    def _extract_p_value(self, claim: Dict) -> Optional[float]:
        """Extract p-value from claim."""
        stats = claim.get('statistics')
        if isinstance(stats, str):
            try:
                stats = json.loads(stats)
            except:
                return None
        
        if not stats:
            return None
        
        return stats.get('p_value')
    
    def _add_node(self, node: GraphNode):
        """Add node to graph."""
        self._nodes[node.node_id] = node
        self._nodes_by_type[node.node_type].add(node.node_id)
        
        nx = self._get_networkx()
        if nx is not None:
            self._graph.add_node(node.node_id, **node.to_dict())
    
    def _add_edge(self, edge: GraphEdge):
        """Add edge to graph."""
        self._edges.append(edge)
        self._edges_from[edge.source].append(edge)
        self._edges_to[edge.target].append(edge)
        
        nx = self._get_networkx()
        if nx is not None:
            self._graph.add_edge(edge.source, edge.target, **edge.to_dict())
    
    def _add_construct_node(self, construct: Dict) -> str:
        """Add construct node if not exists, return ID."""
        construct_id = construct.get('id', '')
        if not construct_id:
            # Generate ID from role if no ID
            construct_id = f"construct:{construct.get('role', 'unknown')}"
        
        if construct_id not in self._nodes:
            node = GraphNode(
                node_id=construct_id,
                node_type=NodeType.CONSTRUCT,
                label=construct.get('role', construct_id),
                properties={
                    'role': construct.get('role'),
                    'direction': construct.get('direction')
                }
            )
            self._add_node(node)
        
        return construct_id
    
    def _build_affects_edges(self):
        """Build derived IV->DV edges from claims."""
        # For each claim, if it has both IV and DV, create affects edge
        for claim_id in self._nodes_by_type[NodeType.CLAIM]:
            ivs = []
            dvs = []
            
            for edge in self._edges_from.get(claim_id, []):
                if edge.edge_type == EdgeType.ABOUT_IV:
                    ivs.append(edge.target)
                elif edge.edge_type == EdgeType.ABOUT_DV:
                    dvs.append(edge.target)
            
            # Create IV -> DV edges
            claim_node = self._nodes.get(claim_id)
            for iv in ivs:
                for dv in dvs:
                    self._add_edge(GraphEdge(
                        source=iv,
                        target=dv,
                        edge_type=EdgeType.AFFECTS,
                        properties={
                            'claim_id': claim_id,
                            'effect_size': claim_node.properties.get('effect_size') if claim_node else None
                        }
                    ))
    
    def _build_citation_edges(self) -> int:
        """Build citation edges from citations table."""
        count = 0
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT source_paper_id, cited_paper_id FROM citations WHERE cited_paper_id IS NOT NULL"
            ).fetchall()
            
            for row in rows:
                citing = row['source_paper_id']
                cited = row['cited_paper_id']
                
                if citing in self._nodes and cited in self._nodes:
                    self._add_edge(GraphEdge(
                        source=citing,
                        target=cited,
                        edge_type=EdgeType.CITES
                    ))
                    count += 1
        
        return count
    
    def _save_cache(self, path: Path):
        """Save graph to cache."""
        data = {
            'nodes': {k: v.to_dict() for k, v in self._nodes.items()},
            'edges': [e.to_dict() for e in self._edges],
            'nodes_by_type': {k.value: list(v) for k, v in self._nodes_by_type.items()},
            'construct_claims': {k: list(v) for k, v in self._construct_claims.items()}
        }
        
        with open(path, 'wb') as f:
            pickle.dump(data, f)
    
    def _load_cache(self, path: Path):
        """Load graph from cache."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        # Reconstruct nodes
        for node_id, node_dict in data['nodes'].items():
            node = GraphNode(
                node_id=node_dict['id'],
                node_type=NodeType(node_dict['type']),
                label=node_dict['label'],
                properties=node_dict.get('properties', {})
            )
            self._nodes[node_id] = node
        
        # Reconstruct edges
        for edge_dict in data['edges']:
            edge = GraphEdge(
                source=edge_dict['source'],
                target=edge_dict['target'],
                edge_type=EdgeType(edge_dict['type']),
                properties=edge_dict.get('properties', {})
            )
            self._edges.append(edge)
            self._edges_from[edge.source].append(edge)
            self._edges_to[edge.target].append(edge)
        
        # Reconstruct indexes
        for type_str, node_ids in data.get('nodes_by_type', {}).items():
            self._nodes_by_type[NodeType(type_str)] = set(node_ids)
        
        for construct_id, claim_ids in data.get('construct_claims', {}).items():
            self._construct_claims[construct_id] = set(claim_ids)
        
        logger.info(f"Loaded graph from cache: {len(self._nodes)} nodes, {len(self._edges)} edges")
    
    # ========================================================================
    # QUERY METHODS
    # ========================================================================
    
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        return self._nodes.get(node_id)
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[GraphNode]:
        """Get all nodes of a given type."""
        return [self._nodes[nid] for nid in self._nodes_by_type.get(node_type, set())]
    
    def get_edges_from(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get all edges from a node."""
        edges = self._edges_from.get(node_id, [])
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges
    
    def get_edges_to(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get all edges to a node."""
        edges = self._edges_to.get(node_id, [])
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges
    
    def get_claims_about(self, construct_id: str) -> List[GraphNode]:
        """Get all claims about a construct."""
        claim_ids = self._construct_claims.get(construct_id, set())
        return [self._nodes[cid] for cid in claim_ids if cid in self._nodes]
    
    def what_affects(self, construct_id: str) -> List[Tuple[GraphNode, List[GraphNode]]]:
        """
        Find what affects a given construct (DV).
        
        Returns list of (IV_node, [claim_nodes]) tuples.
        """
        results = defaultdict(list)
        
        # Find AFFECTS edges pointing to this construct
        for edge in self._edges_to.get(construct_id, []):
            if edge.edge_type == EdgeType.AFFECTS:
                iv_id = edge.source
                claim_id = edge.properties.get('claim_id')
                if claim_id and claim_id in self._nodes:
                    results[iv_id].append(self._nodes[claim_id])
        
        return [
            (self._nodes[iv_id], claims)
            for iv_id, claims in results.items()
            if iv_id in self._nodes
        ]
    
    def what_does_affect(self, construct_id: str) -> List[Tuple[GraphNode, List[GraphNode]]]:
        """
        Find what a construct (IV) affects.
        
        Returns list of (DV_node, [claim_nodes]) tuples.
        """
        results = defaultdict(list)
        
        # Find AFFECTS edges from this construct
        for edge in self._edges_from.get(construct_id, []):
            if edge.edge_type == EdgeType.AFFECTS:
                dv_id = edge.target
                claim_id = edge.properties.get('claim_id')
                if claim_id and claim_id in self._nodes:
                    results[dv_id].append(self._nodes[claim_id])
        
        return [
            (self._nodes[dv_id], claims)
            for dv_id, claims in results.items()
            if dv_id in self._nodes
        ]
    
    def find_construct(self, query: str) -> List[GraphNode]:
        """Find constructs matching query string."""
        query_lower = query.lower()
        matches = []
        
        for node_id in self._nodes_by_type.get(NodeType.CONSTRUCT, set()):
            node = self._nodes[node_id]
            if query_lower in node.label.lower() or query_lower in node.node_id.lower():
                matches.append(node)
        
        return matches
    
    def get_paper_claims(self, paper_id: str) -> List[GraphNode]:
        """Get all claims from a paper."""
        claims = []
        for edge in self._edges_from.get(paper_id, []):
            if edge.edge_type == EdgeType.HAS_CLAIM:
                claim = self._nodes.get(edge.target)
                if claim:
                    claims.append(claim)
        return claims
    
    def get_stats(self) -> Dict[str, int]:
        """Get graph statistics."""
        edge_counts = defaultdict(int)
        for edge in self._edges:
            edge_counts[edge.edge_type.value] += 1
        
        return {
            'total_nodes': len(self._nodes),
            'papers': len(self._nodes_by_type.get(NodeType.PAPER, set())),
            'claims': len(self._nodes_by_type.get(NodeType.CLAIM, set())),
            'constructs': len(self._nodes_by_type.get(NodeType.CONSTRUCT, set())),
            'total_edges': len(self._edges),
            'edges_by_type': dict(edge_counts)
        }
    
    def export_for_visualization(self) -> Dict[str, Any]:
        """Export graph in format suitable for visualization (e.g., D3.js)."""
        return {
            'nodes': [n.to_dict() for n in self._nodes.values()],
            'links': [
                {
                    'source': e.source,
                    'target': e.target,
                    'type': e.edge_type.value
                }
                for e in self._edges
            ]
        }
