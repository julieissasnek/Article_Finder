# Version: 3.2.2
"""
Article Finder v3.2.2 - Claim Synthesis
Meta-analytic tools for aggregating findings across claims.

Enables:
- Effect size aggregation (weighted mean)
- Heterogeneity detection (I²)
- Moderator identification
- Contradiction flagging
- Forest plot generation
"""

import logging
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class EffectDirection(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NULL = "null"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class EffectSizeData:
    """Extracted effect size from a claim."""
    claim_id: str
    paper_id: str
    effect_type: Optional[str] = None  # d, r, eta², etc.
    effect_value: Optional[float] = None
    variance: Optional[float] = None
    n: Optional[int] = None
    p_value: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    direction: EffectDirection = EffectDirection.UNKNOWN
    
    @property
    def weight(self) -> float:
        """Inverse variance weight (or n-based if no variance)."""
        if self.variance and self.variance > 0:
            return 1.0 / self.variance
        elif self.n and self.n > 0:
            return float(self.n)
        return 1.0
    
    @property
    def has_effect(self) -> bool:
        return self.effect_value is not None


@dataclass
class SynthesisResult:
    """Result of meta-analytic synthesis."""
    construct: str
    n_claims: int
    n_with_effect: int
    
    # Aggregate effect
    pooled_effect: Optional[float] = None
    pooled_se: Optional[float] = None
    pooled_ci_lower: Optional[float] = None
    pooled_ci_upper: Optional[float] = None
    pooled_p: Optional[float] = None
    
    # Heterogeneity
    q_statistic: Optional[float] = None
    i_squared: Optional[float] = None
    tau_squared: Optional[float] = None
    heterogeneity_level: Optional[str] = None  # low, moderate, high
    
    # Direction summary
    n_positive: int = 0
    n_negative: int = 0
    n_null: int = 0
    overall_direction: EffectDirection = EffectDirection.UNKNOWN
    
    # Moderators
    moderators_detected: List[str] = field(default_factory=list)
    
    # Contradictions
    contradictions: List[Dict] = field(default_factory=list)
    
    # Individual effects for forest plot
    effects: List[EffectSizeData] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'construct': self.construct,
            'n_claims': self.n_claims,
            'n_with_effect': self.n_with_effect,
            'pooled_effect': self.pooled_effect,
            'pooled_ci': [self.pooled_ci_lower, self.pooled_ci_upper] if self.pooled_ci_lower else None,
            'pooled_p': self.pooled_p,
            'i_squared': self.i_squared,
            'heterogeneity': self.heterogeneity_level,
            'direction': {
                'positive': self.n_positive,
                'negative': self.n_negative,
                'null': self.n_null,
                'overall': self.overall_direction.value
            },
            'moderators': self.moderators_detected,
            'contradictions': len(self.contradictions)
        }


class ClaimSynthesizer:
    """
    Synthesize findings from multiple claims.
    
    Provides meta-analytic aggregation and contradiction detection.
    """
    
    def __init__(self, database, claim_graph=None):
        """
        Args:
            database: Database instance
            claim_graph: Optional pre-built ClaimGraph
        """
        self.db = database
        self._graph = claim_graph
    
    @property
    def graph(self):
        """Lazy-load knowledge graph."""
        if self._graph is None:
            from knowledge.claim_graph import ClaimGraph
            self._graph = ClaimGraph(self.db)
            self._graph.build(force_rebuild=False)
        return self._graph
    
    def synthesize(self, construct: str) -> SynthesisResult:
        """
        Synthesize all claims about a construct.
        
        Args:
            construct: Construct ID or search term
            
        Returns:
            SynthesisResult with aggregated statistics
        """
        # Find matching constructs
        matches = self.graph.find_construct(construct)
        
        if not matches:
            return SynthesisResult(
                construct=construct,
                n_claims=0,
                n_with_effect=0
            )
        
        # Collect all claims
        all_claims = []
        seen_claim_ids = set()
        
        for match in matches:
            claims = self.graph.get_claims_about(match.node_id)
            for claim in claims:
                if claim.node_id not in seen_claim_ids:
                    seen_claim_ids.add(claim.node_id)
                    all_claims.append(claim)
        
        if not all_claims:
            return SynthesisResult(
                construct=construct,
                n_claims=0,
                n_with_effect=0
            )
        
        # Extract effect sizes
        effects = []
        for claim in all_claims:
            effect = self._extract_effect(claim)
            effects.append(effect)
        
        # Calculate synthesis
        result = self._calculate_synthesis(construct, effects)
        
        # Detect contradictions
        result.contradictions = self._detect_contradictions(effects)
        
        # Detect moderators
        result.moderators_detected = self._detect_moderators(all_claims)
        
        return result
    
    def _extract_effect(self, claim) -> EffectSizeData:
        """Extract effect size data from a claim node."""
        props = claim.properties
        
        effect = EffectSizeData(
            claim_id=claim.node_id,
            paper_id='',  # Would need to trace back
        )
        
        # Extract effect size
        es_value = props.get('effect_size')
        if es_value is not None:
            effect.effect_value = float(es_value)
        
        # Extract p-value
        p_val = props.get('p_value')
        if p_val is not None:
            effect.p_value = float(p_val)
        
        # Infer direction from statement
        statement = props.get('statement', '').lower()
        claim_type = props.get('claim_type', '')
        
        if claim_type == 'null':
            effect.direction = EffectDirection.NULL
        elif any(word in statement for word in ['increase', 'improve', 'enhance', 'positive', 'higher', 'better', 'more']):
            effect.direction = EffectDirection.POSITIVE
        elif any(word in statement for word in ['decrease', 'reduce', 'impair', 'negative', 'lower', 'worse', 'less']):
            effect.direction = EffectDirection.NEGATIVE
        
        return effect
    
    def _calculate_synthesis(self, construct: str, effects: List[EffectSizeData]) -> SynthesisResult:
        """Calculate aggregate statistics from effects."""
        result = SynthesisResult(
            construct=construct,
            n_claims=len(effects),
            n_with_effect=sum(1 for e in effects if e.has_effect)
        )
        
        result.effects = effects
        
        # Count directions
        for effect in effects:
            if effect.direction == EffectDirection.POSITIVE:
                result.n_positive += 1
            elif effect.direction == EffectDirection.NEGATIVE:
                result.n_negative += 1
            elif effect.direction == EffectDirection.NULL:
                result.n_null += 1
        
        # Determine overall direction
        if result.n_positive > result.n_negative and result.n_positive > result.n_null:
            result.overall_direction = EffectDirection.POSITIVE
        elif result.n_negative > result.n_positive and result.n_negative > result.n_null:
            result.overall_direction = EffectDirection.NEGATIVE
        elif result.n_null > result.n_positive and result.n_null > result.n_negative:
            result.overall_direction = EffectDirection.NULL
        elif result.n_positive > 0 and result.n_negative > 0:
            result.overall_direction = EffectDirection.MIXED
        
        # Calculate pooled effect (if we have effect sizes)
        effects_with_values = [e for e in effects if e.has_effect]
        
        if effects_with_values:
            result.pooled_effect, result.pooled_se = self._weighted_mean(effects_with_values)
            
            if result.pooled_se:
                result.pooled_ci_lower = result.pooled_effect - 1.96 * result.pooled_se
                result.pooled_ci_upper = result.pooled_effect + 1.96 * result.pooled_se
            
            # Calculate heterogeneity (simplified I²)
            if len(effects_with_values) >= 2:
                result.q_statistic, result.i_squared = self._calculate_heterogeneity(
                    effects_with_values, result.pooled_effect
                )
                
                if result.i_squared is not None:
                    if result.i_squared < 25:
                        result.heterogeneity_level = "low"
                    elif result.i_squared < 75:
                        result.heterogeneity_level = "moderate"
                    else:
                        result.heterogeneity_level = "high"
        
        return result
    
    def _weighted_mean(self, effects: List[EffectSizeData]) -> Tuple[Optional[float], Optional[float]]:
        """Calculate weighted mean effect size."""
        if not effects:
            return None, None
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for effect in effects:
            if effect.effect_value is not None:
                w = effect.weight
                weighted_sum += w * effect.effect_value
                total_weight += w
        
        if total_weight == 0:
            return None, None
        
        pooled = weighted_sum / total_weight
        se = math.sqrt(1.0 / total_weight) if total_weight > 0 else None
        
        return pooled, se
    
    def _calculate_heterogeneity(
        self, 
        effects: List[EffectSizeData], 
        pooled: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """Calculate Q statistic and I² for heterogeneity."""
        if len(effects) < 2 or pooled is None:
            return None, None
        
        # Q = sum of weighted squared deviations
        q = 0.0
        for effect in effects:
            if effect.effect_value is not None:
                w = effect.weight
                q += w * (effect.effect_value - pooled) ** 2
        
        # I² = (Q - df) / Q * 100
        df = len(effects) - 1
        
        if q <= df:
            i_squared = 0.0
        else:
            i_squared = ((q - df) / q) * 100
        
        return q, i_squared
    
    def _detect_contradictions(self, effects: List[EffectSizeData]) -> List[Dict]:
        """Detect contradictory findings."""
        contradictions = []
        
        positive = [e for e in effects if e.direction == EffectDirection.POSITIVE]
        negative = [e for e in effects if e.direction == EffectDirection.NEGATIVE]
        null = [e for e in effects if e.direction == EffectDirection.NULL]
        
        # Positive vs Negative
        for pos in positive[:5]:
            for neg in negative[:5]:
                contradictions.append({
                    'type': 'direction_conflict',
                    'claim_1': pos.claim_id,
                    'claim_2': neg.claim_id,
                    'direction_1': 'positive',
                    'direction_2': 'negative'
                })
        
        # Effect vs Null
        effect_claims = positive + negative
        for eff in effect_claims[:5]:
            for nul in null[:3]:
                contradictions.append({
                    'type': 'effect_vs_null',
                    'claim_1': eff.claim_id,
                    'claim_2': nul.claim_id,
                    'direction_1': eff.direction.value,
                    'direction_2': 'null'
                })
        
        return contradictions[:20]  # Limit
    
    def _detect_moderators(self, claims) -> List[str]:
        """Detect potential moderators from claim properties."""
        moderator_counts = defaultdict(int)
        
        for claim in claims:
            # Check for moderator mentions in constructs
            props = claim.properties
            
            # Look for explicit moderators (would come from claim.constructs.moderators)
            # For now, check claim_type
            if props.get('claim_type') == 'moderated':
                moderator_counts['effect_moderation'] += 1
        
        # Return moderators mentioned in multiple claims
        return [mod for mod, count in moderator_counts.items() if count >= 2]
    
    def synthesize_by_iv_dv(
        self, 
        iv_construct: str, 
        dv_construct: str
    ) -> SynthesisResult:
        """
        Synthesize claims linking a specific IV to a specific DV.
        """
        from knowledge.claim_graph import EdgeType
        
        # Find IV and DV constructs
        iv_matches = self.graph.find_construct(iv_construct)
        dv_matches = self.graph.find_construct(dv_construct)
        
        if not iv_matches or not dv_matches:
            return SynthesisResult(
                construct=f"{iv_construct} → {dv_construct}",
                n_claims=0,
                n_with_effect=0
            )
        
        # Find claims that link IV to DV
        relevant_claims = []
        
        for iv_node in iv_matches:
            # Get AFFECTS edges from IV
            affects_edges = self.graph.get_edges_from(iv_node.node_id, EdgeType.AFFECTS)
            
            for edge in affects_edges:
                # Check if target is one of our DVs
                if any(edge.target == dv.node_id for dv in dv_matches):
                    claim_id = edge.properties.get('claim_id')
                    if claim_id:
                        claim_node = self.graph.get_node(claim_id)
                        if claim_node:
                            relevant_claims.append(claim_node)
        
        if not relevant_claims:
            return SynthesisResult(
                construct=f"{iv_construct} → {dv_construct}",
                n_claims=0,
                n_with_effect=0
            )
        
        # Extract effects and synthesize
        effects = [self._extract_effect(claim) for claim in relevant_claims]
        result = self._calculate_synthesis(f"{iv_construct} → {dv_construct}", effects)
        result.contradictions = self._detect_contradictions(effects)
        
        return result
    
    def generate_forest_plot_data(self, result: SynthesisResult) -> Dict[str, Any]:
        """
        Generate data for a forest plot visualization.
        
        Returns data suitable for plotting with matplotlib or export.
        """
        if not result.effects:
            return {'studies': [], 'pooled': None}
        
        studies = []
        for i, effect in enumerate(result.effects):
            if effect.has_effect:
                studies.append({
                    'label': f"Study {i+1}",
                    'claim_id': effect.claim_id,
                    'effect': effect.effect_value,
                    'ci_lower': effect.ci_lower or (effect.effect_value - 0.2),
                    'ci_upper': effect.ci_upper or (effect.effect_value + 0.2),
                    'weight': effect.weight,
                    'direction': effect.direction.value
                })
        
        return {
            'studies': studies,
            'pooled': {
                'effect': result.pooled_effect,
                'ci_lower': result.pooled_ci_lower,
                'ci_upper': result.pooled_ci_upper
            } if result.pooled_effect else None,
            'heterogeneity': {
                'i_squared': result.i_squared,
                'level': result.heterogeneity_level
            }
        }
    
    def get_summary_text(self, result: SynthesisResult) -> str:
        """Generate human-readable summary of synthesis."""
        lines = []
        
        lines.append(f"=== Synthesis: {result.construct} ===")
        lines.append(f"Claims analyzed: {result.n_claims} ({result.n_with_effect} with effect sizes)")
        lines.append("")
        
        # Direction summary
        lines.append("Direction of findings:")
        lines.append(f"  Positive effects: {result.n_positive}")
        lines.append(f"  Negative effects: {result.n_negative}")
        lines.append(f"  Null findings:    {result.n_null}")
        lines.append(f"  Overall:          {result.overall_direction.value}")
        lines.append("")
        
        # Pooled effect
        if result.pooled_effect is not None:
            ci_str = ""
            if result.pooled_ci_lower is not None:
                ci_str = f" [{result.pooled_ci_lower:.2f}, {result.pooled_ci_upper:.2f}]"
            lines.append(f"Pooled effect: {result.pooled_effect:.3f}{ci_str}")
            
            if result.i_squared is not None:
                lines.append(f"Heterogeneity: I² = {result.i_squared:.1f}% ({result.heterogeneity_level})")
        else:
            lines.append("Pooled effect: Insufficient data")
        
        lines.append("")
        
        # Contradictions
        if result.contradictions:
            lines.append(f"Contradictions detected: {len(result.contradictions)}")
        
        # Moderators
        if result.moderators_detected:
            lines.append(f"Potential moderators: {', '.join(result.moderators_detected)}")
        
        return "\n".join(lines)


def synthesize_construct(database, construct: str) -> SynthesisResult:
    """Convenience function for synthesis."""
    synthesizer = ClaimSynthesizer(database)
    return synthesizer.synthesize(construct)
