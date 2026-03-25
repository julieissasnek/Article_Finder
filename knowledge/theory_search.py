"""
Article Finder - Theory-Aware Search Integration
Sprint AF-6: Theory-Driven Search

Extends Article Finder's search capabilities to find papers that test 
theory-derived predictions. Identifies high-VOI research opportunities.
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import logging

# Import from Article Eater's theory system
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "article_eater"))

try:
    from src.services.theory_registry import TheoryRegistry
    from src.services.prediction_generator import PredictionGenerator, Query, PredictionOutput
    from src.models.theory_models import (
        Prediction, Theory, TestingStatus, SupportLevel, Direction
    )
    THEORY_SYSTEM_AVAILABLE = True
except ImportError:
    THEORY_SYSTEM_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class TheoryTestingOpportunity:
    """A research opportunity to test a theory prediction."""
    prediction: 'Prediction'
    theory: 'Theory'
    voi_score: float  # Value of information
    search_queries: List[str]  # Generated search queries
    priority_rank: int
    rationale: str


@dataclass  
class TheoryGap:
    """An identified gap where theory predicts but evidence is missing."""
    prediction_id: str
    prediction_statement: str
    source_theory: str
    prior_confidence: float
    testing_status: str
    suggested_studies: List[str]


class TheoryAwareSearch:
    """
    Integrates theory-based predictions with Article Finder search.
    
    Capabilities:
    1. Generate search queries from untested predictions
    2. Rank papers by theory-testing potential
    3. Identify high-VOI research gaps
    4. Score search results by prediction relevance
    """
    
    def __init__(self, theory_registry: 'TheoryRegistry', finder_db=None):
        """
        Initialize theory-aware search.
        
        Args:
            theory_registry: TheoryRegistry instance from Article Eater
            finder_db: Optional Article Finder database connection
        """
        if not THEORY_SYSTEM_AVAILABLE:
            raise ImportError("Theory system not available. Ensure Article Eater is properly installed.")
        
        self.registry = theory_registry
        self.finder_db = finder_db
        self.generator = PredictionGenerator(theory_registry)
    
    def get_testing_opportunities(
        self, 
        limit: int = 20,
        min_prior_confidence: float = 0.5
    ) -> List[TheoryTestingOpportunity]:
        """
        Get ranked list of theory-testing opportunities.
        
        Returns predictions that:
        1. Are untested or partially tested
        2. Have high prior confidence (theory strongly predicts)
        3. Would significantly update knowledge if tested
        
        Args:
            limit: Maximum opportunities to return
            min_prior_confidence: Minimum prior confidence threshold
            
        Returns:
            Ranked list of TheoryTestingOpportunity
        """
        opportunities = []
        
        # Get all predictions
        for theory in self.registry.list_theories():
            full_theory = self.registry.get_theory(theory.theory_id)
            if not full_theory:
                continue
            
            for pred in full_theory.all_predictions:
                # Filter by testing status
                if pred.testing_status not in [TestingStatus.UNTESTED, TestingStatus.PARTIALLY_TESTED]:
                    continue
                
                # Filter by confidence
                if pred.prior_confidence < min_prior_confidence:
                    continue
                
                # Calculate VOI
                voi = self._calculate_prediction_voi(pred, full_theory)
                
                # Generate search queries
                queries = self._generate_search_queries(pred, full_theory)
                
                # Create rationale
                rationale = self._generate_rationale(pred, full_theory, voi)
                
                opportunities.append(TheoryTestingOpportunity(
                    prediction=pred,
                    theory=full_theory,
                    voi_score=voi,
                    search_queries=queries,
                    priority_rank=0,  # Set after sorting
                    rationale=rationale,
                ))
        
        # Sort by VOI
        opportunities.sort(key=lambda x: x.voi_score, reverse=True)
        
        # Set ranks
        for i, opp in enumerate(opportunities[:limit]):
            opp.priority_rank = i + 1
        
        return opportunities[:limit]
    
    def _calculate_prediction_voi(self, pred: 'Prediction', theory: 'Theory') -> float:
        """Calculate Value of Information for testing a prediction."""
        voi = 0.0
        
        # Base VOI from prior confidence (higher confidence = more to learn)
        voi += 0.3 * pred.prior_confidence
        
        # Bonus for untested vs partially tested
        if pred.testing_status == TestingStatus.UNTESTED:
            voi += 0.2
        
        # Bonus for core theory (testing validates/invalidates important theory)
        voi += 0.2 * theory.overall_confidence
        
        # Bonus for clear quantitative prediction
        if pred.quantitative:
            voi += 0.1
        
        # Bonus for derivations that would test multiple claims
        if len(pred.derivation_chain) >= 2:
            voi += 0.1
        
        # Penalty for very narrow applicability
        if pred.generality.value == "context_specific":
            voi -= 0.1
        
        return round(min(1.0, max(0.0, voi)), 2)
    
    def _generate_search_queries(self, pred: 'Prediction', theory: 'Theory') -> List[str]:
        """Generate search queries to find papers testing a prediction."""
        queries = []
        
        # Extract key terms from prediction
        outcome = pred.consequent_outcome.replace('_', ' ')
        direction = pred.consequent_direction.value
        
        # Basic outcome query
        queries.append(f'"{outcome}" effect study')
        
        # Theory-specific query
        queries.append(f'{theory.name} {outcome} empirical')
        
        # Antecedent-based queries
        if pred.antecedent_env_conditions:
            for cond in pred.antecedent_env_conditions[:2]:
                env_type = cond.get('type', '').replace('_', ' ')
                if env_type:
                    queries.append(f'{env_type} {outcome} experiment')
        
        # Direction-specific
        if direction == 'positive':
            queries.append(f'{outcome} improvement intervention')
        elif direction == 'negative':
            queries.append(f'{outcome} reduction stress')
        
        # Deduplicate and clean
        seen = set()
        clean_queries = []
        for q in queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                clean_queries.append(q)
        
        return clean_queries[:5]
    
    def _generate_rationale(self, pred: 'Prediction', theory: 'Theory', voi: float) -> str:
        """Generate human-readable rationale for why this is worth testing."""
        parts = []
        
        parts.append(f"{theory.name} (confidence: {theory.overall_confidence:.0%}) predicts:")
        parts.append(f'"{pred.statement[:100]}..."')
        
        if pred.testing_status == TestingStatus.UNTESTED:
            parts.append("This prediction has NOT been directly tested.")
        else:
            parts.append(f"Current support: {pred.overall_support.value}")
        
        parts.append(f"Value of additional research: {voi:.0%}")
        
        if pred.derivation_chain:
            parts.append(f"Tests {len(pred.derivation_chain)} core claims if supported/refuted.")
        
        return " ".join(parts)
    
    def identify_gaps(self) -> List[TheoryGap]:
        """
        Identify gaps where theory makes predictions but evidence is missing.
        
        Returns:
            List of TheoryGap objects
        """
        gaps = []
        
        for theory in self.registry.list_theories():
            full_theory = self.registry.get_theory(theory.theory_id)
            if not full_theory:
                continue
            
            for pred in full_theory.all_predictions:
                if pred.testing_status in [TestingStatus.UNTESTED, TestingStatus.PARTIALLY_TESTED]:
                    # Generate study suggestions
                    suggestions = self._suggest_studies(pred, full_theory)
                    
                    gaps.append(TheoryGap(
                        prediction_id=pred.prediction_id,
                        prediction_statement=pred.statement,
                        source_theory=theory.name,
                        prior_confidence=pred.prior_confidence,
                        testing_status=pred.testing_status.value,
                        suggested_studies=suggestions,
                    ))
        
        # Sort by prior confidence (most confident predictions first)
        gaps.sort(key=lambda g: g.prior_confidence, reverse=True)
        
        return gaps
    
    def _suggest_studies(self, pred: 'Prediction', theory: 'Theory') -> List[str]:
        """Suggest study designs to test a prediction."""
        suggestions = []
        
        outcome = pred.consequent_outcome.replace('_', ' ')
        
        # Basic experimental suggestion
        suggestions.append(f"Randomized experiment manipulating environmental conditions and measuring {outcome}")
        
        # Based on temporal frame
        if pred.antecedent_temporal:
            temporal = pred.antecedent_temporal.get('exposure_type', '')
            if temporal == 'acute':
                suggestions.append("Short-term exposure study (minutes to hours)")
            elif temporal == 'chronic':
                suggestions.append("Longitudinal study tracking outcomes over weeks/months")
        
        # Based on population
        if pred.applicable_populations and pred.applicable_populations != ['all']:
            pop = pred.applicable_populations[0]
            suggestions.append(f"Study specifically in {pop} population")
        
        return suggestions[:3]
    
    def score_paper_relevance(
        self,
        paper_title: str,
        paper_abstract: str,
        predictions: Optional[List['Prediction']] = None
    ) -> Dict[str, Any]:
        """
        Score a paper's relevance to testing theory predictions.
        
        Args:
            paper_title: Paper title
            paper_abstract: Paper abstract
            predictions: Optional list of predictions to score against
                        (if None, scores against all untested predictions)
        
        Returns:
            Dict with relevance scores and matched predictions
        """
        if predictions is None:
            predictions = self.registry.get_untested_predictions(limit=50)
        
        text = f"{paper_title} {paper_abstract}".lower()
        
        matches = []
        for pred in predictions:
            score = 0.0
            match_reasons = []
            
            # Check outcome mention
            outcome_terms = pred.consequent_outcome.lower().replace('_', ' ').split()
            outcome_matches = sum(1 for term in outcome_terms if term in text and len(term) > 3)
            if outcome_matches > 0:
                score += 0.3 * (outcome_matches / len(outcome_terms))
                match_reasons.append(f"Mentions outcome: {pred.consequent_outcome}")
            
            # Check theory mention
            theory = self.registry.get_theory(pred.source_theory_id)
            if theory:
                theory_name_lower = theory.name.lower()
                if theory_name_lower in text or any(alias.lower() in text for alias in theory.aliases):
                    score += 0.3
                    match_reasons.append(f"Mentions theory: {theory.name}")
            
            # Check key terms from statement
            statement_terms = [t for t in pred.statement.lower().split() if len(t) > 4][:10]
            term_matches = sum(1 for term in statement_terms if term in text)
            if term_matches >= 2:
                score += 0.2 * min(1.0, term_matches / 5)
                match_reasons.append(f"Statement term overlap: {term_matches}")
            
            # Check environmental conditions
            if pred.antecedent_env_conditions:
                for cond in pred.antecedent_env_conditions:
                    env_type = cond.get('type', '').lower().replace('_', ' ')
                    if env_type and env_type in text:
                        score += 0.2
                        match_reasons.append(f"Environment match: {env_type}")
                        break
            
            if score > 0.2:
                matches.append({
                    'prediction_id': pred.prediction_id,
                    'prediction_statement': pred.statement[:100],
                    'source_theory': pred.source_theory_id,
                    'relevance_score': round(score, 2),
                    'match_reasons': match_reasons,
                })
        
        # Sort by relevance
        matches.sort(key=lambda m: m['relevance_score'], reverse=True)
        
        # Overall paper relevance
        overall_score = matches[0]['relevance_score'] if matches else 0.0
        
        return {
            'paper_title': paper_title,
            'overall_relevance': round(overall_score, 2),
            'n_prediction_matches': len(matches),
            'top_matches': matches[:5],
            'is_theory_testing_candidate': overall_score >= 0.4,
        }
    
    def generate_theory_query(
        self,
        iv: str,
        dv: str,
        context: Optional[Dict[str, Any]] = None
    ) -> PredictionOutput:
        """
        Generate a full prediction analysis for a query.
        
        This is the main interface for asking "What does theory predict about X → Y?"
        
        Args:
            iv: Independent variable (environmental factor)
            dv: Dependent variable (outcome)
            context: Optional context (population, environment_type, temporal_frame)
            
        Returns:
            PredictionOutput with theory analysis and prior distribution
        """
        context = context or {}
        
        query = Query(
            query_id=f"query:{iv}:{dv}",
            independent_variable=iv,
            dependent_variable=dv,
            population=context.get('population'),
            environment_type=context.get('environment_type'),
            temporal_frame=context.get('temporal_frame'),
            additional_conditions=context.get('conditions', []),
        )
        
        return self.generator.generate(query)


def create_theory_search(ae_db_path: str, af_db_path: Optional[str] = None) -> TheoryAwareSearch:
    """
    Factory function to create a TheoryAwareSearch instance.
    
    Args:
        ae_db_path: Path to Article Eater database with theory registry
        af_db_path: Optional path to Article Finder database
        
    Returns:
        Configured TheoryAwareSearch instance
    """
    registry = TheoryRegistry(ae_db_path)
    return TheoryAwareSearch(registry, finder_db=af_db_path)
