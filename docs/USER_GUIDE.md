<!-- Version: 3.2.2 -->
# Article Finder v3.2 User Guide

A comprehensive tool for managing and analyzing neuroarchitecture research literature.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [Importing References](#importing-references)
4. [Classification System](#classification-system)
5. [Working with PDFs](#working-with-pdfs)
6. [Citation Network](#citation-network)
7. [Article Eater Integration](#article-eater-integration)
8. [Command Line Interface](#command-line-interface)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# Install
cd article_finder_v3.2
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -e .
pip install -r requirements.txt

# Configure
cp config/settings.yaml config/settings.local.yaml
# Edit settings.local.yaml with your email

# Launch UI
scripts/run_ui.sh
```

Open http://localhost:8503 in your browser (see `contracts/ports.json`).

---

## Installation

### Requirements

- Python 3.9+
- 4GB RAM minimum (8GB recommended for large corpora)
- Internet connection for DOI resolution

### Dependencies

```bash
pip install -e .
pip install openpyxl pandas streamlit plotly sentence-transformers jsonschema pyyaml
```

### Configuration

Copy and edit the config file:

```bash
cp config/settings.yaml config/settings.local.yaml
```

**Important settings:**

```yaml
apis:
  openalex:
    email: "your-email@university.edu"  # Required for API politeness
  crossref:
    email: "your-email@university.edu"

paths:
  database: "data/article_finder.db"
  pdfs: "data/pdfs"
  inbox_pdfs: "data/inbox_pdfs"
```

---

## Importing References

Article Finder v3.2 supports multiple import methods:

### From Spreadsheets (Excel/CSV)

The smart importer handles various formats:

1. **Standard format** - Columns named `DOI`, `Title`, `Authors`, `Year`
2. **Citation strings** - Single column with full references like:
   - `Smith, J. (2020). Paper Title. Journal Name, 45(3), 123-456.`
3. **Mixed formats** - Auto-detects column types

**Via UI:**
1. Go to **Import** page
2. Upload your file
3. Review the preview and column mapping
4. Adjust mappings if needed
5. Click **Import**

**Via CLI:**
```bash
python cli/main.py import data/references.xlsx --source MyCorpus
```

### From PDF Directory

If you have PDFs with author-based filenames:

```bash
python cli/main.py import-pdfs data/pdfs/ --source PDFCollection
```

The system parses filenames like:
- `Wastiels,_L.,_&_He.pdf` → Authors: Wastiels, He
- `2020_Smith_Daylight.pdf` → Year: 2020, Authors: Smith
- `10.1016_j.jenvp.2020.pdf` → DOI: 10.1016/j.jenvp.2020

### Enriching Metadata

After import, fetch missing abstracts and metadata:

**Via UI:** Import page → Enrich Papers section

**Via CLI:**
```bash
python cli/main.py enrich --limit 100
```

---

## Classification System

### The Taxonomy

Article Finder uses a **9-facet taxonomy** for classifying neuroarchitecture papers:

| Facet | Description | Examples |
|-------|-------------|----------|
| Environmental Factors | Physical attributes studied | Lighting, temperature, acoustics |
| Outcomes | Human responses measured | Attention, stress, mood |
| Subjects | Population studied | Adults, elderly, students |
| Settings | Building type | Office, healthcare, residential |
| Methodology | Research approach | Experimental, survey, fMRI |
| Modality | Environment type | Real building, VR, photos |
| Cross-Modal | Sensory interactions | Light-temperature, sound-space |
| Theory | Theoretical framework | Attention restoration, biophilia |
| Evidence Strength | Quality indicators | RCT, meta-analysis |

### Automatic Classification

Papers are scored against all taxonomy nodes using semantic similarity:

```bash
# Load taxonomy and build embeddings
python cli/main.py classify --load-taxonomy --build-centroids

# Score all papers
python cli/main.py classify --score-all --report
```

### Triage Decisions

Based on scores, papers are assigned:

- **send_to_eater** (score ≥ 0.70) - Highly relevant, process immediately
- **review** (score 0.40-0.70) - Potentially relevant, needs human review
- **reject** (score < 0.40) - Likely not relevant

---

## Working with PDFs

### Downloading PDFs

For papers with DOIs, try to fetch open access versions:

```bash
python cli/main.py download --limit 50
```

Uses Unpaywall API to find legal open access copies.

### Matching Existing PDFs

If you have PDFs already:

1. Place them in `data/pdfs/`
2. Run the PDF cataloger:
   ```bash
   python cli/main.py import-pdfs data/pdfs/ --match-existing
   ```

This matches PDFs to existing paper records by author/title.

To copy PDFs from another folder into AF storage:

```bash
python cli/main.py import-pdfs /path/to/pdfs --copy-to-storage --storage-dir data/pdfs
```

### Inbox (Drop Folder) Ingestion

Drop PDFs into the inbox folder (default: `data/inbox_pdfs/`) and process them:

```bash
python cli/main.py inbox
```

To continuously watch the inbox:

```bash
python cli/main.py inbox --watch --interval 30
```

By default, PDFs are copied into `data/pdfs/` and archived to
`data/inbox_pdfs/processed/` after processing.

**UI:** Import → **Inbox PDFs** tab lets you upload or process inbox PDFs.

---

## Citation Network

### Building the Network

Fetch citations for papers in your corpus:

```bash
python cli/main.py citations --fetch --limit 100
```

This uses OpenAlex to get:
- **References** - Papers this paper cites
- **Citations** - Papers that cite this paper

### Expansion Queue

Discovered papers (from citations) are added to the expansion queue. Review and add relevant ones:

**Via UI:** Citations page → Expansion Queue tab

**Via CLI:**
```bash
python cli/main.py citations --show-queue
python cli/main.py citations --add-from-queue --limit 20
```

### Visualization

The UI provides an interactive citation network graph showing:
- Green nodes: Papers in your corpus
- Gray nodes: External papers (referenced but not in corpus)
- Node size: Number of connections

---

## Article Eater Integration

Article Finder prepares job bundles for Article Eater (the claim extraction system).

### Creating Job Bundles

```bash
# Build bundles for papers marked send_to_eater
python cli/main.py build-jobs --status send_to_eater --output data/job_bundles/
```

Each bundle contains:
- `paper.json` - Paper metadata (ae.paper.v1 schema)
- `paper.pdf` - PDF file

### Processing Results

After Article Eater processes bundles:

```bash
python cli/main.py import-results data/ae_outputs/
```

This imports:
- Claims (ae.claim.v1)
- Rules (ae.rule.v1)
- Provenance info

---

## Command Line Interface

### Full Command Reference

```bash
# Import references
python cli/main.py import FILE [--source NAME] [--limit N]
python cli/main.py import-pdfs DIRECTORY [--source NAME]

# Enrich metadata
python cli/main.py enrich [--limit N]

# Classification
python cli/main.py classify --load-taxonomy
python cli/main.py classify --build-centroids
python cli/main.py classify --score-all [--report]

# Citations
python cli/main.py citations --fetch [--limit N]
python cli/main.py citations --show-queue
python cli/main.py citations --add-from-queue [--limit N]

# PDFs
python cli/main.py download [--limit N]

# Article Eater integration
python cli/main.py build-jobs [--status STATUS] [--output DIR]
python cli/main.py import-results DIRECTORY

# Utilities
python cli/main.py stats
python cli/main.py ui  # Launch Streamlit
```

---

## Troubleshooting

### Common Issues

**"No papers imported"**

Check your file format. The importer needs either:
- A DOI column, OR
- A title column, OR
- A citation string column

View the import preview to verify column detection.

**"ModuleNotFoundError"**

Ensure you installed in editable mode:
```bash
pip install -e .
```

**"Rate limited by API"**

Set your email in config for polite pool access:
```yaml
apis:
  openalex:
    email: "your-email@university.edu"
```

**"Embedding model download failed"**

The first run downloads the sentence-transformers model (~90MB). Ensure internet access.

### Getting Help

- Check the error message for specific guidance
- Review `data/article_finder.log` for detailed logs
- Run tests: `python -m pytest tests/`

---

## Version History

### v3.2.2 (Current)

- **Smart importer** - Handles messy citation strings, fuzzy column detection
- **PDF cataloger** - Import from PDF filenames
- **Citation visualization** - Interactive network graphs
- **Comprehensive tests** - Full test coverage for import
- **Better error messages** - Actionable fix suggestions

### v3.1.0

- Initial release with taxonomy classification
- Article Eater integration
- Basic import functionality

---

## License

Article Finder v3.2 is proprietary software developed for neuroarchitecture research.

## Contact

For support, contact the development team.

# Health Check

Run:

```bash
python cli/main.py doctor
```
