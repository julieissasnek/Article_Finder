#!/usr/bin/env bash
set -euo pipefail

on_error() {
  local exit_code=$?
  local line_no=${1:-unknown}
  local cmd=${2:-unknown}
  echo ""
  echo "========================================"
  echo "INSTALL FAILED"
  echo "========================================"
  echo "Exit code: ${exit_code}"
  echo "Line: ${line_no}"
  echo "Command: ${cmd}"
  echo ""
  echo "Debug hints:"
  echo "- Confirm Python 3.10+ is installed: python3 --version"
  echo "- Confirm pip is available: python3 -m pip --version"
  echo "- If installs fail, check network access and proxies"
  echo "- Re-run with: bash -x ./install_turnkey.sh"
  echo ""
  exit ${exit_code}
}
trap 'on_error $LINENO "$BASH_COMMAND"' ERR

log() {
  printf "[%s] %s
" "$(date '+%H:%M:%S')" "$*"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

log "Article Finder Turnkey Installer"
log "Repo: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ and retry."
  exit 2
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
log "Python: $PY_VER"

log "Creating/refreshing venv..."
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate

log "Upgrading pip/setuptools/wheel..."
python -m pip install --upgrade pip setuptools wheel

if [[ -f "requirements.txt" ]]; then
  log "Installing requirements.txt..."
  python -m pip install -r requirements.txt
fi

if [[ -f "setup.py" ]]; then
  log "Installing package (editable)..."
  python -m pip install -e .
fi

log "Verifying import..."
python -c 'import article_finder_v3; print(f"Article Finder version: {getattr(article_finder_v3, "__version__", "unknown")}")'

log "Install complete."

cat <<'EOF'

Next steps (AI/local LLM):
- If you already have a Gemini key, run:
    export GEMINI_API_KEY=YOUR_KEY
- Or OpenAI:
    export OPENAI_API_KEY=YOUR_KEY
- For local LLM, install Ollama and run:
    ollama pull mistral
    ollama serve

Batch runs in Article Finder default to local Ollama when available.

More help: see INSTALL_AI.md

Launch UI:
  python cli/main.py ui

EOF
