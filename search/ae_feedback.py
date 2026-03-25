# Version: 3.2.5
"""
Article Finder v3.2.5 - Article Eater Feedback Loop
Processes AE outputs to improve future searches.

This module implements the closed-loop integration:
1. AE extracts claims, rules, mechanisms from papers
2. This module ingests those outputs
3. Updates the knowledge graph with new knowledge
4. Identifies new gaps created by new knowledge
5. Generates follow-up queries to fill those gaps
6. Feeds back to Bibliographer for targeted searching

The key insight: every new piece of knowledge reveals new gaps.
- A new causal claim may lack mechanism evidence
- A theory test may reveal untested predictions
- A neural finding may not cover all environmental factors
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AEResult:
    """Parsed Article Eater result bundle."""
    paper_id: str
    status: str
    n_claims: int = 0
    n_rules: int = 0
    claims: List[Dict] = field(default_factory=list)
    rules: List[Dict] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)
    run_id: Optional[str] = None


@dataclass
class FollowUpQuery:
    """A query generated from AE feedback."""
    query: str
    reason: str
    source_paper_id: str
    source_claim_id: Optional[str] = None
    priority: float = 0.5
    gap_type: str = 'coverage'


class AEFeedbackLoop:
    """
    Process AE outputs to improve future AF searches.

    Implements the feedback cycle:
    AE extracts → update graph → find gaps → generate queries → AF searches
    """

    def __init__(
        self,
        database,
        output_dir: Path = None,
        claim_graph=None,
        gap_analyzer=None
    ):
        """
        Args:
            database: Article Finder database instance
            output_dir: Directory containing AE output bundles
            claim_graph: Optional ClaimGraph instance
            gap_analyzer: Optional GapAnalyzer instance
        """
        self.db = database
        self.output_dir = Path(output_dir) if output_dir else Path('./data/ae_outputs')
        self.claim_graph = claim_graph
        self.gap_analyzer = gap_analyzer

        # Track processed results
        self._processed_runs: Set[str] = set()
        self._load_processed_runs()

    def _load_processed_runs(self):
        """Load set of already-processed AE runs."""
        tracking_file = self.output_dir / '.processed_runs.json'
        if tracking_file.exists():
            with open(tracking_file) as f:
                self._processed_runs = set(json.load(f))

    def _save_processed_runs(self):
        """Save set of processed AE runs."""
        tracking_file = self.output_dir / '.processed_runs.json'
        tracking_file.parent.mkdir(parents=True, exist_ok=True)
        with open(tracking_file, 'w') as f:
            json.dump(list(self._processed_runs), f)

    # =========================================================================
    # INGEST AE OUTPUTS
    # =========================================================================

    def process_all_outputs(self, force: bool = False) -> Dict[str, Any]:
        """
        Process all AE output bundles.

        Args:
            force: If True, reprocess already-processed bundles

        Returns:
            Processing statistics
        """
        stats = {
            'bundles_found': 0,
            'bundles_processed': 0,
            'claims_ingested': 0,
            'rules_ingested': 0,
            'followup_queries': 0,
            'errors': []
        }

        if not self.output_dir.exists():
            logger.warning(f"AE output directory not found: {self.output_dir}")
            return stats

        # Find all output bundles
        bundles = list(self.output_dir.glob('output_*/result.json'))
        stats['bundles_found'] = len(bundles)

        for result_file in bundles:
            bundle_dir = result_file.parent
            run_id = bundle_dir.name

            if not force and run_id in self._processed_runs:
                continue

            try:
                result = self._process_bundle(bundle_dir)
                stats['bundles_processed'] += 1
                stats['claims_ingested'] += result.n_claims
                stats['rules_ingested'] += result.n_rules

                self._processed_runs.add(run_id)

            except Exception as e:
                logger.error(f"Error processing bundle {run_id}: {e}")
                stats['errors'].append(str(e))

        self._save_processed_runs()

        # Generate follow-up queries from new knowledge
        followup = self.generate_followup_queries()
        stats['followup_queries'] = len(followup)

        return stats

    def _process_bundle(self, bundle_dir: Path) -> AEResult:
        """Process a single AE output bundle."""
        result_file = bundle_dir / 'result.json'
        claims_file = bundle_dir / 'claims.jsonl'
        rules_file = bundle_dir / 'rules.jsonl'

        # Load result metadata
        with open(result_file) as f:
            result_data = json.load(f)

        result = AEResult(
            paper_id=result_data.get('paper_id', ''),
            status=result_data.get('status', 'UNKNOWN'),
            run_id=result_data.get('run_id'),
            n_claims=result_data.get('summary', {}).get('n_claims', 0),
            n_rules=result_data.get('summary', {}).get('n_rules', 0),
            errors=result_data.get('errors', [])
        )

        # Load claims
        if claims_file.exists():
            result.claims = self._load_jsonl(claims_file)
            self._ingest_claims(result.claims, result.paper_id)

        # Load rules
        if rules_file.exists():
            result.rules = self._load_jsonl(rules_file)
            self._ingest_rules(result.rules, result.paper_id)

        logger.info(f"Processed {bundle_dir.name}: {result.n_claims} claims, {result.n_rules} rules")

        return result

    def _load_jsonl(self, filepath: Path) -> List[Dict]:
        """Load JSONL file."""
        items = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

    def _ingest_claims(self, claims: List[Dict], paper_id: str):
        """Ingest claims into database."""
        with self.db.connection() as conn:
            for claim in claims:
                claim_id = claim.get('claim_id', f"claim:{paper_id}:{len(claims)}")

                conn.execute("""
                    INSERT OR REPLACE INTO claims
                    (claim_id, paper_id, claim_type, statement, constructs,
                     study_design, statistics, evidence, ae_confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    claim_id,
                    paper_id,
                    claim.get('claim_type'),
                    claim.get('statement'),
                    json.dumps(claim.get('constructs', {})),
                    json.dumps(claim.get('study_design', {})),
                    json.dumps(claim.get('statistics', {})),
                    json.dumps(claim.get('evidence', [])),
                    claim.get('ae_confidence', 0.0)
                ))

    def _ingest_rules(self, rules: List[Dict], paper_id: str):
        """Ingest rules into database."""
        with self.db.connection() as conn:
            for rule in rules:
                rule_id = rule.get('rule_id', f"rule:{paper_id}:{len(rules)}")

                conn.execute("""
                    INSERT OR REPLACE INTO rules
                    (rule_id, paper_id, rule_type, lhs, rhs, polarity,
                     strength, applicability, evidence_links, ae_confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    rule_id,
                    paper_id,
                    rule.get('rule_type'),
                    json.dumps(rule.get('lhs', [])),
                    json.dumps(rule.get('rhs', [])),
                    rule.get('polarity'),
                    json.dumps(rule.get('strength', {})),
                    json.dumps(rule.get('applicability', {})),
                    json.dumps(rule.get('evidence_links', [])),
                    rule.get('ae_confidence', 0.0)
                ))

    # =========================================================================
    # FOLLOW-UP QUERY GENERATION
    # =========================================================================

    def generate_followup_queries(self, limit: int = 50) -> List[FollowUpQuery]:
        """
        Generate follow-up queries based on newly ingested knowledge.

        New knowledge reveals new gaps:
        - Causal claims lacking mechanisms
        - Theory mentions without empirical tests
        - Neural findings without environmental factor coverage
        - Boundary conditions that need testing
        """
        queries = []

        # 1. Find causal claims lacking mechanism evidence
        queries.extend(self._queries_for_mechanism_gaps())

        # 2. Find claims mentioning theories without testing them
        queries.extend(self._queries_for_theory_gaps())

        # 3. Find claims with moderators that need boundary testing
        queries.extend(self._queries_for_boundary_gaps())

        # 4. Use GapAnalyzer if available for comprehensive gap analysis
        if self.gap_analyzer:
            gap_queries = self.gap_analyzer.get_priority_queries(limit=limit)
            for gq in gap_queries:
                queries.append(FollowUpQuery(
                    query=gq['query'],
                    reason=f"Gap analysis: {gq['gap_type']}",
                    source_paper_id='',
                    priority=gq['priority'],
                    gap_type=gq['gap_type']
                ))

        # Sort by priority and deduplicate
        queries.sort(key=lambda q: q.priority, reverse=True)

        seen = set()
        unique = []
        for q in queries:
            if q.query not in seen:
                seen.add(q.query)
                unique.append(q)

        return unique[:limit]

    def _queries_for_mechanism_gaps(self) -> List[FollowUpQuery]:
        """Generate queries for causal claims lacking mechanism evidence."""
        queries = []

        with self.db.connection() as conn:
            # Find causal claims without corresponding mechanistic claims
            rows = conn.execute("""
                SELECT c.claim_id, c.paper_id, c.statement, c.constructs
                FROM claims c
                WHERE c.claim_type = 'causal'
                  AND NOT EXISTS (
                      SELECT 1 FROM claims m
                      WHERE m.claim_type = 'mechanistic'
                        AND m.constructs LIKE '%' ||
                            json_extract(c.constructs, '$.environment_factors[0].id') || '%'
                  )
                LIMIT 20
            """).fetchall()

            for row in rows:
                constructs = json.loads(row['constructs']) if row['constructs'] else {}
                env_factors = constructs.get('environment_factors', [])
                outcomes = constructs.get('outcomes', [])

                if env_factors and outcomes:
                    iv = env_factors[0].get('role', '').replace('_', ' ')
                    dv = outcomes[0].get('role', '').replace('_', ' ')

                    if iv and dv:
                        queries.append(FollowUpQuery(
                            query=f'"{iv}" mechanism "{dv}" pathway',
                            reason=f"Causal claim lacks mechanism: {row['statement'][:50]}",
                            source_paper_id=row['paper_id'],
                            source_claim_id=row['claim_id'],
                            priority=0.75,
                            gap_type='mechanism'
                        ))

        return queries

    def _queries_for_theory_gaps(self) -> List[FollowUpQuery]:
        """Generate queries for theory mentions without empirical tests."""
        queries = []

        # Known theories to check for
        theories = [
            ('attention restoration', 'ART', 'theo.restoration.art'),
            ('stress recovery', 'SRT', 'theo.restoration.srt'),
            ('biophilia', 'biophilia hypothesis', 'theo.preference.biophilia'),
            ('prospect refuge', 'prospect-refuge', 'theo.perception.prospect_refuge'),
            ('affordance', 'Gibson affordances', 'theo.perception.affordance'),
        ]

        with self.db.connection() as conn:
            for theory_term, alt_term, theory_id in theories:
                # Check if we have claims mentioning this theory
                count = conn.execute("""
                    SELECT COUNT(*) as n
                    FROM claims
                    WHERE LOWER(statement) LIKE ?
                       OR LOWER(statement) LIKE ?
                """, (f'%{theory_term}%', f'%{alt_term}%')).fetchone()

                if count and count['n'] < 3:  # Under-tested
                    queries.append(FollowUpQuery(
                        query=f'"{theory_term}" empirical test evidence',
                        reason=f"Theory under-tested: {theory_term}",
                        source_paper_id='',
                        priority=0.8,
                        gap_type='theory'
                    ))
                    queries.append(FollowUpQuery(
                        query=f'"{theory_term}" experiment built environment',
                        reason=f"Theory under-tested: {theory_term}",
                        source_paper_id='',
                        priority=0.75,
                        gap_type='theory'
                    ))

        return queries

    def _queries_for_boundary_gaps(self) -> List[FollowUpQuery]:
        """Generate queries for boundary conditions that need testing."""
        queries = []

        with self.db.connection() as conn:
            # Find claims with moderators
            rows = conn.execute("""
                SELECT c.claim_id, c.paper_id, c.statement, c.constructs
                FROM claims c
                WHERE c.claim_type = 'moderated'
                   OR json_extract(c.constructs, '$.moderators') IS NOT NULL
                LIMIT 10
            """).fetchall()

            for row in rows:
                constructs = json.loads(row['constructs']) if row['constructs'] else {}
                moderators = constructs.get('moderators', [])

                for mod in moderators[:2]:
                    mod_name = mod.get('id', '').replace('_', ' ')
                    if mod_name:
                        # Search for studies testing this boundary condition
                        queries.append(FollowUpQuery(
                            query=f'"{mod_name}" moderator effect boundary',
                            reason=f"Boundary condition needs testing: {mod_name}",
                            source_paper_id=row['paper_id'],
                            source_claim_id=row['claim_id'],
                            priority=0.6,
                            gap_type='boundary'
                        ))

        return queries

    # =========================================================================
    # INTEGRATION WITH BIBLIOGRAPHER
    # =========================================================================

    def feed_to_bibliographer(self, bibliographer, limit: int = 20):
        """
        Feed follow-up queries to the Bibliographer as new cells.

        Args:
            bibliographer: Bibliographer instance
            limit: Max queries to add
        """
        followup = self.generate_followup_queries(limit=limit)

        added = 0
        for query in followup:
            cell_id = f"followup:{query.gap_type}:{hash(query.query) % 10000}"

            if cell_id not in bibliographer.state.cells:
                from search.bibliographer import CellProgress

                bibliographer.state.cells[cell_id] = CellProgress(
                    cell_id=cell_id,
                    factor_id=query.gap_type,
                    factor_name=query.reason[:50],
                    outcome_id='',
                    outcome_name='',
                    priority='HIGH' if query.priority > 0.7 else 'MEDIUM',
                    cell_type=query.gap_type,
                    factor_seeds=[query.query]  # Store query as seed
                )
                added += 1

        bibliographer.state.save(bibliographer.state_path)
        logger.info(f"Added {added} follow-up cells to Bibliographer")

        return added

    def get_feedback_summary(self) -> Dict[str, Any]:
        """Get summary of feedback loop state."""
        with self.db.connection() as conn:
            claims_count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            rules_count = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]

            # Count by claim type
            type_counts = {}
            for row in conn.execute("SELECT claim_type, COUNT(*) as n FROM claims GROUP BY claim_type"):
                type_counts[row['claim_type'] or 'unknown'] = row['n']

        return {
            'processed_bundles': len(self._processed_runs),
            'total_claims': claims_count,
            'total_rules': rules_count,
            'claims_by_type': type_counts,
            'pending_followup': len(self.generate_followup_queries())
        }
