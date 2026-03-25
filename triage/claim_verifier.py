#!/usr/bin/env python3
"""
Claim and Rule Verification Module

Verifies that extracted claims and rules are consistent with paper metadata.
Uses heuristics and optionally AI to check for data quality issues.

TODO: Integrate with LLM API for deeper semantic verification
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database


@dataclass
class VerificationResult:
    """Result of verifying a paper's claims/rules."""
    paper_id: str
    status: str  # 'pass', 'warn', 'fail'
    issues: List[str]
    suggestions: List[str]
    scores: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'paper_id': self.paper_id,
            'status': self.status,
            'issues': self.issues,
            'suggestions': self.suggestions,
            'scores': self.scores
        }


class ClaimVerifier:
    """
    Verify claims and rules against paper metadata.

    Checks:
    1. Title-abstract consistency
    2. Claims match paper topic
    3. Rules have valid structure
    4. Required fields are populated
    """

    def __init__(self, database: Database):
        self.db = database

    def verify_paper(self, paper_id: str) -> VerificationResult:
        """
        Verify all claims and rules for a paper.

        Returns VerificationResult with status and issues found.
        """
        paper = self.db.get_paper(paper_id)
        if not paper:
            return VerificationResult(
                paper_id=paper_id,
                status='fail',
                issues=['Paper not found in database'],
                suggestions=[],
                scores={}
            )

        issues = []
        suggestions = []
        scores = {}

        # Check 1: Title-Abstract consistency
        title_abstract_score = self._check_title_abstract_consistency(
            paper.get('title', ''),
            paper.get('abstract', '')
        )
        scores['title_abstract_consistency'] = title_abstract_score

        if title_abstract_score < 0.3:
            issues.append(f"Title and abstract may not match (score: {title_abstract_score:.2f})")
            suggestions.append("Verify the abstract belongs to this paper")

        # Get claims and rules
        claims = self._get_claims(paper_id)
        rules = self._get_rules(paper_id)

        scores['n_claims'] = len(claims)
        scores['n_rules'] = len(rules)

        # Check 2: Claims match paper topic
        if claims:
            claim_relevance = self._check_claims_relevance(
                paper.get('title', ''),
                paper.get('abstract', ''),
                claims
            )
            scores['claim_relevance'] = claim_relevance

            if claim_relevance < 0.3:
                issues.append(f"Claims may not match paper topic (score: {claim_relevance:.2f})")
                suggestions.append("Review extracted claims against paper content")

        # Check 3: Rules structure
        for rule in rules:
            rule_issues = self._check_rule_structure(rule)
            issues.extend(rule_issues)

        # Check 4: Required fields
        field_issues = self._check_required_fields(paper, claims, rules)
        issues.extend(field_issues)

        # Determine overall status
        if any('fail' in issue.lower() or 'not match' in issue.lower() for issue in issues):
            status = 'fail'
        elif issues:
            status = 'warn'
        else:
            status = 'pass'

        return VerificationResult(
            paper_id=paper_id,
            status=status,
            issues=issues,
            suggestions=suggestions,
            scores=scores
        )

    def _check_title_abstract_consistency(self, title: str, abstract: str) -> float:
        """
        Check if title and abstract are about the same topic.

        Returns score 0-1 where 1 = highly consistent.
        Uses keyword overlap as a simple heuristic.
        """
        if not title or not abstract:
            return 0.0

        # Extract significant words (>3 chars, not common words)
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
                      'can', 'has', 'her', 'was', 'one', 'our', 'out', 'with',
                      'this', 'that', 'from', 'they', 'been', 'have', 'were',
                      'said', 'each', 'which', 'their', 'will', 'other', 'about',
                      'into', 'than', 'them', 'these', 'some', 'would', 'make',
                      'like', 'just', 'over', 'such', 'also', 'more', 'very'}

        def extract_keywords(text: str) -> set:
            words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
            return {w for w in words if w not in stop_words}

        title_words = extract_keywords(title)
        abstract_words = extract_keywords(abstract)

        if not title_words:
            return 0.5  # Can't assess

        # What fraction of title words appear in abstract?
        overlap = len(title_words & abstract_words)
        score = overlap / len(title_words)

        return min(1.0, score)

    def _check_claims_relevance(
        self,
        title: str,
        abstract: str,
        claims: List[Dict]
    ) -> float:
        """
        Check if claims are relevant to paper topic.

        Returns score 0-1 where 1 = highly relevant.
        """
        if not claims:
            return 1.0  # No claims to check

        paper_text = f"{title} {abstract}".lower()

        # Check how many claims share keywords with paper
        relevant_count = 0
        for claim in claims:
            statement = claim.get('statement', '').lower()
            # Simple check: do they share significant words?
            paper_words = set(re.findall(r'\b[a-zA-Z]{5,}\b', paper_text))
            claim_words = set(re.findall(r'\b[a-zA-Z]{5,}\b', statement))

            if paper_words & claim_words:
                relevant_count += 1

        return relevant_count / len(claims) if claims else 1.0

    def _check_rule_structure(self, rule: Dict) -> List[str]:
        """Check if a rule has valid structure."""
        issues = []

        lhs = rule.get('lhs', '')
        rhs = rule.get('rhs', '')
        polarity = rule.get('polarity', '')

        if not lhs:
            issues.append(f"Rule {rule.get('rule_id')}: Missing left-hand side (cause)")

        if not rhs:
            issues.append(f"Rule {rule.get('rule_id')}: Missing right-hand side (effect)")

        if polarity not in ('positive', 'negative', 'neutral', ''):
            issues.append(f"Rule {rule.get('rule_id')}: Invalid polarity '{polarity}'")

        return issues

    def _check_required_fields(
        self,
        paper: Dict,
        claims: List[Dict],
        rules: List[Dict]
    ) -> List[str]:
        """Check that required fields are populated."""
        issues = []

        if not paper.get('title'):
            issues.append("Paper missing title")

        if not paper.get('abstract'):
            issues.append("Paper missing abstract - claims may be unreliable")

        # Claims should have statements
        for claim in claims:
            if not claim.get('statement'):
                issues.append(f"Claim {claim.get('claim_id')}: Missing statement")

        return issues

    def _get_claims(self, paper_id: str) -> List[Dict]:
        """Get all claims for a paper."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM claims WHERE paper_id = ?",
                (paper_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def _get_rules(self, paper_id: str) -> List[Dict]:
        """Get all rules for a paper."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rules WHERE paper_id = ?",
                (paper_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def verify_all_papers_with_claims(self) -> Dict[str, Any]:
        """Verify all papers that have claims/rules extracted."""
        with self.db.connection() as conn:
            paper_ids = conn.execute(
                "SELECT DISTINCT paper_id FROM claims UNION SELECT DISTINCT paper_id FROM rules"
            ).fetchall()
            paper_ids = [row[0] for row in paper_ids]

        results = []
        for paper_id in paper_ids:
            result = self.verify_paper(paper_id)
            results.append(result.to_dict())

        # Summary
        pass_count = sum(1 for r in results if r['status'] == 'pass')
        warn_count = sum(1 for r in results if r['status'] == 'warn')
        fail_count = sum(1 for r in results if r['status'] == 'fail')

        return {
            'total': len(results),
            'pass': pass_count,
            'warn': warn_count,
            'fail': fail_count,
            'results': results
        }


# =============================================================================
# TODO: AI-powered verification using LLM
# =============================================================================
#
# class AIClaimVerifier(ClaimVerifier):
#     """
#     Enhanced verifier that uses an LLM for semantic checking.
#
#     TODO: Implement this class with:
#     1. API client for Claude/GPT
#     2. Prompt templates for verification
#     3. Batch processing for efficiency
#     4. Caching to avoid redundant API calls
#
#     Verification prompts:
#     - "Does this abstract match the paper title '{title}'? Abstract: {abstract}"
#     - "Are these claims consistent with the paper topic? Claims: {claims}"
#     - "Is this rule logically valid? LHS: {lhs}, RHS: {rhs}, Polarity: {polarity}"
#     """
#     pass


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Verify claims and rules')
    parser.add_argument('--db', type=Path, default='data/article_finder.db')
    parser.add_argument('--paper', type=str, help='Verify specific paper')
    parser.add_argument('--all', action='store_true', help='Verify all papers with claims')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show details')

    args = parser.parse_args()

    db = Database(args.db)
    verifier = ClaimVerifier(db)

    if args.paper:
        result = verifier.verify_paper(args.paper)
        print(f"\nVerification for {args.paper}:")
        print(f"  Status: {result.status.upper()}")
        print(f"  Scores: {result.scores}")
        if result.issues:
            print(f"\n  Issues:")
            for issue in result.issues:
                print(f"    - {issue}")
        if result.suggestions:
            print(f"\n  Suggestions:")
            for sug in result.suggestions:
                print(f"    - {sug}")

    elif args.all:
        summary = verifier.verify_all_papers_with_claims()
        print(f"\nVerification Summary:")
        print(f"  Total papers: {summary['total']}")
        print(f"  Pass: {summary['pass']}")
        print(f"  Warn: {summary['warn']}")
        print(f"  Fail: {summary['fail']}")

        if args.verbose:
            print(f"\nDetails:")
            for r in summary['results']:
                status_icon = '✓' if r['status'] == 'pass' else ('⚠' if r['status'] == 'warn' else '✗')
                print(f"  {status_icon} {r['paper_id']}: {r['status']}")
                for issue in r['issues']:
                    print(f"      - {issue}")

    else:
        parser.print_help()
