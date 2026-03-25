#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORTS_JSON="$ROOT_DIR/contracts/ports.json"

PORT=8501
if [ -f "$PORTS_JSON" ]; then
  PORT=$(python3 - <<'PY'
import json
from pathlib import Path
p=Path("/Users/davidusa/REPOS/article_finder_v3.2.2/contracts/ports.json")
try:
    data=json.loads(p.read_text(encoding='utf-8'))
    print(int(data.get('ports',{}).get('ui',{}).get('host',8501)))
except Exception:
    print(8501)
PY
)
fi

echo "Open http://localhost:${PORT}"
exec streamlit run "$ROOT_DIR/ui/app.py" --server.port "$PORT"
