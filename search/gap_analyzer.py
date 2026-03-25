# Version: 3.2.5
"""
Article Finder v3.2.5 - Gap Analyzer
Analyzes knowledge graph and taxonomy to identify search priorities.

This module bridges AE outputs with AF search by:
1. Analyzing coverage across taxonomy cells
2. Finding theories with untested predictions
3. Identifying IV→DV edges lacking mechanism explanations
4. Finding neural outcomes with sparse evidence
5. Generating priority queries to fill gaps

The GapAnalyzer drives the feedback loop: AE extracts → gaps identified → AF searches.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum
import yaml

logger = logging.getLogger(__name__)


class LiteratureGapType(Enum):
    """Types of literature coverage gaps (distinct from epistemic GapType in AE).

    Note: Renamed from GapType to avoid collision with AE's canonical GapType
    which covers epistemic argument gaps (mediation, mechanism, direction, etc.).
    This enum covers search/coverage gaps for literature discovery.
    """
    COVERAGE = "coverage"           # Taxonomy cell has few papers
    THEORY_UNTESTED = "theory"      # Theory prediction not tested
    MECHANISM_MISSING = "mechanism" # IV→DV edge lacks mediator
    NEURAL_SPARSE = "neural"        # Neural outcome under-studied
    BOUNDARY_UNKNOWN = "boundary"   # Moderators/boundary conditions unknown


@dataclass
class KnowledgeGap:
    """A gap in the knowledge graph that should be filled."""
    gap_id: str
    gap_type: LiteratureGapType
    priority: float  # 0.0 to 1.0
    description: str

    # What's missing
    taxonomy_cells: List[str] = field(default_factory=list)  # Relevant taxonomy nodes
    constructs: List[str] = field(default_factory=list)      # Constructs involved

    # Search strategy
    suggested_queries: List[str] = field(default_factory=list)
    search_apis: List[str] = field(default_factory=lambda: ['openalex', 'semantic_scholar'])

    # Context
    existing_evidence: int = 0  # Papers/claims already found
    theory_id: Optional[str] = None  # If theory gap

    def to_dict(self) -> Dict[str, Any]:
        return {
            'gap_id': self.gap_id,
            'gap_type': self.gap_type.value,
            'priority': self.priority,
            'description': self.description,
            'taxonomy_cells': self.taxonomy_cells,
            'constructs': self.constructs,
            'suggested_queries': self.suggested_queries,
            'existing_evidence': self.existing_evidence,
            'theory_id': self.theory_id
        }


@dataclass
class CoverageStats:
    """Coverage statistics for a taxonomy cell."""
    cell_id: str
    factor_id: str
    outcome_id: str
    paper_count: int = 0
    claim_count: int = 0
    has_mechanism: bool = False
    has_neural: bool = False
    has_theory_test: bool = False
    coverage_score: float = 0.0


class GapAnalyzer:
    """
    Analyzes knowledge graph and taxonomy to identify gaps for search.

    Integrates with:
    - Taxonomy (config/taxonomy.yaml) for domain structure
    - ClaimGraph (knowledge/claim_graph.py) for extracted knowledge
    - TheoryAwareSearch (knowledge/theory_search.py) for theory predictions
    """

    def __init__(
        self,
        database,
        taxonomy_path: Optional[Path] = None,
        claim_graph=None
    ):
        self.db = database
        self.taxonomy_path = taxonomy_path or Path('./config/taxonomy.yaml')
        self.claim_graph = claim_graph

        # Load taxonomy
        self._taxonomy = None
        self._load_taxonomy()

        # Cache
        self._coverage_cache: Dict[str, CoverageStats] = {}

    def _load_taxonomy(self):
        """Load taxonomy from YAML."""
        if self.taxonomy_path.exists():
            with open(self.taxonomy_path) as f:
                self._taxonomy = yaml.safe_load(f)
        else:
            logger.warning(f"Taxonomy not found: {self.taxonomy_path}")
            self._taxonomy = {}

    # =========================================================================
    # COVERAGE ANALYSIS
    # =========================================================================

    def analyze_coverage(self, force_refresh: bool = False) -> Dict[str, CoverageStats]:
        """
        Analyze coverage across all factor×outcome cells.

        Returns coverage statistics per cell.
        """
        if self._coverage_cache and not force_refresh:
            return self._coverage_cache

        # Get all factors and outcomes
        factors = self._extract_nodes('environmental_factors', max_level=2)
        outcomes = self._extract_nodes('outcomes', max_level=2)

        coverage = {}

        for factor in factors:
            for outcome in outcomes:
                cell_id = f"{factor['id']}_{outcome['id']}"

                stats = CoverageStats(
                    cell_id=cell_id,
                    factor_id=factor['id'],
                    outcome_id=outcome['id']
                )

                # Count papers/claims for this cell
                stats.paper_count, stats.claim_count = self._count_evidence(
                    factor['id'], outcome['id']
                )

                # Check for mechanism and neural evidence
                stats.has_mechanism = self._has_mechanism_evidence(factor['id'], outcome['id'])
                stats.has_neural = self._has_neural_evidence(outcome['id'])

                # Calculate coverage score
                stats.coverage_score = self._calculate_coverage_score(stats)

                coverage[cell_id] = stats

        self._coverage_cache = coverage
        return coverage

    def _extract_nodes(self, facet_key: str, max_level: int = 2) -> List[Dict]:
        """Extract nodes from taxonomy up to max_level."""
        nodes = []
        facet_data = self._taxonomy.get(facet_key, [])

        def extract_recursive(items, current_level=1):
            for item in items:
                if current_level <= max_level:
                    nodes.append({
                        'id': item.get('id', ''),
                        'name': item.get('name', ''),
                        'level': item.get('level', current_level),
                        'seeds': item.get('seeds', [])
                    })
                    if 'children' in item and current_level < max_level:
                        extract_recursive(item['children'], current_level + 1)

        extract_recursive(facet_data)
        return nodes

    def _count_evidence(self, factor_id: str, outcome_id: str) -> Tuple[int, int]:
        """Count papers and claims for a factor×outcome combination."""
        paper_count = 0
        claim_count = 0

        with self.db.connection() as conn:
            # Try paper_facet_scores first, fall back to simpler query
            try:
                result = conn.execute("""
                    SELECT COUNT(DISTINCT pfs1.paper_id) as papers
                    FROM paper_facet_scores pfs1
                    JOIN paper_facet_scores pfs2 ON pfs1.paper_id = pfs2.paper_id
                    WHERE pfs1.node_id LIKE ?
                      AND pfs2.node_id LIKE ?
                      AND pfs1.score >= 0.4
                      AND pfs2.score >= 0.4
                """, (f"{factor_id}%", f"{outcome_id}%")).fetchone()

                if result:
                    paper_count = result['papers'] or 0
            except Exception:
                # Table may not exist or be empty - use text search as fallback
                try:
                    # Search paper titles/abstracts for keywords
                    factor_term = factor_id.split('.')[-1].replace('_', ' ')
                    outcome_term = outcome_id.split('.')[-1].replace('_', ' ')
                    result = conn.execute("""
                        SELECT COUNT(*) as papers
                        FROM papers
                        WHERE (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
                          AND (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
                    """, (f"%{factor_term}%", f"%{factor_term}%",
                          f"%{outcome_term}%", f"%{outcome_term}%")).fetchone()
                    if result:
                        paper_count = result['papers'] or 0
                except Exception:
                    pass

            # Count claims with these constructs
            try:
                result = conn.execute("""
                    SELECT COUNT(*) as claims
                    FROM claims
                    WHERE constructs LIKE ?
                      AND constructs LIKE ?
                """, (f"%{factor_id}%", f"%{outcome_id}%")).fetchone()

                if result:
                    claim_count = result['claims'] or 0
            except Exception:
                pass

        return paper_count, claim_count

    def _has_mechanism_evidence(self, factor_id: str, outcome_id: str) -> bool:
        """Check if there's mechanism evidence for this IV→DV relationship."""
        try:
            with self.db.connection() as conn:
                result = conn.execute("""
                    SELECT COUNT(*) as count
                    FROM claims
                    WHERE claim_type = 'mechanistic'
                      AND constructs LIKE ?
                      AND constructs LIKE ?
                """, (f"%{factor_id}%", f"%{outcome_id}%")).fetchone()

                return result and result['count'] > 0
        except Exception:
            return False

    def _has_neural_evidence(self, outcome_id: str) -> bool:
        """Check if outcome has neural measurement evidence."""
        try:
            with self.db.connection() as conn:
                result = conn.execute("""
                    SELECT COUNT(*) as count
                    FROM claims
                    WHERE constructs LIKE '%out.neural%'
                      AND constructs LIKE ?
                """, (f"%{outcome_id}%",)).fetchone()

                return result and result['count'] > 0
        except Exception:
            return False

    def _calculate_coverage_score(self, stats: CoverageStats) -> float:
        """Calculate coverage score (0-1) for a cell."""
        score = 0.0

        # Paper count contributes 40%
        paper_score = min(1.0, stats.paper_count / 10)  # 10+ papers = full score
        score += 0.4 * paper_score

        # Claim count contributes 30%
        claim_score = min(1.0, stats.claim_count / 5)  # 5+ claims = full score
        score += 0.3 * claim_score

        # Mechanism evidence contributes 15%
        if stats.has_mechanism:
            score += 0.15

        # Neural evidence contributes 15%
        if stats.has_neural:
            score += 0.15

        return round(score, 2)

    # =========================================================================
    # GAP IDENTIFICATION
    # =========================================================================

    def find_coverage_gaps(self, threshold: float = 0.3) -> List[KnowledgeGap]:
        """Find taxonomy cells with coverage below threshold."""
        coverage = self.analyze_coverage()
        gaps = []

        for cell_id, stats in coverage.items():
            if stats.coverage_score < threshold:
                gap = KnowledgeGap(
                    gap_id=f"coverage:{cell_id}",
                    gap_type=LiteratureGapType.COVERAGE,
                    priority=1.0 - stats.coverage_score,  # Lower coverage = higher priority
                    description=f"Low coverage for {stats.factor_id} → {stats.outcome_id}",
                    taxonomy_cells=[stats.factor_id, stats.outcome_id],
                    existing_evidence=stats.paper_count
                )

                # Generate queries from taxonomy seeds
                gap.suggested_queries = self._generate_coverage_queries(stats)
                gaps.append(gap)

        # Sort by priority
        gaps.sort(key=lambda g: g.priority, reverse=True)
        return gaps

    def find_theory_gaps(self) -> List[KnowledgeGap]:
        """Find theories with untested predictions."""
        gaps = []
        theories = self._extract_nodes('theory', max_level=2)

        for theory in theories:
            # Check how many papers test this theory
            paper_count = self._count_theory_papers(theory['id'])

            if paper_count < 5:  # Under-tested threshold
                gap = KnowledgeGap(
                    gap_id=f"theory:{theory['id']}",
                    gap_type=LiteratureGapType.THEORY_UNTESTED,
                    priority=0.8 if paper_count == 0 else 0.6,
                    description=f"Theory '{theory['name']}' has limited empirical testing",
                    taxonomy_cells=[theory['id']],
                    existing_evidence=paper_count,
                    theory_id=theory['id']
                )

                # Generate queries from theory seeds
                gap.suggested_queries = self._generate_theory_queries(theory)
                gaps.append(gap)

        gaps.sort(key=lambda g: g.priority, reverse=True)
        return gaps

    def find_mechanism_gaps(self) -> List[KnowledgeGap]:
        """Find IV→DV relationships lacking mechanism explanations."""
        coverage = self.analyze_coverage()
        gaps = []

        for cell_id, stats in coverage.items():
            # Only consider cells with some evidence but no mechanism
            if stats.paper_count >= 3 and not stats.has_mechanism:
                gap = KnowledgeGap(
                    gap_id=f"mechanism:{cell_id}",
                    gap_type=LiteratureGapType.MECHANISM_MISSING,
                    priority=0.7,
                    description=f"No mechanism evidence for {stats.factor_id} → {stats.outcome_id}",
                    taxonomy_cells=[stats.factor_id, stats.outcome_id],
                    existing_evidence=stats.paper_count
                )

                gap.suggested_queries = self._generate_mechanism_queries(stats)
                gaps.append(gap)

        gaps.sort(key=lambda g: g.priority, reverse=True)
        return gaps

    def find_neural_gaps(self) -> List[KnowledgeGap]:
        """Find environmental factors lacking neural outcome evidence."""
        gaps = []
        factors = self._extract_nodes('environmental_factors', max_level=2)
        neural_outcomes = self._extract_nodes('outcomes', max_level=3)
        neural_outcomes = [n for n in neural_outcomes if 'neural' in n['id']]

        for factor in factors:
            for neural in neural_outcomes:
                paper_count = self._count_neural_factor_papers(factor['id'], neural['id'])

                if paper_count < 2:  # Sparse neural evidence
                    gap = KnowledgeGap(
                        gap_id=f"neural:{factor['id']}_{neural['id']}",
                        gap_type=LiteratureGapType.NEURAL_SPARSE,
                        priority=0.75,
                        description=f"Sparse neural evidence: {factor['name']} → {neural['name']}",
                        taxonomy_cells=[factor['id'], neural['id']],
                        existing_evidence=paper_count
                    )

                    gap.suggested_queries = self._generate_neural_queries(factor, neural)
                    gaps.append(gap)

        # Limit to top gaps (neural can generate many)
        gaps.sort(key=lambda g: g.priority, reverse=True)
        return gaps[:50]

    def _count_theory_papers(self, theory_id: str) -> int:
        """Count papers testing a theory."""
        try:
            with self.db.connection() as conn:
                # Try facet scores first
                try:
                    result = conn.execute("""
                        SELECT COUNT(DISTINCT paper_id) as count
                        FROM paper_facet_scores
                        WHERE node_id = ?
                          AND score >= 0.4
                    """, (theory_id,)).fetchone()
                    if result and result['count'] > 0:
                        return result['count']
                except Exception:
                    pass

                # Fall back to text search using theory seeds
                theory_term = theory_id.split('.')[-1].replace('_', ' ')
                result = conn.execute("""
                    SELECT COUNT(*) as count
                    FROM papers
                    WHERE LOWER(title) LIKE ?
                       OR LOWER(abstract) LIKE ?
                """, (f"%{theory_term}%", f"%{theory_term}%")).fetchone()
                return result['count'] if result else 0
        except Exception:
            return 0

    def _count_neural_factor_papers(self, factor_id: str, neural_id: str) -> int:
        """Count papers with both factor and neural outcome."""
        try:
            with self.db.connection() as conn:
                # Try facet scores first
                try:
                    result = conn.execute("""
                        SELECT COUNT(DISTINCT pfs1.paper_id) as count
                        FROM paper_facet_scores pfs1
                        JOIN paper_facet_scores pfs2 ON pfs1.paper_id = pfs2.paper_id
                        WHERE pfs1.node_id LIKE ?
                          AND pfs2.node_id LIKE ?
                          AND pfs1.score >= 0.3
                          AND pfs2.score >= 0.3
                    """, (f"{factor_id}%", f"{neural_id}%")).fetchone()
                    if result and result['count'] > 0:
                        return result['count']
                except Exception:
                    pass

                # Fall back to text search
                factor_term = factor_id.split('.')[-1].replace('_', ' ')
                neural_term = neural_id.split('.')[-1].replace('_', ' ')
                result = conn.execute("""
                    SELECT COUNT(*) as count
                    FROM papers
                    WHERE (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
                      AND (LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)
                """, (f"%{factor_term}%", f"%{factor_term}%",
                      f"%{neural_term}%", f"%{neural_term}%")).fetchone()
                return result['count'] if result else 0
        except Exception:
            return 0

    # =========================================================================
    # QUERY GENERATION (Using Taxonomy Seeds)
    # =========================================================================

    def _generate_coverage_queries(self, stats: CoverageStats) -> List[str]:
        """Generate search queries for a coverage gap using taxonomy seeds."""
        queries = []

        # Get seeds from taxonomy
        factor_seeds = self._get_seeds(stats.factor_id)
        outcome_seeds = self._get_seeds(stats.outcome_id)

        # Cross-product of seeds (more specific than generic terms)
        for f_seed in factor_seeds[:3]:
            for o_seed in outcome_seeds[:2]:
                queries.append(f'"{f_seed}" AND "{o_seed}"')

        # Add building/architecture context
        if factor_seeds:
            queries.append(f'"{factor_seeds[0]}" building occupants')
            queries.append(f'"{factor_seeds[0]}" indoor environment effect')

        return queries[:8]

    def _generate_theory_queries(self, theory: Dict) -> List[str]:
        """Generate search queries to find papers testing a theory."""
        queries = []
        seeds = theory.get('seeds', [])
        name = theory.get('name', '')

        for seed in seeds[:3]:
            queries.append(f'"{seed}" empirical study')
            queries.append(f'"{seed}" experiment')

        if name:
            queries.append(f'"{name}" test evidence')
            queries.append(f'"{name}" architecture environment')

        return queries[:6]

    def _generate_mechanism_queries(self, stats: CoverageStats) -> List[str]:
        """Generate queries to find mechanism/mediator evidence."""
        queries = []

        factor_seeds = self._get_seeds(stats.factor_id)
        outcome_seeds = self._get_seeds(stats.outcome_id)

        if factor_seeds and outcome_seeds:
            queries.append(f'"{factor_seeds[0]}" mechanism "{outcome_seeds[0]}"')
            queries.append(f'"{factor_seeds[0]}" mediates "{outcome_seeds[0]}"')
            queries.append(f'"{factor_seeds[0]}" pathway "{outcome_seeds[0]}"')
            queries.append(f'how {factor_seeds[0]} affects {outcome_seeds[0]}')

        return queries[:5]

    def _generate_neural_queries(self, factor: Dict, neural: Dict) -> List[str]:
        """Generate queries for neural outcome evidence."""
        queries = []

        factor_seeds = factor.get('seeds', [])
        neural_seeds = neural.get('seeds', [])
        neural_name = neural.get('name', '')

        if factor_seeds:
            if neural_seeds:
                queries.append(f'"{factor_seeds[0]}" "{neural_seeds[0]}"')
            if neural_name:
                queries.append(f'"{factor_seeds[0]}" {neural_name} brain')
                queries.append(f'{factor_seeds[0]} neural correlates')

        # Add specific neuroscience terms
        if 'eeg' in neural.get('id', ''):
            queries.append(f'{factor.get("name", "")} EEG study')
        if 'fmri' in neural.get('id', ''):
            queries.append(f'{factor.get("name", "")} fMRI neuroimaging')

        return queries[:5]

    def _get_seeds(self, node_id: str) -> List[str]:
        """Get seed phrases for a taxonomy node."""
        # Search through taxonomy for node
        for facet_key in ['environmental_factors', 'outcomes', 'theory', 'subjects', 'settings']:
            facet_data = self._taxonomy.get(facet_key, [])
            seeds = self._find_node_seeds(facet_data, node_id)
            if seeds:
                return seeds
        return []

    def _find_node_seeds(self, nodes: List, target_id: str) -> List[str]:
        """Recursively find seeds for a node ID."""
        for node in nodes:
            if node.get('id') == target_id:
                return node.get('seeds', [])
            if 'children' in node:
                seeds = self._find_node_seeds(node['children'], target_id)
                if seeds:
                    return seeds
        return []

    # =========================================================================
    # AGGREGATE GAP ANALYSIS
    # =========================================================================

    def get_all_gaps(self, limit: int = 100) -> List[KnowledgeGap]:
        """
        Get all gaps sorted by priority.

        Combines coverage, theory, mechanism, and neural gaps.
        """
        all_gaps = []

        # Coverage gaps (most important)
        all_gaps.extend(self.find_coverage_gaps(threshold=0.3))

        # Theory gaps
        all_gaps.extend(self.find_theory_gaps())

        # Mechanism gaps
        all_gaps.extend(self.find_mechanism_gaps())

        # Neural gaps
        all_gaps.extend(self.find_neural_gaps())

        # Sort by priority and deduplicate
        all_gaps.sort(key=lambda g: g.priority, reverse=True)

        # Remove duplicates by gap_id
        seen = set()
        unique_gaps = []
        for gap in all_gaps:
            if gap.gap_id not in seen:
                seen.add(gap.gap_id)
                unique_gaps.append(gap)

        return unique_gaps[:limit]

    def get_priority_queries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get priority search queries from all gaps.

        Returns queries with metadata for the Bibliographer to execute.
        """
        gaps = self.get_all_gaps(limit=limit)
        queries = []

        for gap in gaps:
            for query in gap.suggested_queries:
                queries.append({
                    'query': query,
                    'gap_id': gap.gap_id,
                    'gap_type': gap.gap_type.value,
                    'priority': gap.priority,
                    'taxonomy_cells': gap.taxonomy_cells,
                    'search_apis': gap.search_apis
                })

        # Sort by priority and deduplicate
        queries.sort(key=lambda q: q['priority'], reverse=True)

        # Deduplicate queries
        seen = set()
        unique = []
        for q in queries:
            if q['query'] not in seen:
                seen.add(q['query'])
                unique.append(q)

        return unique[:limit]

    def get_coverage_summary(self) -> Dict[str, Any]:
        """Get a summary of overall coverage."""
        coverage = self.analyze_coverage()

        total_cells = len(coverage)
        covered = sum(1 for s in coverage.values() if s.coverage_score >= 0.5)
        with_mechanism = sum(1 for s in coverage.values() if s.has_mechanism)
        with_neural = sum(1 for s in coverage.values() if s.has_neural)

        avg_score = sum(s.coverage_score for s in coverage.values()) / max(1, total_cells)

        return {
            'total_cells': total_cells,
            'covered_cells': covered,
            'coverage_rate': round(covered / max(1, total_cells), 2),
            'cells_with_mechanism': with_mechanism,
            'cells_with_neural': with_neural,
            'average_coverage_score': round(avg_score, 2),
            'gap_counts': {
                'coverage': len(self.find_coverage_gaps()),
                'theory': len(self.find_theory_gaps()),
                'mechanism': len(self.find_mechanism_gaps()),
                'neural': len(self.find_neural_gaps())
            }
        }
