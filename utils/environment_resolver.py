"""
Environment Resolver - Resolves environment tags using Tagging_Contractor vocabulary.

For resolving IVs (independent variables) - environmental factors that can be designed.

Usage:
    from utils.environment_resolver import resolve_environment
    
    result = resolve_environment("warm lighting")
    if result:
        tag_id = result['tag_id']  # "env.ae.warm_lighting"
"""

import json
from pathlib import Path
from typing import Optional, Dict, Tuple
from difflib import SequenceMatcher

# Lookup table path
_LOOKUP_PATH = Path(__file__).parent.parent / "config" / "environment_lookup.json"
_lookup_data = None

def _load_lookup():
    global _lookup_data
    if _lookup_data is None:
        if _LOOKUP_PATH.exists():
            with open(_LOOKUP_PATH) as f:
                _lookup_data = json.load(f)
        else:
            _lookup_data = {"lookup": {}, "tags": {}}
    return _lookup_data

def resolve_environment(raw_term: str, fuzzy_threshold: float = 0.85) -> Optional[Dict]:
    """
    Resolve a raw environment term to canonical tag.
    
    Returns dict with tag_id, canonical_name, category, confidence
    or None if not found.
    """
    data = _load_lookup()
    raw_lower = raw_term.lower().strip()
    
    # Exact lookup
    if raw_lower in data['lookup']:
        tag_id = data['lookup'][raw_lower]
        tag_info = data['tags'].get(tag_id, {})
        return {
            'tag_id': tag_id,
            'canonical_name': tag_info.get('canonical_name', tag_id),
            'category': tag_info.get('category', ''),
            'domain': tag_info.get('domain', ''),
            'confidence': 1.0,
            'match_type': 'exact'
        }
    
    # Fuzzy match
    best_match = None
    best_score = 0.0
    
    for lookup_text, tag_id in data['lookup'].items():
        score = SequenceMatcher(None, raw_lower, lookup_text).ratio()
        if score > best_score and score >= fuzzy_threshold:
            best_score = score
            best_match = tag_id
    
    if best_match:
        tag_info = data['tags'].get(best_match, {})
        return {
            'tag_id': best_match,
            'canonical_name': tag_info.get('canonical_name', best_match),
            'category': tag_info.get('category', ''),
            'domain': tag_info.get('domain', ''),
            'confidence': best_score,
            'match_type': 'fuzzy'
        }
    
    return None

def resolve_or_queue_environment(
    raw_term: str,
    queue_path: Optional[Path] = None
) -> Tuple[Optional[Dict], bool]:
    """
    Resolve environment term, or queue for review if not found.
    
    Returns (resolved_dict, was_queued)
    """
    resolved = resolve_environment(raw_term)
    if resolved:
        return (resolved, False)
    
    # Queue unresolved
    if queue_path is None:
        queue_path = Path(__file__).parent.parent / "data" / "unresolved_environment.jsonl"
    
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(queue_path, 'a') as f:
        f.write(json.dumps({"raw_term": raw_term}) + "\n")
    
    return (None, True)

def get_all_environment_tags() -> Dict[str, Dict]:
    """Get all canonical environment tags."""
    data = _load_lookup()
    return data.get('tags', {})

def get_environment_categories() -> list:
    """Get list of environment categories."""
    data = _load_lookup()
    categories = set()
    for tag in data.get('tags', {}).values():
        cat = tag.get('category', '')
        if cat:
            categories.add(cat)
    return sorted(categories)
