# Version: 3.2.2
"""
Article Finder v3.2.2 - Query Engine
Natural language queries over the knowledge graph.

Translates questions like:
- "What affects cognitive performance?"
- "What does daylight affect?"
- "Show contradictory claims about open offices"
- "How many claims support biophilic design?"

Into graph traversals and returns structured results.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class QueryType(Enum):
    WHAT_AFFECTS = "what_affects"           # What affects X?
    AFFECTS_WHAT = "affects_what"           # What does X affect?
    CLAIMS_ABOUT = "claims_about"           # Show claims about X
    CONTRADICTIONS = "contradictions"        # Find contradictory claims about X
    COUNT_CLAIMS = "count_claims"           # How many claims about X?
    PAPERS_ABOUT = "papers_about"           # Papers studying X
    SIMILAR_CLAIMS = "similar_claims"       # Claims similar to X
    GENERAL_SEARCH = "general_search"       # Fallback semantic search


@dataclass
class QueryResult:
    """Result from a knowledge graph query."""
    query_type: QueryType
    query_text: str
    construct: Optional[str] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[str] = None
    count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'query_type': self.query_type.value,
            'query': self.query_text,
            'construct': self.construct,
            'count': self.count,
            'summary': self.summary,
            'results': self.results
        }


class QueryParser:
    """
    Parse natural language queries into structured query types.
    """
    
    # Patterns for query type detection
    PATTERNS = {
        QueryType.WHAT_AFFECTS: [
            r"what (?:factors? )?affects? (.+?)(?:\?|$)",
            r"what influences? (.+?)(?:\?|$)",
            r"what impacts? (.+?)(?:\?|$)",
            r"what (?:are the )?(?:causes?|drivers?) of (.+?)(?:\?|$)",
            r"(.+?) is affected by what(?:\?|$)",
        ],
        QueryType.AFFECTS_WHAT: [
            r"what does (.+?) affect(?:\?|$)",
            r"what (?:are the )?effects? of (.+?)(?:\?|$)",
            r"what does (.+?) influence(?:\?|$)",
            r"what does (.+?) impact(?:\?|$)",
            r"how does (.+?) affect (?:people|humans|occupants)(?:\?|$)",
            r"(.+?) affects what(?:\?|$)",
        ],
        QueryType.CLAIMS_ABOUT: [
            r"(?:show|list|find|get) (?:all )?claims? about (.+?)(?:\?|$)",
            r"what (?:do (?:the )?studies|does research) say about (.+?)(?:\?|$)",
            r"claims? (?:about|regarding|on) (.+?)(?:\?|$)",
        ],
        QueryType.CONTRADICTIONS: [
            r"(?:find|show|are there) contradictions? (?:about|in|regarding) (.+?)(?:\?|$)",
            r"contradictory (?:claims?|findings?|evidence) (?:about|on) (.+?)(?:\?|$)",
            r"conflicting (?:claims?|findings?|evidence) (?:about|on) (.+?)(?:\?|$)",
        ],
        QueryType.COUNT_CLAIMS: [
            r"how many claims? (?:are there )?(?:about|on|regarding) (.+?)(?:\?|$)",
            r"(?:count|number of) claims? (?:about|on) (.+?)(?:\?|$)",
        ],
        QueryType.PAPERS_ABOUT: [
            r"(?:find|show|list) papers? (?:about|on|studying) (.+?)(?:\?|$)",
            r"what papers? (?:study|discuss|cover) (.+?)(?:\?|$)",
        ],
    }
    
    def parse(self, query: str) -> Tuple[QueryType, Optional[str]]:
        """
        Parse query into type and extracted construct.
        
        Returns (query_type, construct_string)
        """
        query_lower = query.lower().strip()
        
        for query_type, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    construct = match.group(1).strip()
                    return (query_type, construct)
        
        # Fallback to general search
        return (QueryType.GENERAL_SEARCH, query_lower)


class QueryEngine:
    """
    Execute queries against the knowledge graph.
    """
    
    def __init__(self, database, claim_graph=None, semantic_search=None, claim_embeddings=None):
        """
        Args:
            database: Database instance
            claim_graph: Optional pre-built ClaimGraph
            semantic_search: Optional SemanticSearch instance
            claim_embeddings: Optional ClaimEmbeddings instance
        """
        self.db = database
        self._graph = claim_graph
        self._search = semantic_search
        self._claim_embeddings = claim_embeddings
        self.parser = QueryParser()
    
    @property
    def graph(self):
        """Lazy-load knowledge graph."""
        if self._graph is None:
            from knowledge.claim_graph import ClaimGraph
            self._graph = ClaimGraph(self.db)
            self._graph.build(force_rebuild=False)
        return self._graph
    
    @property
    def search(self):
        """Lazy-load semantic search."""
        if self._search is None:
            from knowledge.semantic_search import SemanticSearch
            self._search = SemanticSearch(self.db)
        return self._search
    
    @property
    def claim_embeddings(self):
        """Lazy-load claim embeddings."""
        if self._claim_embeddings is None:
            from knowledge.claim_embeddings import ClaimEmbeddings
            self._claim_embeddings = ClaimEmbeddings(self.db)
        return self._claim_embeddings
    
    def query(self, query_text: str) -> QueryResult:
        """
        Execute a natural language query.
        
        Parses the query, determines type, and executes appropriate traversal.
        """
        query_type, construct = self.parser.parse(query_text)
        
        logger.info(f"Query type: {query_type.value}, construct: {construct}")
        
        if query_type == QueryType.WHAT_AFFECTS:
            return self._query_what_affects(query_text, construct)
        
        elif query_type == QueryType.AFFECTS_WHAT:
            return self._query_affects_what(query_text, construct)
        
        elif query_type == QueryType.CLAIMS_ABOUT:
            return self._query_claims_about(query_text, construct)
        
        elif query_type == QueryType.CONTRADICTIONS:
            return self._query_contradictions(query_text, construct)
        
        elif query_type == QueryType.COUNT_CLAIMS:
            return self._query_count_claims(query_text, construct)
        
        elif query_type == QueryType.PAPERS_ABOUT:
            return self._query_papers_about(query_text, construct)
        
        else:
            return self._query_general_search(query_text, construct)
    
    def _find_construct_matches(self, construct: str) -> List[Any]:
        """Find graph constructs matching the query string."""
        # First try exact/partial match in graph
        matches = self.graph.find_construct(construct)
        
        if not matches:
            # Try semantic search over constructs
            # For now, just search for papers as fallback
            pass
        
        return matches
    
    def _query_what_affects(self, query_text: str, construct: str) -> QueryResult:
        """Find what affects a given construct."""
        matches = self._find_construct_matches(construct)
        
        results = []
        all_ivs = defaultdict(list)
        
        for match in matches:
            affecting = self.graph.what_affects(match.node_id)
            for iv_node, claims in affecting:
                for claim in claims:
                    all_ivs[iv_node.label].append({
                        'iv': iv_node.label,
                        'iv_id': iv_node.node_id,
                        'claim': claim.properties.get('statement', ''),
                        'claim_type': claim.properties.get('claim_type'),
                        'effect_size': claim.properties.get('effect_size')
                    })
        
        # Aggregate results
        for iv_label, claims in all_ivs.items():
            results.append({
                'factor': iv_label,
                'claim_count': len(claims),
                'claims': claims[:5],  # Top 5 claims
                'avg_effect': self._avg_effect_size(claims)
            })
        
        results.sort(key=lambda x: -x['claim_count'])
        
        summary = None
        if results:
            top_factors = [r['factor'] for r in results[:3]]
            summary = f"{len(results)} factors affect {construct}. Top factors: {', '.join(top_factors)}"
        
        return QueryResult(
            query_type=QueryType.WHAT_AFFECTS,
            query_text=query_text,
            construct=construct,
            results=results,
            summary=summary,
            count=len(results)
        )
    
    def _query_affects_what(self, query_text: str, construct: str) -> QueryResult:
        """Find what a construct affects."""
        matches = self._find_construct_matches(construct)
        
        results = []
        all_dvs = defaultdict(list)
        
        for match in matches:
            affected = self.graph.what_does_affect(match.node_id)
            for dv_node, claims in affected:
                for claim in claims:
                    all_dvs[dv_node.label].append({
                        'dv': dv_node.label,
                        'dv_id': dv_node.node_id,
                        'claim': claim.properties.get('statement', ''),
                        'claim_type': claim.properties.get('claim_type'),
                        'effect_size': claim.properties.get('effect_size')
                    })
        
        for dv_label, claims in all_dvs.items():
            results.append({
                'outcome': dv_label,
                'claim_count': len(claims),
                'claims': claims[:5],
                'avg_effect': self._avg_effect_size(claims)
            })
        
        results.sort(key=lambda x: -x['claim_count'])
        
        summary = None
        if results:
            top_outcomes = [r['outcome'] for r in results[:3]]
            summary = f"{construct} affects {len(results)} outcomes. Top: {', '.join(top_outcomes)}"
        
        return QueryResult(
            query_type=QueryType.AFFECTS_WHAT,
            query_text=query_text,
            construct=construct,
            results=results,
            summary=summary,
            count=len(results)
        )
    
    def _query_claims_about(self, query_text: str, construct: str) -> QueryResult:
        """Get all claims about a construct."""
        # Try graph first
        matches = self._find_construct_matches(construct)
        
        results = []
        seen_claims = set()
        
        for match in matches:
            claims = self.graph.get_claims_about(match.node_id)
            for claim in claims:
                if claim.node_id in seen_claims:
                    continue
                seen_claims.add(claim.node_id)
                
                results.append({
                    'claim_id': claim.node_id,
                    'statement': claim.properties.get('statement', ''),
                    'claim_type': claim.properties.get('claim_type'),
                    'effect_size': claim.properties.get('effect_size'),
                    'p_value': claim.properties.get('p_value')
                })
        
        # Also do semantic search over claims
        if len(results) < 10:
            semantic_claims = self.claim_embeddings.search(construct, limit=20)
            for sc in semantic_claims:
                if sc.claim_id not in seen_claims:
                    results.append({
                        'claim_id': sc.claim_id,
                        'statement': sc.statement,
                        'claim_type': sc.claim_type,
                        'semantic_score': sc.score
                    })
        
        summary = f"Found {len(results)} claims about {construct}"
        
        return QueryResult(
            query_type=QueryType.CLAIMS_ABOUT,
            query_text=query_text,
            construct=construct,
            results=results[:50],  # Limit to 50
            summary=summary,
            count=len(results)
        )
    
    def _query_contradictions(self, query_text: str, construct: str) -> QueryResult:
        """Find potentially contradictory claims about a construct."""
        # Get all claims about the construct
        claims_result = self._query_claims_about(query_text, construct)
        claims = claims_result.results
        
        if len(claims) < 2:
            return QueryResult(
                query_type=QueryType.CONTRADICTIONS,
                query_text=query_text,
                construct=construct,
                results=[],
                summary=f"Not enough claims to find contradictions (found {len(claims)})",
                count=0
            )
        
        # Look for potential contradictions:
        # 1. Claims with opposite effect directions
        # 2. Claims with very different effect sizes
        # 3. Semantically similar but with different conclusions
        
        contradictions = []
        
        # Simple heuristic: look for positive vs negative effects
        positive_claims = []
        negative_claims = []
        null_claims = []
        
        for claim in claims:
            claim_type = claim.get('claim_type', '')
            statement = claim.get('statement', '').lower()
            
            if claim_type == 'null':
                null_claims.append(claim)
            elif any(word in statement for word in ['increase', 'improve', 'enhance', 'positive', 'higher']):
                positive_claims.append(claim)
            elif any(word in statement for word in ['decrease', 'reduce', 'impair', 'negative', 'lower']):
                negative_claims.append(claim)
        
        # Pair positive with negative claims
        for pos in positive_claims[:5]:
            for neg in negative_claims[:5]:
                contradictions.append({
                    'type': 'direction_conflict',
                    'claim_1': pos,
                    'claim_2': neg,
                    'explanation': 'Opposite effect directions'
                })
        
        # Pair effect claims with null claims
        for effect in (positive_claims + negative_claims)[:5]:
            for null in null_claims[:3]:
                contradictions.append({
                    'type': 'effect_vs_null',
                    'claim_1': effect,
                    'claim_2': null,
                    'explanation': 'Effect claim vs null finding'
                })
        
        summary = f"Found {len(contradictions)} potential contradictions about {construct}"
        
        return QueryResult(
            query_type=QueryType.CONTRADICTIONS,
            query_text=query_text,
            construct=construct,
            results=contradictions[:20],
            summary=summary,
            count=len(contradictions)
        )
    
    def _query_count_claims(self, query_text: str, construct: str) -> QueryResult:
        """Count claims about a construct."""
        claims_result = self._query_claims_about(query_text, construct)
        
        # Breakdown by type
        by_type = defaultdict(int)
        for claim in claims_result.results:
            by_type[claim.get('claim_type', 'unknown')] += 1
        
        results = [{
            'total': claims_result.count,
            'by_type': dict(by_type)
        }]
        
        summary = f"{claims_result.count} claims about {construct}"
        if by_type:
            type_breakdown = ", ".join(f"{count} {t}" for t, count in by_type.items())
            summary += f" ({type_breakdown})"
        
        return QueryResult(
            query_type=QueryType.COUNT_CLAIMS,
            query_text=query_text,
            construct=construct,
            results=results,
            summary=summary,
            count=claims_result.count
        )
    
    def _query_papers_about(self, query_text: str, construct: str) -> QueryResult:
        """Find papers about a construct."""
        # Use semantic search over papers
        paper_results = self.search.search(construct, limit=30)
        
        results = []
        for pr in paper_results:
            results.append({
                'paper_id': pr.paper_id,
                'title': pr.title,
                'year': pr.year,
                'doi': pr.doi,
                'relevance': pr.score
            })
        
        summary = f"Found {len(results)} papers about {construct}"
        
        return QueryResult(
            query_type=QueryType.PAPERS_ABOUT,
            query_text=query_text,
            construct=construct,
            results=results,
            summary=summary,
            count=len(results)
        )
    
    def _query_general_search(self, query_text: str, construct: str) -> QueryResult:
        """Fallback general search."""
        # Search both papers and claims
        paper_results = self.search.search(construct, limit=15)
        claim_results = self.claim_embeddings.search(construct, limit=15)
        
        results = {
            'papers': [
                {'title': p.title, 'year': p.year, 'score': p.score}
                for p in paper_results
            ],
            'claims': [
                {'statement': c.statement[:100], 'type': c.claim_type, 'score': c.score}
                for c in claim_results
            ]
        }
        
        summary = f"Found {len(paper_results)} papers and {len(claim_results)} claims matching '{construct}'"
        
        return QueryResult(
            query_type=QueryType.GENERAL_SEARCH,
            query_text=query_text,
            construct=construct,
            results=[results],
            summary=summary,
            count=len(paper_results) + len(claim_results)
        )
    
    def _avg_effect_size(self, claims: List[Dict]) -> Optional[float]:
        """Calculate average effect size from claims."""
        effect_sizes = [
            c.get('effect_size') 
            for c in claims 
            if c.get('effect_size') is not None
        ]
        
        if not effect_sizes:
            return None
        
        return sum(effect_sizes) / len(effect_sizes)


def query_knowledge_graph(database, query: str) -> QueryResult:
    """Convenience function for querying."""
    engine = QueryEngine(database)
    return engine.query(query)
