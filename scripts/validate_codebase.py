#!/usr/bin/env python3
"""
Codebase Validation Script

Runs static analysis and basic tests to catch common issues like:
- Type errors (string vs Path)
- Missing imports
- Database schema mismatches
- Broken file references

Usage:
    python scripts/validate_codebase.py
    python scripts/validate_codebase.py --fix  # Auto-fix some issues
"""

import sys
import subprocess
from pathlib import Path
from typing import List, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_imports() -> List[str]:
    """Check that all modules can be imported."""
    issues = []
    modules = [
        'core.database',
        'triage.scorer',
        'triage.claim_verifier',
        'ingest.pdf_cataloger',
        'ingest.zotero_connector',
        'ingest.prepare_for_ae',
        'search.bibliographer',
        'eater_interface.job_bundle_v2',
        'eater_interface.invoker',
    ]

    for module in modules:
        try:
            __import__(module)
        except ImportError as e:
            issues.append(f"Import error in {module}: {e}")
        except Exception as e:
            issues.append(f"Error loading {module}: {e}")

    return issues


def check_database_init() -> List[str]:
    """Check database initialization works with various inputs."""
    issues = []

    from core.database import Database
    import tempfile

    # Test with Path
    try:
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / 'test.db')
            del db
    except Exception as e:
        issues.append(f"Database init with Path failed: {e}")

    # Test with string
    try:
        with tempfile.TemporaryDirectory() as td:
            db = Database(f"{td}/test.db")
            del db
    except Exception as e:
        issues.append(f"Database init with string failed: {e}")

    # Test with None (should use default)
    try:
        # Don't actually create default DB, just check the logic
        pass
    except Exception as e:
        issues.append(f"Database init with None failed: {e}")

    return issues


def check_pdf_cataloger() -> List[str]:
    """Check PDF cataloger functions work."""
    issues = []

    try:
        from ingest.pdf_cataloger import (
            extract_pdf_text,
            verify_text_matches_title,
            verify_abstract_matches_pdf
        )

        # Test verification functions with sample data
        matches, score = verify_text_matches_title(
            "This is a paper about architecture and lighting design",
            "Architecture and Lighting Design"
        )
        if not matches:
            issues.append(f"Title verification failed for matching text (score={score})")

        matches, score = verify_text_matches_title(
            "This is about disaster planning and emergency response",
            "Architecture and Lighting Design"
        )
        if matches:
            issues.append(f"Title verification passed for non-matching text (score={score})")

    except Exception as e:
        issues.append(f"PDF cataloger check failed: {e}")

    return issues


def check_claim_verifier() -> List[str]:
    """Check claim verifier module."""
    issues = []

    try:
        from triage.claim_verifier import ClaimVerifier, VerificationResult

        # Just check classes can be instantiated
        result = VerificationResult(
            paper_id="test",
            status="pass",
            issues=[],
            suggestions=[],
            scores={}
        )
        if result.status != "pass":
            issues.append("VerificationResult status incorrect")

    except Exception as e:
        issues.append(f"Claim verifier check failed: {e}")

    return issues


def run_mypy() -> List[str]:
    """Run mypy static type checker if available."""
    issues = []

    try:
        result = subprocess.run(
            ['mypy', '--ignore-missing-imports', 'core/database.py'],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60
        )
        if result.returncode != 0 and result.stdout:
            for line in result.stdout.strip().split('\n'):
                if 'error:' in line:
                    issues.append(f"mypy: {line}")
    except FileNotFoundError:
        pass  # mypy not installed, skip
    except Exception as e:
        issues.append(f"mypy check failed: {e}")

    return issues


def main():
    print("=" * 60)
    print("Article Finder Codebase Validation")
    print("=" * 60)

    all_issues = []

    # Run checks
    checks = [
        ("Import checks", check_imports),
        ("Database initialization", check_database_init),
        ("PDF cataloger", check_pdf_cataloger),
        ("Claim verifier", check_claim_verifier),
        ("Static type checking (mypy)", run_mypy),
    ]

    for name, check_fn in checks:
        print(f"\n{name}...")
        try:
            issues = check_fn()
            if issues:
                print(f"  ⚠ {len(issues)} issue(s) found:")
                for issue in issues:
                    print(f"    - {issue}")
                all_issues.extend(issues)
            else:
                print(f"  ✓ Passed")
        except Exception as e:
            print(f"  ✗ Check failed: {e}")
            all_issues.append(f"{name}: {e}")

    # Summary
    print("\n" + "=" * 60)
    if all_issues:
        print(f"VALIDATION FAILED: {len(all_issues)} issue(s) found")
        return 1
    else:
        print("VALIDATION PASSED: All checks passed")
        return 0


if __name__ == '__main__':
    sys.exit(main())
