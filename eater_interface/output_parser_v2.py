# Version: 3.2.2
"""
Article Finder v3 - Article Eater Output Parser (Contract-Compliant)
Parses output bundles matching AE schemas exactly.

Schema sources:
- ae.result.v1.schema.json
- ae.claim.v1.schema.json  
- ae.rule.v1.schema.json
- ae.provenance.v1.schema.json
- ae.audit_event.v1.schema.json
- ae.review_item.v1.schema.json
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================================
# DATA CLASSES MATCHING EXACT SCHEMAS
# ============================================================================

@dataclass
class ConstructItem:
    """Matches ae.claim.v1 construct_item."""
    id: str
    role: str
    direction: Optional[str] = None


@dataclass
class ModeratorItem:
    """Matches ae.claim.v1 moderator_item."""
    id: str
    value: Any  # string | number | null


@dataclass
class Sample:
    """Matches ae.claim.v1 sample."""
    n: Optional[int]
    population: Optional[str]
    age_mean: Optional[float]
    country: Optional[str]


@dataclass
class TaskItem:
    """Matches ae.claim.v1 task_item."""
    id: str
    name: str


@dataclass
class SettingItem:
    """Matches ae.claim.v1 setting_item."""
    id: str
    notes: str


@dataclass
class EffectSize:
    """Matches ae.claim.v1 effect_size."""
    type: Optional[str]
    value: Optional[float]


@dataclass
class EvidenceItem:
    """Matches ae.claim.v1 evidence_item."""
    kind: str  # span | table_cell | figure_ref | manual_note
    source: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    table_id: Optional[str] = None
    row: Optional[int] = None
    col: Optional[str] = None
    figure_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class Study:
    """Matches ae.claim.v1 study."""
    design: str
    sample: Sample
    task: List[TaskItem]
    setting: List[SettingItem]


@dataclass
class Statistics:
    """Matches ae.claim.v1 statistics."""
    effect_size: EffectSize
    p_value: Optional[float]
    ci95: Optional[List[float]]  # [low, high] or null


@dataclass
class Constructs:
    """Matches ae.claim.v1 constructs."""
    environment_factors: List[ConstructItem]
    outcomes: List[ConstructItem]
    mediators: List[ConstructItem]
    moderators: List[ModeratorItem]


@dataclass
class ParsedClaim:
    """
    Complete claim matching ae.claim.v1 schema exactly.
    
    Required fields: schema, claim_id, paper_id, claim_type, statement,
                    constructs, study, statistics, evidence, constraints, ae_confidence
    """
    schema: str  # Must be "ae.claim.v1"
    claim_id: str
    paper_id: str
    claim_type: str  # causal|associational|null|moderated|mechanistic|descriptive
    statement: str
    constructs: Constructs
    study: Study
    statistics: Statistics
    evidence: List[EvidenceItem]
    constraints: List[str]
    ae_confidence: float


@dataclass
class VarState:
    """Matches ae.rule.v1 var_state."""
    var: str
    state: str


@dataclass 
class Strength:
    """Matches ae.rule.v1 strength."""
    kind: str
    type: Optional[str] = None
    value: Optional[float] = None


@dataclass
class PopulationItem:
    """Matches ae.rule.v1 applicability.population item."""
    id: str


@dataclass
class SettingIdItem:
    """Matches ae.rule.v1 applicability.setting item."""
    id: str


@dataclass
class Applicability:
    """Matches ae.rule.v1 applicability."""
    population: List[PopulationItem]
    setting: List[SettingIdItem]
    boundary_conditions: List[str]


@dataclass
class EvidenceLink:
    """Matches ae.rule.v1 evidence_links item."""
    claim_id: str


@dataclass
class BNMapping:
    """Matches ae.rule.v1 bn_mapping."""
    node_suggestions: List[str]
    discretization_hint: str


@dataclass
class ParsedRule:
    """
    Complete rule matching ae.rule.v1 schema exactly.
    
    Required fields: schema, rule_id, paper_id, rule_type, lhs, rhs, polarity,
                    strength, applicability, evidence_links, bn_mapping, ae_confidence
    """
    schema: str  # Must be "ae.rule.v1"
    rule_id: str
    paper_id: str
    rule_type: str  # edge|cpd_hint|prior|constraint|interaction
    lhs: List[VarState]
    rhs: List[VarState]
    polarity: str  # positive|negative|null|u_shaped|unknown
    strength: Strength
    applicability: Applicability
    evidence_links: List[EvidenceLink]
    bn_mapping: BNMapping
    ae_confidence: float


@dataclass
class ErrorItem:
    """Matches ae.result.v1 errors item."""
    code: str
    message: str


@dataclass
class Summary:
    """Matches ae.result.v1 summary."""
    n_claims: int
    n_rules: int
    n_effect_sizes: int
    n_population_records: int
    n_environment_factors: int


@dataclass
class Artifacts:
    """Matches ae.result.v1 artifacts."""
    claims_jsonl: str
    rules_jsonl: str
    provenance_json: str
    audit_log_jsonl: str


@dataclass
class Quality:
    """Matches ae.result.v1 quality."""
    confidence: float
    blocking_issues: List[str]
    warnings: List[str]


@dataclass
class EaterResult:
    """
    Complete result matching ae.result.v1 schema exactly.
    
    Required fields: schema, paper_id, pdf_sha256, run_id, status, profile,
                    hitl, summary, artifacts, quality, errors
    """
    schema: str  # Must be "ae.result.v1"
    paper_id: str
    pdf_sha256: str
    run_id: str
    status: str  # SUCCESS | PARTIAL_SUCCESS | FAIL
    profile: str  # fast | standard | deep
    hitl: str     # off | auto | required
    summary: Summary
    artifacts: Artifacts
    quality: Quality
    errors: List[ErrorItem]
    
    # Convenience field (not in schema)
    output_path: Optional[Path] = None


# ============================================================================
# PARSER
# ============================================================================

class OutputParser:
    """
    Parses Article Eater output bundles matching contract exactly.
    
    Expected bundle structure:
    Required:
      - result.json (ae.result.v1)
      - claims.jsonl (ae.claim.v1 records)
      - rules.jsonl (ae.rule.v1 records)
      - provenance.json (ae.provenance.v1)
      - audit.log.jsonl (ae.audit_event.v1 records)
    
    Optional:
      - review_items.jsonl (ae.review_item.v1 records)
      - fulltext.extracted.txt
      - tables/, figures/, spans.jsonl, cost.json
    """
    
    def __init__(self, bundle_path: Path):
        self.bundle_path = Path(bundle_path)
        self._result: Optional[EaterResult] = None
    
    def parse_result(self) -> EaterResult:
        """Parse result.json and return EaterResult."""
        result_path = self.bundle_path / "result.json"
        
        if not result_path.exists():
            raise FileNotFoundError(f"result.json not found in {self.bundle_path}")
        
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate schema
        if data.get('schema') != "ae.result.v1":
            raise ValueError(f"Wrong schema: {data.get('schema')}, expected ae.result.v1")
        
        # Parse summary
        summary_data = data.get('summary', {})
        summary = Summary(
            n_claims=summary_data.get('n_claims', 0),
            n_rules=summary_data.get('n_rules', 0),
            n_effect_sizes=summary_data.get('n_effect_sizes', 0),
            n_population_records=summary_data.get('n_population_records', 0),
            n_environment_factors=summary_data.get('n_environment_factors', 0)
        )
        
        # Parse artifacts
        artifacts_data = data.get('artifacts', {})
        artifacts = Artifacts(
            claims_jsonl=artifacts_data.get('claims_jsonl', 'claims.jsonl'),
            rules_jsonl=artifacts_data.get('rules_jsonl', 'rules.jsonl'),
            provenance_json=artifacts_data.get('provenance_json', 'provenance.json'),
            audit_log_jsonl=artifacts_data.get('audit_log_jsonl', 'audit.log.jsonl')
        )
        
        # Parse quality
        quality_data = data.get('quality', {})
        quality = Quality(
            confidence=quality_data.get('confidence', 0.0),
            blocking_issues=quality_data.get('blocking_issues', []),
            warnings=quality_data.get('warnings', [])
        )
        
        # Parse errors
        errors = [
            ErrorItem(code=e.get('code', 'unknown'), message=e.get('message', ''))
            for e in data.get('errors', [])
        ]
        
        self._result = EaterResult(
            schema=data['schema'],
            paper_id=data['paper_id'],
            pdf_sha256=data.get('pdf_sha256', ''),
            run_id=data.get('run_id', ''),
            status=data['status'],
            profile=data.get('profile', 'standard'),
            hitl=data.get('hitl', 'auto'),
            summary=summary,
            artifacts=artifacts,
            quality=quality,
            errors=errors,
            output_path=self.bundle_path
        )
        
        return self._result
    
    def get_result(self) -> EaterResult:
        """Get parsed result, parsing if necessary."""
        if self._result is None:
            self.parse_result()
        return self._result
    
    def iter_claims(self) -> Generator[ParsedClaim, None, None]:
        """Iterate over claims from claims.jsonl."""
        result = self.get_result()
        claims_path = self.bundle_path / result.artifacts.claims_jsonl
        
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
                except Exception as e:
                    print(f"Warning: Error parsing claim at line {line_num}: {e}")
    
    def _parse_claim(self, data: Dict) -> ParsedClaim:
        """Parse a single claim dictionary."""
        
        # Parse constructs
        constructs_data = data.get('constructs', {})
        constructs = Constructs(
            environment_factors=[
                ConstructItem(id=c['id'], role=c['role'], direction=c.get('direction'))
                for c in constructs_data.get('environment_factors', [])
            ],
            outcomes=[
                ConstructItem(id=c['id'], role=c['role'], direction=c.get('direction'))
                for c in constructs_data.get('outcomes', [])
            ],
            mediators=[
                ConstructItem(id=c['id'], role=c['role'], direction=c.get('direction'))
                for c in constructs_data.get('mediators', [])
            ],
            moderators=[
                ModeratorItem(id=m['id'], value=m.get('value'))
                for m in constructs_data.get('moderators', [])
            ]
        )
        
        # Parse study
        study_data = data.get('study', {})
        sample_data = study_data.get('sample', {})
        sample = Sample(
            n=sample_data.get('n'),
            population=sample_data.get('population'),
            age_mean=sample_data.get('age_mean'),
            country=sample_data.get('country')
        )
        
        study = Study(
            design=study_data.get('design', 'unknown'),
            sample=sample,
            task=[
                TaskItem(id=t['id'], name=t['name'])
                for t in study_data.get('task', [])
            ],
            setting=[
                SettingItem(id=s['id'], notes=s.get('notes', ''))
                for s in study_data.get('setting', [])
            ]
        )
        
        # Parse statistics
        stats_data = data.get('statistics', {})
        effect_size_data = stats_data.get('effect_size', {})
        statistics = Statistics(
            effect_size=EffectSize(
                type=effect_size_data.get('type'),
                value=effect_size_data.get('value')
            ),
            p_value=stats_data.get('p_value'),
            ci95=stats_data.get('ci95')
        )
        
        # Parse evidence
        evidence = [
            EvidenceItem(
                kind=e['kind'],
                source=e.get('source'),
                start=e.get('start'),
                end=e.get('end'),
                table_id=e.get('table_id'),
                row=e.get('row'),
                col=e.get('col'),
                figure_id=e.get('figure_id'),
                note=e.get('note')
            )
            for e in data.get('evidence', [])
        ]
        
        return ParsedClaim(
            schema=data.get('schema', 'ae.claim.v1'),
            claim_id=data['claim_id'],
            paper_id=data['paper_id'],
            claim_type=data.get('claim_type', 'unknown'),
            statement=data.get('statement', ''),
            constructs=constructs,
            study=study,
            statistics=statistics,
            evidence=evidence,
            constraints=data.get('constraints', []),
            ae_confidence=data.get('ae_confidence', 0.0)
        )
    
    def iter_rules(self) -> Generator[ParsedRule, None, None]:
        """Iterate over rules from rules.jsonl."""
        result = self.get_result()
        rules_path = self.bundle_path / result.artifacts.rules_jsonl
        
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
                except Exception as e:
                    print(f"Warning: Error parsing rule at line {line_num}: {e}")
    
    def _parse_rule(self, data: Dict) -> ParsedRule:
        """Parse a single rule dictionary."""
        
        # Parse strength
        strength_data = data.get('strength', {})
        strength = Strength(
            kind=strength_data.get('kind', 'unknown'),
            type=strength_data.get('type'),
            value=strength_data.get('value')
        )
        
        # Parse applicability
        applicability_data = data.get('applicability', {})
        applicability = Applicability(
            population=[
                PopulationItem(id=p['id'])
                for p in applicability_data.get('population', [])
            ],
            setting=[
                SettingIdItem(id=s['id'])
                for s in applicability_data.get('setting', [])
            ],
            boundary_conditions=applicability_data.get('boundary_conditions', [])
        )
        
        # Parse bn_mapping
        bn_data = data.get('bn_mapping', {})
        bn_mapping = BNMapping(
            node_suggestions=bn_data.get('node_suggestions', []),
            discretization_hint=bn_data.get('discretization_hint', '')
        )
        
        return ParsedRule(
            schema=data.get('schema', 'ae.rule.v1'),
            rule_id=data['rule_id'],
            paper_id=data['paper_id'],
            rule_type=data.get('rule_type', 'edge'),
            lhs=[VarState(var=v['var'], state=v['state']) for v in data.get('lhs', [])],
            rhs=[VarState(var=v['var'], state=v['state']) for v in data.get('rhs', [])],
            polarity=data.get('polarity', 'unknown'),
            strength=strength,
            applicability=applicability,
            evidence_links=[
                EvidenceLink(claim_id=e['claim_id'])
                for e in data.get('evidence_links', [])
            ],
            bn_mapping=bn_mapping,
            ae_confidence=data.get('ae_confidence', 0.0)
        )
    
    def get_all_claims(self) -> List[ParsedClaim]:
        """Get all claims as a list."""
        return list(self.iter_claims())
    
    def get_all_rules(self) -> List[ParsedRule]:
        """Get all rules as a list."""
        return list(self.iter_rules())
    
    def get_provenance(self) -> Optional[Dict]:
        """Get provenance information."""
        result = self.get_result()
        provenance_path = self.bundle_path / result.artifacts.provenance_json
        
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
    
    def validate_bundle(self) -> Dict[str, Any]:
        """
        Validate the output bundle structure and contents.
        
        Returns dict with 'valid' bool and 'errors' list.
        """
        errors = []
        
        # Check required files
        result = self.get_result()
        
        required_files = [
            result.artifacts.claims_jsonl,
            result.artifacts.rules_jsonl,
            result.artifacts.provenance_json,
            result.artifacts.audit_log_jsonl
        ]
        
        for filename in required_files:
            filepath = self.bundle_path / filename
            if not filepath.exists():
                errors.append(f"Missing required file: {filename}")
        
        # Validate claims count matches
        claims = self.get_all_claims()
        if len(claims) != result.summary.n_claims:
            errors.append(
                f"Claim count mismatch: summary says {result.summary.n_claims}, "
                f"found {len(claims)}"
            )
        
        # Validate rules count matches
        rules = self.get_all_rules()
        if len(rules) != result.summary.n_rules:
            errors.append(
                f"Rule count mismatch: summary says {result.summary.n_rules}, "
                f"found {len(rules)}"
            )
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'bundle_path': str(self.bundle_path)
        }


# ============================================================================
# STATUS MAPPING
# ============================================================================

def map_eater_status_to_finder(eater_status: str, has_blocking_issues: bool = False) -> str:
    """
    Map Article Eater status to Article Finder corpus status.
    
    Per contract README:
    - SUCCESS → processed_success
    - PARTIAL_SUCCESS → processed_partial (or needs_human_review if blocking)
    - FAIL → processed_fail
    """
    if eater_status == 'SUCCESS':
        return 'processed_success'
    elif eater_status == 'PARTIAL_SUCCESS':
        return 'needs_human_review' if has_blocking_issues else 'processed_partial'
    elif eater_status == 'FAIL':
        return 'processed_fail'
    else:
        return 'needs_human_review'


# ============================================================================
# DATABASE IMPORTER
# ============================================================================

class OutputImporter:
    """
    Imports Article Eater outputs into the Article Finder database.
    """
    
    def __init__(self, database):
        self.db = database
    
    def import_bundle(self, bundle_path: Path) -> Dict[str, Any]:
        """
        Import an Article Eater output bundle into the database.
        
        Returns import summary.
        """
        parser = OutputParser(bundle_path)
        result = parser.parse_result()
        
        # Determine finder status
        has_blocking = len(result.quality.blocking_issues) > 0
        finder_status = map_eater_status_to_finder(result.status, has_blocking)
        
        # Update paper status and AE metadata
        paper = self.db.get_paper(result.paper_id)
        if paper:
            paper.update({
                'ae_output_path': str(bundle_path),
                'ae_run_id': result.run_id,
                'ae_profile': result.profile,
                'ae_status': result.status,
                'ae_n_claims': result.summary.n_claims,
                'ae_n_rules': result.summary.n_rules,
                'ae_confidence': result.quality.confidence,
                'ae_warnings': result.quality.warnings + result.quality.blocking_issues,
                'status': finder_status
            })
            self.db.add_paper(paper)
        
        # Import claims
        claims_imported = 0
        for claim in parser.iter_claims():
            self._import_claim(claim, result.run_id)
            claims_imported += 1
        
        # Import rules
        rules_imported = 0
        for rule in parser.iter_rules():
            self._import_rule(rule, result.run_id)
            rules_imported += 1
        
        return {
            'paper_id': result.paper_id,
            'status': result.status,
            'finder_status': finder_status,
            'claims_imported': claims_imported,
            'rules_imported': rules_imported,
            'confidence': result.quality.confidence,
            'blocking_issues': result.quality.blocking_issues,
            'warnings': result.quality.warnings,
            'needs_review': parser.has_review_items()
        }
    
    def _import_claim(self, claim: ParsedClaim, run_id: str) -> None:
        """Import a single claim."""
        # Convert to database format
        claim_dict = {
            'claim_id': claim.claim_id,
            'paper_id': claim.paper_id,
            'claim_type': claim.claim_type,
            'statement': claim.statement,
            'environment_factors': [
                {'id': c.id, 'role': c.role, 'direction': c.direction}
                for c in claim.constructs.environment_factors
            ],
            'outcomes': [
                {'id': c.id, 'role': c.role, 'direction': c.direction}
                for c in claim.constructs.outcomes
            ],
            'mediators': [
                {'id': c.id, 'role': c.role, 'direction': c.direction}
                for c in claim.constructs.mediators
            ],
            'moderators': [
                {'id': m.id, 'value': m.value}
                for m in claim.constructs.moderators
            ],
            'design': claim.study.design,
            'sample_n': claim.study.sample.n,
            'population': claim.study.sample.population,
            'setting': claim.study.setting[0].id if claim.study.setting else None,
            'effect_size_type': claim.statistics.effect_size.type,
            'effect_size_value': claim.statistics.effect_size.value,
            'p_value': claim.statistics.p_value,
            'ci95_low': claim.statistics.ci95[0] if claim.statistics.ci95 else None,
            'ci95_high': claim.statistics.ci95[1] if claim.statistics.ci95 else None,
            'evidence_spans': [
                {'kind': e.kind, 'source': e.source, 'start': e.start, 'end': e.end}
                for e in claim.evidence
            ],
            'ae_confidence': claim.ae_confidence,
            'ae_run_id': run_id
        }
        
        self.db.add_claim(claim_dict)
    
    def _import_rule(self, rule: ParsedRule, run_id: str) -> None:
        """Import a single rule."""
        rule_dict = {
            'rule_id': rule.rule_id,
            'paper_id': rule.paper_id,
            'rule_type': rule.rule_type,
            'lhs': [{'var': v.var, 'state': v.state} for v in rule.lhs],
            'rhs': [{'var': v.var, 'state': v.state} for v in rule.rhs],
            'polarity': rule.polarity,
            'strength_kind': rule.strength.kind,
            'strength_type': rule.strength.type,
            'strength_value': rule.strength.value,
            'population': [{'id': p.id} for p in rule.applicability.population],
            'setting': [{'id': s.id} for s in rule.applicability.setting],
            'boundary_conditions': rule.applicability.boundary_conditions,
            'evidence_links': [e.claim_id for e in rule.evidence_links],
            'ae_confidence': rule.ae_confidence,
            'ae_run_id': run_id
        }
        
        self.db.add_rule(rule_dict)
