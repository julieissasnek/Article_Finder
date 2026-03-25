"""
Article Finder - Outcome Resolver
Resolves raw outcome terms using Outcome_Contractor vocabulary.

Usage:
    from utils.outcome_resolver import resolve_outcome, resolve_or_queue_outcome
    
    resolved = resolve_outcome("positive affect")
    if resolved:
        canonical_id = resolved['canonical_id']  # "affect.mood.positive"
"""

import json
from pathlib import Path
from typing import Optional, Dict, Tuple
from difflib import SequenceMatcher

# Load lookup table
_LOOKUP_PATH = Path(__file__).parent.parent / "config" / "outcome_lookup.json"
_lookup_data = None

def _load_lookup():
    global _lookup_data
    if _lookup_data is None:
        if _LOOKUP_PATH.exists():
            with open(_LOOKUP_PATH) as f:
                _lookup_data = json.load(f)
        else:
            _lookup_data = {"lookup": {}, "terms": {}}
    return _lookup_data

def resolve_outcome(raw_term: str) -> Optional[Dict]:
    """
    Resolve a raw outcome term to canonical form.
    
    Returns dict with canonical_id, name, domain, confidence
    or None if not found.
    """
    data = _load_lookup()
    raw_lower = raw_term.lower().strip()
    
    # Exact lookup
    if raw_lower in data['lookup']:
        term_id = data['lookup'][raw_lower]
        term_info = data['terms'].get(term_id, {})
        return {
            'canonical_id': term_id,
            'name': term_info.get('name', term_id),
            'domain': term_info.get('domain', ''),
            'confidence': 1.0,
            'match_type': 'exact'
        }
    
    # Fuzzy match
    best_match = None
    best_score = 0.0
    
    for lookup_text, term_id in data['lookup'].items():
        score = SequenceMatcher(None, raw_lower, lookup_text).ratio()
        if score > best_score and score >= 0.85:
            best_score = score
            best_match = term_id
    
    if best_match:
        term_info = data['terms'].get(best_match, {})
        return {
            'canonical_id': best_match,
            'name': term_info.get('name', best_match),
            'domain': term_info.get('domain', ''),
            'confidence': best_score,
            'match_type': 'fuzzy'
        }
    
    return None

def resolve_or_queue_outcome(
    raw_term: str,
    queue_path: Optional[Path] = None
) -> Tuple[Optional[Dict], bool]:
    """
    Resolve outcome term, or queue for review if not found.
    
    Returns (resolved_dict, was_queued)
    """
    resolved = resolve_outcome(raw_term)
    if resolved:
        return (resolved, False)
    
    # Queue unresolved term
    if queue_path is None:
        queue_path = Path(__file__).parent.parent / "data" / "unresolved_outcomes.jsonl"
    
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(queue_path, 'a') as f:
        f.write(json.dumps({"raw_term": raw_term}) + "\n")
    
    return (None, True)

def get_all_outcomes() -> Dict[str, Dict]:
    """Get all canonical outcome terms."""
    data = _load_lookup()
    return data.get('terms', {})

def get_outcome_domains() -> list:
    """Get list of outcome domains."""
    return ['cog', 'affect', 'behav', 'social', 'physio', 'neural', 'health']
