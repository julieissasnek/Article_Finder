#!/usr/bin/env python3
"""Apply pending AF schema-governance migrations to the live database."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.schema_registry import apply_pending_schema_migrations


DB_PATH = REPO_ROOT / "data" / "article_finder.db"


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    try:
        applied = apply_pending_schema_migrations(con)
        con.commit()
        payload = {
            "status": "ok",
            "db_path": str(DB_PATH),
            "applied_versions": applied,
        }
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
