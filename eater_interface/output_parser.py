# Version: 3.2.2
"""
Article Finder v3 - Article Eater Output Parser
Parses output bundles from Article Eater and imports into database
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EaterResult:
    """Parsed result from Article Eater."""
    paper_id: str
    pdf_sha256: str
    run_id: str
    status: str  # SUCCESS | PARTIAL_SUCCESS | FAIL
    profile: str  # fast | standard | deep
    hitl: str     # off | auto | required
    
    # Summary
    n_claims: int
    n_rules: int
    n_effect_sizes: int
    n_population_records: int
    n_environment_factors: int
    
    # Quality
    confidence: float
    blocking_issues: List[str]
    warnings: List[str]
    errors: List[str]
    
    # Paths
    output_path: Path


@dataclass
class ParsedClaim:
    """A single claim parsed from claims.jsonl."""
    claim_id: str
    paper_id: str
    claim_type: str
    statement: str
    
    # Constructs
    environment_factors: List[Dict]
    outcomes: List[Dict]
    mediators: List[Dict]
    moderators: List[Dict]
    
    # Study details
    design: Optional[str]
    sample_n: Optional[int]
    population: Optional[str]
    setting: Optional[str]
    task: Optional[List[Dict]]
    
    # Statistics
    effect_size_type: Optional[str]
    effect_size_value: Optional[float]
    p_value: Optional[float]
    ci95_low: Optional[float]
    ci95_high: Optional[float]
    
    # Evidence
    evidence_spans: List[Dict]
    ae_confidence: float


@dataclass
class ParsedRule:
    """A single rule parsed from rules.jsonl."""
    rule_id: str
    paper_id: str
    rule_type: str
    
    lhs: List[Dict]
    rhs: List[Dict]
    polarity: str
    
    strength_kind: Optional[str]
    strength_type: Optional[str]
    strength_value: Optional[float]
    
    population: List[Dict]
    setting: List[Dict]
    boundary_conditions: List[str]
    
    evidence_links: List[str]
    ae_confidence: float


class OutputParser:
    """
    Parses Article Eater output bundles.
    
    Expected bundle structure:
    - result.json (required)
    - claims.jsonl (required if SUCCESS)
    - rules.jsonl (required if SUCCESS)
    - provenance.json (optional)
    - audit.log.jsonl (optional)
    - fulltext.extracted.txt (optional)
    - tables/ (optional)
    - figures/ (optional)
    """
    
    RESULT_SCHEMA = "ae.result.v1"
    CLAIM_SCHEMA = "ae.claim.v1"
    RULE_SCHEMA = "ae.rule.v1"
    
    def __init__(self, bundle_path: Path):
        """
        Initialize parser with an output bundle path.
        
        Args:
            bundle_path: Path to Article Eater output bundle directory
        """
        self.bundle_path = Path(bundle_path)
        self._result: Optional[EaterResult] = None
    
    def parse_result(self) -> EaterResult:
        """
        Parse result.json and return EaterResult.
        
        Raises:
            FileNotFoundError: If result.json doesn't exist
            ValueError: If result.json has wrong schema
        """
        result_path = self.bundle_path / "result.json"
        
        if not result_path.exists():
            raise FileNotFoundError(f"result.json not found in {self.bundle_path}")
        
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate schema
        if data.get('schema') != self.RESULT_SCHEMA:
            raise ValueError(
                f"Wrong schema version: {data.get('schema')}, expected {self.RESULT_SCHEMA}"
            )
        
        summary = data.get('summary', {})
        quality = data.get('quality', {})
        
        self._result = EaterResult(
            paper_id=data['paper_id'],
            pdf_sha256=data.get('pdf_sha256', ''),
            run_id=data.get('run_id', ''),
            status=data['status'],
            profile=data.get('profile', 'standard'),
            hitl=data.get('hitl', 'auto'),
            n_claims=summary.get('n_claims', 0),
            n_rules=summary.get('n_rules', 0),
            n_effect_sizes=summary.get('n_effect_sizes', 0),
            n_population_records=summary.get('n_population_records', 0),
            n_environment_factors=summary.get('n_environment_factors', 0),
            confidence=quality.get('confidence', 0.0),
            blocking_issues=quality.get('blocking_issues', []),
            warnings=quality.get('warnings', []),
            errors=data.get('errors', []),
            output_path=self.bundle_path
        )
        
        return self._result
    
    def get_result(self) -> EaterResult:
        """Get parsed result, parsing if necessary."""
        if self._result is None:
            self.parse_result()
        return self._result
    
    def iter_claims(self) -> Generator[ParsedClaim, None, None]:
        """
        Iterate over claims from claims.jsonl.
        
        Yields:
            ParsedClaim objects
        """
        claims_path = self.bundle_path / "claims.jsonl"
        
        if not claims_path.exists():
            return
        
        with open(claims_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    yield self._parse_claim(data)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse claim at line {line_num}: {e}")
                except KeyError as e:
                    print(f"Warning: Missing field in claim at line {line_num}: {e}")
    
    def _parse_claim(self, data: Dict) -> ParsedClaim:
        """Parse a single claim dictionary."""
        constructs = data.get('constructs', {})
        study = data.get('study', {})
        stats = data.get('statistics', {})
        
        # Parse CI if present
        ci95 = stats.get('ci95')
        ci95_low = ci95[0] if ci95 and len(ci95) >= 2 else None
        ci95_high = ci95[1] if ci95 and len(ci95) >= 2 else None
        
        # Parse effect size
        effect_size = stats.get('effect_size', {})
        
        return ParsedClaim(
            claim_id=data['claim_id'],
            paper_id=data['paper_id'],
            claim_type=data.get('claim_type', 'unknown'),
            statement=data.get('statement', ''),
            environment_factors=constructs.get('environment_factors', []),
            outcomes=constructs.get('outcomes', []),
            mediators=constructs.get('mediators', []),
            moderators=constructs.get('moderators', []),
            design=study.get('design'),
            sample_n=study.get('sample', {}).get('n'),
            population=study.get('sample', {}).get('population'),
            setting=study.get('setting', [{}])[0].get('id') if study.get('setting') else None,
            task=study.get('task'),
            effect_size_type=effect_size.get('type'),
            effect_size_value=effect_size.get('value'),
            p_value=stats.get('p_value'),
            ci95_low=ci95_low,
            ci95_high=ci95_high,
            evidence_spans=data.get('evidence', []),
            ae_confidence=data.get('ae_confidence', 0.0)
        )
    
    def iter_rules(self) -> Generator[ParsedRule, None, None]:
        """
        Iterate over rules from rules.jsonl.
        
        Yields:
            ParsedRule objects
        """
        rules_path = self.bundle_path / "rules.jsonl"
        
        if not rules_path.exists():
            return
        
        with open(rules_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    yield self._parse_rule(data)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse rule at line {line_num}: {e}")
                except KeyError as e:
                    print(f"Warning: Missing field in rule at line {line_num}: {e}")
    
    def _parse_rule(self, data: Dict) -> ParsedRule:
        """Parse a single rule dictionary."""
        strength = data.get('strength', {})
        applicability = data.get('applicability', {})
        
        return ParsedRule(
            rule_id=data['rule_id'],
            paper_id=data['paper_id'],
            rule_type=data.get('rule_type', 'edge'),
            lhs=data.get('lhs', []),
            rhs=data.get('rhs', []),
            polarity=data.get('polarity', 'unknown'),
            strength_kind=strength.get('kind'),
            strength_type=strength.get('type'),
            strength_value=strength.get('value'),
            population=applicability.get('population', []),
            setting=applicability.get('setting', []),
            boundary_conditions=applicability.get('boundary_conditions', []),
            evidence_links=data.get('evidence_links', []),
            ae_confidence=data.get('ae_confidence', 0.0)
        )
    
    def get_all_claims(self) -> List[ParsedClaim]:
        """Get all claims as a list."""
        return list(self.iter_claims())
    
    def get_all_rules(self) -> List[ParsedRule]:
        """Get all rules as a list."""
        return list(self.iter_rules())
    
    def get_provenance(self) -> Optional[Dict]:
        """Get provenance information if available."""
        provenance_path = self.bundle_path / "provenance.json"
        
        if not provenance_path.exists():
            return None
        
        with open(provenance_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_extracted_fulltext(self) -> Optional[str]:
        """Get extracted fulltext if available."""
        fulltext_path = self.bundle_path / "fulltext.extracted.txt"
        
        if not fulltext_path.exists():
            return None
        
        with open(fulltext_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def has_review_items(self) -> bool:
        """Check if there are items needing human review."""
        review_path = self.bundle_path / "review_items.jsonl"
        return review_path.exists()
    
    def get_review_items(self) -> List[Dict]:
        """Get items needing human review."""
        review_path = self.bundle_path / "review_items.jsonl"
        
        if not review_path.exists():
            return []
        
        items = []
        with open(review_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        
        return items


def map_eater_status_to_finder(eater_status: str) -> str:
    """
    Map Article Eater status to Article Finder corpus status.
    
    Args:
        eater_status: SUCCESS | PARTIAL_SUCCESS | FAIL
        
    Returns:
        Finder status: processed_success | processed_partial | processed_fail | needs_human_review
    """
    mapping = {
        'SUCCESS': 'processed_success',
        'PARTIAL_SUCCESS': 'processed_partial',
        'FAIL': 'processed_fail'
    }
    return mapping.get(eater_status, 'needs_human_review')


class OutputImporter:
    """
    Imports Article Eater outputs into the Article Finder database.
    """
    
    def __init__(self, database):
        """
        Initialize importer with database connection.
        
        Args:
            database: Article Finder Database instance
        """
        self.db = database
    
    def import_bundle(self, bundle_path: Path) -> Dict[str, Any]:
        """
        Import an Article Eater output bundle into the database.
        
        Args:
            bundle_path: Path to the output bundle
            
        Returns:
            Import summary with counts
        """
        parser = OutputParser(bundle_path)
        result = parser.parse_result()
        
        # Update paper status and AE metadata
        paper_update = {
            'ae_output_path': str(bundle_path),
            'ae_run_id': result.run_id,
            'ae_profile': result.profile,
            'ae_status': result.status,
            'ae_n_claims': result.n_claims,
            'ae_n_rules': result.n_rules,
            'ae_confidence': result.confidence,
            'ae_warnings': result.warnings,
            'status': map_eater_status_to_finder(result.status)
        }
        
        # Get existing paper
        paper = self.db.get_paper(result.paper_id)
        if paper:
            paper.update(paper_update)
            self.db.add_paper(paper)
        
        # Import claims
        claims_imported = 0
        for claim in parser.iter_claims():
            self.db.add_claim({
                'claim_id': claim.claim_id,
                'paper_id': claim.paper_id,
                'claim_type': claim.claim_type,
                'statement': claim.statement,
                'environment_factors': claim.environment_factors,
                'outcomes': claim.outcomes,
                'mediators': claim.mediators,
                'moderators': claim.moderators,
                'design': claim.design,
                'sample_n': claim.sample_n,
                'population': claim.population,
                'setting': claim.setting,
                'effect_size_type': claim.effect_size_type,
                'effect_size_value': claim.effect_size_value,
                'p_value': claim.p_value,
                'ci95_low': claim.ci95_low,
                'ci95_high': claim.ci95_high,
                'evidence_spans': claim.evidence_spans,
                'ae_confidence': claim.ae_confidence,
                'ae_run_id': result.run_id
            })
            claims_imported += 1
        
        # Import rules
        rules_imported = 0
        for rule in parser.iter_rules():
            self.db.add_rule({
                'rule_id': rule.rule_id,
                'paper_id': rule.paper_id,
                'rule_type': rule.rule_type,
                'lhs': rule.lhs,
                'rhs': rule.rhs,
                'polarity': rule.polarity,
                'strength_kind': rule.strength_kind,
                'strength_type': rule.strength_type,
                'strength_value': rule.strength_value,
                'population': rule.population,
                'setting': rule.setting,
                'boundary_conditions': rule.boundary_conditions,
                'evidence_links': rule.evidence_links,
                'ae_confidence': rule.ae_confidence,
                'ae_run_id': result.run_id
            })
            rules_imported += 1
        
        return {
            'paper_id': result.paper_id,
            'status': result.status,
            'claims_imported': claims_imported,
            'rules_imported': rules_imported,
            'confidence': result.confidence,
            'warnings': result.warnings,
            'needs_review': parser.has_review_items()
        }
