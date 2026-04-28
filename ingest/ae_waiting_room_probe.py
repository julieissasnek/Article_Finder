"""
Article Finder -> Article Eater waiting-room duplicate probe.

This module delegates duplicate checking to Article Eater's canonical
collection-pipeline probe so AF and AE use the same duplicate language.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


AF_REPO_ROOT = Path(__file__).resolve().parents[1]
REPOS_ROOT = AF_REPO_ROOT.parent
DEFAULT_AE_REPO_ROOT = REPOS_ROOT / "Article_Eater_PostQuinean_v1_recovery"
DEFAULT_AE_PROBE_SCRIPT = DEFAULT_AE_REPO_ROOT / "scripts" / "course_scaffolding.py"


def _normalize_authors(authors: Any) -> Optional[str]:
    if not authors:
        return None
    if isinstance(authors, str):
        return authors.strip() or None
    if isinstance(authors, list):
        parts = [str(a).strip() for a in authors if str(a).strip()]
        return ", ".join(parts) if parts else None
    return str(authors).strip() or None


def probe_pdf_against_article_eater(
    pdf_path: Path,
    doi: str | None = None,
    title: str | None = None,
    authors: Any = None,
    max_matches: int = 5,
    ae_repo_root: Path | None = None,
    python_executable: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any] | None:
    """
    Ask Article Eater whether this PDF already exists in its waiting room/corpus.

    Returns the parsed JSON probe result on success, or None when the AE probe
    is unavailable or fails.
    """
    repo_root = Path(ae_repo_root) if ae_repo_root else DEFAULT_AE_REPO_ROOT
    script_path = repo_root / "scripts" / "course_scaffolding.py"
    if not script_path.exists():
        return None

    cmd = [
        python_executable or sys.executable,
        str(script_path),
        "probe-collection-pdf",
        "--pdf-path",
        str(Path(pdf_path).resolve()),
        "--max-matches",
        str(max_matches),
    ]
    if doi:
        cmd.extend(["--doi", doi])
    if title:
        cmd.extend(["--title", title])
    normalized_authors = _normalize_authors(authors)
    if normalized_authors:
        cmd.extend(["--authors", normalized_authors])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        payload.setdefault("probe_origin", "article_eater")
    return payload if isinstance(payload, dict) else None
