# Version: 3.2.2
"""
Article Finder v3.2
A comprehensive tool for managing and analyzing neuroarchitecture research literature.

Features:
- Smart import from spreadsheets, PDFs, and citation strings
- Multi-facet taxonomy classification
- Citation network analysis
- Article Eater integration for claim extraction
"""

from pathlib import Path

# Version governance: single source of truth from VERSION file
_version_path = Path(__file__).resolve().parent.parent / "VERSION"
try:
    __version__ = _version_path.read_text(encoding="ascii").strip()
except Exception:
    __version__ = "0.0.0"

__author__ = "Article Finder Team"
__email__ = "support@example.com"

# Convenience imports
try:
    from .core.database import Database
except Exception:  # fallback for non-package layout
    from core.database import Database

__all__ = [
    '__version__',
    'Database',
]
