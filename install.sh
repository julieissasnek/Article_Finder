#!/bin/bash
# Version: 3.2.2
#
# Article Finder v3.2.2 Installation Script
# 
# Usage:
#   ./install.sh [target_directory]
#
# Default target: ~/REPOS/article_finder_v3.2
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Article Finder v3.2.2 Installer${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Determine target directory
TARGET_DIR="${1:-$HOME/REPOS/article_finder_v3.2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "Target directory: ${YELLOW}${TARGET_DIR}${NC}"
echo ""

# Check if target exists
if [ -d "$TARGET_DIR" ]; then
    echo -e "${YELLOW}Warning: Target directory already exists!${NC}"
    read -p "Overwrite? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
    rm -rf "$TARGET_DIR"
fi

# Create target directory
mkdir -p "$TARGET_DIR"

# Copy files
echo "Copying files..."
cp -r "$SCRIPT_DIR"/* "$TARGET_DIR/"

# Remove install script from target (not needed there)
rm -f "$TARGET_DIR/install.sh"

# Navigate to target
cd "$TARGET_DIR"

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q

# Install dependencies
echo "Installing dependencies..."
pip install -e . -q
pip install openpyxl pandas streamlit sentence-transformers pyyaml jsonschema numpy -q

# Create local config
if [ ! -f "config/settings.local.yaml" ]; then
    echo "Creating local config..."
    cp config/settings.yaml config/settings.local.yaml
    echo -e "${YELLOW}⚠️  Please edit config/settings.local.yaml with your email for API access${NC}"
fi

# Create data directories
mkdir -p data/pdfs data/cache data/job_bundles data/ae_outputs

# Verify installation
echo ""
echo "Verifying installation..."
python -c "
import sys
sys.path.insert(0, '.')
from article_finder_v3 import __version__
print(f'  Version: {__version__}')
"

# Run quick test
echo "Running quick tests..."
python -m pytest tests/test_import.py -q --tb=no 2>/dev/null || echo "  (some tests may need additional setup)"

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "To get started:"
echo ""
echo "  1. Activate the virtual environment:"
echo -e "     ${YELLOW}cd $TARGET_DIR${NC}"
echo -e "     ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "  2. Edit your config:"
echo -e "     ${YELLOW}nano config/settings.local.yaml${NC}"
echo "     (Set your email for API access)"
echo ""
echo "  3. Import your data:"
echo -e "     ${YELLOW}python cli/main.py import /path/to/references.xlsx${NC}"
echo ""
echo "  4. Or launch the UI:"
echo -e "     ${YELLOW}python cli/main.py ui${NC}"
echo ""
echo "See docs/USER_GUIDE.md for complete documentation."
echo ""
