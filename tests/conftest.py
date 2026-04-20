from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_SHARED_SRC = REPO_ROOT.parent / "atlas_shared" / "src"

for path in (REPO_ROOT, ATLAS_SHARED_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
