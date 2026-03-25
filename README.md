<!-- Version: 3.2.3 -->
# Article Finder v3.2.3
Ports: Source-of-truth in `contracts/ports.json`.

A comprehensive tool for managing and analyzing neuroarchitecture research literature.

## What's New in v3.2.3

### 🔌 Zotero Integration (NEW)
Two-way bridge with local Zotero installation for PDF acquisition:

- **Import PDFs from Zotero**: Automatically match and copy PDFs from your Zotero library
- **Export papers to Zotero**: Export papers needing PDFs in RIS/CSV format
- **UCSD Library Support**: Use Zotero's "Find Available PDF" with library proxy authentication

This enables semi-automated acquisition of paywalled papers through your university library.

```bash
# Check what's in Zotero and Article Finder
python cli/main.py zotero stats

# Export papers needing PDFs → import to Zotero
python cli/main.py zotero export --format ris

# After Zotero downloads PDFs, import them back
python cli/main.py zotero import
```

See `docs/ZOTERO_UCSD_SETUP.md` for full setup guide.

- **Bounded Expansion**: Taxonomy-filtered citation following - stays in domain
- **Deduplication**: Robust duplicate detection (DOI, fuzzy title, author overlap)
- **Discovery Orchestrator**: Full pipeline automation (import → classify → expand → acquire → bundle)
- **Progress Dashboard**: Streamlit UI for monitoring discovery runs

### 🔴 Critical Fix: Smart Importer
The v3.1 importer was broken - it couldn't import your actual data (0/638 papers from your spreadsheet). v3.2 fixes this completely:

- **Smart Citation Parser**: Handles MDPI, APA, MLA, Chicago, Vancouver, and informal citation formats
- **Fuzzy Column Detection**: Recognizes 50+ column name variants ("Reference Information", "Citation", "Ref", etc.)
- **PDF Cataloger**: Creates paper records from PDF filenames like `Wastiels,_L.,_&_He.pdf`
- **CrossRef Integration**: Automatically searches for DOIs when not present in data

### Test Results
Before (v3.1): 0/638 papers imported from your spreadsheet
After (v3.2): **100/100 papers imported** with titles, authors, and years correctly parsed

## Quick Install

```bash
# Extract the tarball
tar -xzf article_finder_v3.2.1.tar.gz
cd article_finder_v3.2

# Run the installer
chmod +x install.sh
./install.sh ~/REPOS/article_finder_v3.2

# Or install manually:
cd ~/REPOS/article_finder_v3.2
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install openpyxl pandas streamlit sentence-transformers pyyaml jsonschema
```

## Quick Start

```bash
# Activate environment
cd ~/REPOS/article_finder_v3.2
source venv/bin/activate

# Import your spreadsheet
python cli/main.py import /path/to/Split_References_Spreadsheet.xlsx --source MDPI

# Match your existing PDFs to papers
python cli/main.py match-pdfs /path/to/pdfs/

# Run bounded expansion (taxonomy-filtered)
python cli/main.py expand --threshold 0.35 --limit 50

# Or run the full discovery pipeline
python cli/main.py discover --email your@email.com --iterations 3

# Launch UI
python cli/main.py ui
```

## Configuration

Edit `config/settings.local.yaml`:

```yaml
apis:
  openalex:
    email: "your-email@ucsd.edu"  # Required for API access
```

## Project Structure

```
article_finder_v3.2/
├── VERSION              # Single source of version truth (3.2.3)
├── config/
│   ├── settings.yaml    # Default configuration
│   └── taxonomy.yaml    # 9-facet neuroarchitecture taxonomy
├── ingest/
│   ├── smart_importer.py    # Fuzzy column detection, handles messy data
│   ├── citation_parser.py   # Parses MDPI/APA/MLA/Chicago citations
│   ├── pdf_cataloger.py     # Creates records from PDF filenames
│   ├── pdf_downloader.py    # Unpaywall-based PDF acquisition
│   ├── doi_resolver.py      # CrossRef + OpenAlex integration
│   └── zotero_bridge.py     # NEW: Two-way Zotero integration
├── search/
│   ├── expansion_scorer.py    # Taxonomy-based relevance scoring
│   ├── bounded_expander.py    # Citation expansion with filtering
│   ├── deduplicator.py        # Robust duplicate detection
│   ├── discovery_orchestrator.py  # Full pipeline automation
│   └── citation_network.py    # Citation graph management
├── triage/
│   ├── taxonomy_loader.py   # Loads 9-facet taxonomy
│   ├── scorer.py            # Hierarchical semantic scoring
│   └── embeddings.py        # Sentence-transformer embeddings
├── ui/pages/
│   ├── 1_dashboard.py
│   ├── 2_search.py
│   ├── 3_triage.py
│   ├── 4_paper.py
│   ├── 5_citations.py       # Citation network visualization
│   ├── 6_import.py          # Smart import with preview
│   └── 7_discovery.py       # Discovery dashboard
├── cli/main.py              # Full CLI with all commands
├── tests/test_import.py     # 29 passing tests
├── docs/
│   ├── USER_GUIDE.md        # Complete documentation
│   ├── ZOTERO_UCSD_SETUP.md # NEW: Zotero + UCSD library setup
│   └── EXPERT_PANEL_REVIEW.md
└── docs/EXPERT_PANEL_AUTOPILOT_PDF.md  # NEW: PDF acquisition analysis
```

## CLI Commands

```bash
# Import
python cli/main.py import FILE [--source NAME] [--preview] [--limit N]
python cli/main.py import-pdfs DIRECTORY [--source NAME]

# Match PDFs to papers
python cli/main.py match-pdfs DIRECTORY [--dry-run]

# Enrich metadata
python cli/main.py enrich [--limit N]

# Classification
python cli/main.py classify --load-taxonomy --build-centroids --score-all

# Expansion (taxonomy-bounded)
python cli/main.py expand --threshold 0.35 --depth 2 --limit 50

# Full discovery pipeline
python cli/main.py discover --email EMAIL --iterations 3

# Zotero Integration (NEW in v3.2.3)
python cli/main.py zotero stats                    # Show Zotero & AF PDF status
python cli/main.py zotero export --format ris      # Export papers needing PDFs
python cli/main.py zotero import                   # Import PDFs from Zotero
python cli/main.py zotero import --dry-run         # Preview import

# Citations
python cli/main.py citations --fetch [--limit N]

# PDFs
python cli/main.py download [--limit N]

# Article Eater
python cli/main.py build-jobs [--status send_to_eater]

# Stats & UI
python cli/main.py stats
python cli/main.py ui
```

## Discovery Pipeline

The `discover` command runs the complete pipeline:

1. **Import** (optional) - Load papers from file
2. **Classify** - Score papers against 9-facet taxonomy
3. **Expand** - Follow citations, filter by relevance
4. **Process Queue** - Add discovered papers to corpus
5. **Acquire PDFs** - Download via Unpaywall
6. **Build Jobs** - Create Article Eater bundles

```bash
python cli/main.py discover \
    --email your@email.com \
    --threshold 0.35 \
    --depth 2 \
    --iterations 3 \
    --expansion-limit 50 \
    --pdf-limit 100
```

## Bounded Expansion

The key innovation: **taxonomy-filtered expansion** prevents corpus pollution.

Instead of adding ALL citations (which would drift into pure neuroscience/psychology), 
each discovered paper is scored against your neuroarchitecture taxonomy. Only papers 
above the relevance threshold (default 0.35) enter the corpus.

```
Seed Papers → Fetch Citations → Score vs Taxonomy → Filter → Queue → Process
                    ↓                    ↓
             500 candidates         45 relevant (9%)
```

## Version Governance

Version is stored in a single `VERSION` file at repo root. The `__init__.py` reads from this file, so there's no version mismatch between package and tarball.

## Comparison: v3.1 vs v3.2

| Feature | v3.1 | v3.2 |
|---------|------|------|
| Import your spreadsheet | ❌ 0/638 | ✅ 100% |
| Citation string parsing | ❌ None | ✅ MDPI, APA, MLA, Chicago |
| Fuzzy column detection | ❌ None | ✅ 50+ variants |
| PDF cataloging | ❌ None | ✅ From filenames |
| Bounded expansion | ❌ None | ✅ Taxonomy-filtered |
| Deduplication | ❌ None | ✅ DOI + fuzzy title |
| Discovery orchestrator | ❌ None | ✅ Full pipeline |
| Progress dashboard | ❌ None | ✅ Streamlit UI |
| Test coverage | ❌ Minimal | ✅ 29 tests |
| Documentation | ❌ None | ✅ User guide |

## License

Proprietary. Developed for neuroarchitecture research at UCSD.

## v3.2.2 Changes (Knowledge Synthesis)

### New Knowledge Module (`knowledge/`)
- **Semantic Search** (`semantic_search.py`): Vector similarity search over papers
- **Claim Embeddings** (`claim_embeddings.py`): Search and deduplicate extracted claims
- **Knowledge Graph** (`claim_graph.py`): Graph connecting papers → claims → constructs
- **Query Engine** (`query_engine.py`): Natural language queries over the graph
- **Synthesis** (`synthesis.py`): Meta-analytic aggregation of findings
- **Parallel Processing** (`parallel.py`): Batch operations with checkpointing

### New CLI Commands
```bash
# Semantic search
python cli/main.py search "daylight cognitive performance"
python cli/main.py similar <paper_id>

# Claim operations
python cli/main.py claims search "reduces stress"
python cli/main.py claims duplicates --threshold 0.9
python cli/main.py claims stats

# Knowledge graph
python cli/main.py graph build
python cli/main.py graph stats
python cli/main.py graph what-affects mood
python cli/main.py graph affects-what daylight

# Natural language queries
python cli/main.py query "What affects cognitive performance?"
python cli/main.py query "What does daylight affect?"

# Meta-analysis
python cli/main.py synthesize daylight
python cli/main.py synthesize --iv daylight --dv mood
```

### Architecture: Corpus Manager → Knowledge Synthesis Engine
```
Papers → Claims → Knowledge Graph → Query Interface → Synthesis
```

# Health Check

Run:

```bash
python cli/main.py doctor
```
