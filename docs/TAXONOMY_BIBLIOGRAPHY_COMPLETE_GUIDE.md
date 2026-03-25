# TAXONOMY-INDEXED REFERENCE DATABASE
## Complete Guide for Article Finder v3.2.3

### THE TWO APPROACHES

Your Article Finder already has **citation chasing** via BoundedExpander. This document adds a complementary approach: **proactive API searching** through taxonomy cells.

| Approach | Tool | How It Works | Best For |
|----------|------|--------------|----------|
| **Citation Chasing** | BoundedExpander | Follow citations from seed papers | Finding closely related work |
| **Taxonomy Sweep** | Bibliographer Agent | Search APIs for each factor×outcome | Comprehensive coverage |
| **Manual Mining** | Consensus/Elicit/Scite | Human-guided queries with AI tools | High-quality curation |

---

## APPROACH 1: BIBLIOGRAPHER AGENT (Automated)

I've added `search/bibliographer.py` to your v3.2.3 codebase. It:

1. **Reads your taxonomy** (config/taxonomy.yaml)
2. **Creates cells** for each factor×outcome combination
3. **Searches multiple APIs** (OpenAlex, Semantic Scholar, PubMed)
4. **Scores results** against taxonomy
5. **Imports relevant papers** above threshold
6. **Tracks progress** per cell with persistence

### Usage

```bash
# Initialize cells from taxonomy (run once)
python cli/main.py bibliographer init

# Show progress
python cli/main.py bibliographer status

# Run full sweep (all pending cells)
python cli/main.py bibliographer run

# Run only HIGH priority cells
python cli/main.py bibliographer run --priority HIGH

# Run specific cell
python cli/main.py bibliographer run --cell env.luminous.daylight_out.cognitive.attention

# Show under-researched areas
python cli/main.py bibliographer gaps

# Reset a cell to re-search
python cli/main.py bibliographer reset --cell CELL_ID
```

### Adding to CLI

Add to `cli/main.py` in the argument parser section:

```python
# === BIBLIOGRAPHER ===
bib_parser = subparsers.add_parser('bibliographer', help='Taxonomy-driven discovery')
bib_parser.add_argument('subcmd', choices=['init', 'status', 'run', 'gaps', 'reset'])
bib_parser.add_argument('--priority', choices=['HIGH', 'MEDIUM', 'LOW'])
bib_parser.add_argument('--cell', help='Specific cell ID')
bib_parser.add_argument('--limit', type=int, default=50, help='Papers per API')
bib_parser.add_argument('--threshold', type=float, default=0.35)
bib_parser.add_argument('--email', help='Email for APIs')
bib_parser.set_defaults(func=cmd_bibliographer)
```

And import the handler:
```python
from search.bibliographer import cmd_bibliographer
```

### How It Works

```
Your Taxonomy (66KB, 1864 lines)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  10 Environmental Factors × 9 Outcomes = 90+ cells  │
│                                                      │
│  env.luminous.daylight × out.cognitive.attention    │
│  env.spatial.ceiling   × out.affective.mood         │
│  env.biophilic.plants  × out.physiological.stress   │
│  ...                                                 │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  For each cell, generate queries:                    │
│    "daylight attention"                              │
│    "daylight effects attention"                      │
│    "daylight attention building"                     │
│    "daylight attention office workplace"             │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  Search 3 APIs per query:                            │
│    • OpenAlex (comprehensive, free)                  │
│    • Semantic Scholar (ML-focused)                   │
│    • PubMed (biomedical focus)                       │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  Deduplicate → Score → Import if > threshold        │
└─────────────────────────────────────────────────────┘
```

### Priority Matrix

Some cells are more important than others:

| Priority | Factor → Outcome | Rationale |
|----------|------------------|-----------|
| HIGH | Luminous → Cognitive | Core neuroarchitecture |
| HIGH | Luminous → Circadian | Direct biological pathway |
| HIGH | Biophilic → Affective | Strong evidence base |
| HIGH | Acoustic → Cognitive | Workplace relevance |
| HIGH | Air Quality → Cognitive | Recent CO2 research |
| HIGH | Spatial → Social | Open plan controversy |
| MEDIUM | Most combinations | Default |
| LOW | Visual → Circadian | Weak connection |

---

## APPROACH 2: MANUAL MINING (Consensus, Elicit, Scite)

For high-quality curation, use AI research tools manually.

### TOOL COMPARISON

| Tool | Best For | Unique Feature | Export |
|------|----------|----------------|--------|
| **Consensus** | Yes/No questions | Consensus meter | CSV |
| **Elicit** | Data extraction | Custom columns | CSV, BibTeX |
| **Scite.ai** | Citation context | Supporting/contrasting | CSV |

### CONSENSUS (consensus.app)

**Use for:** "Does X affect Y?" questions

**Workflow:**
```
1. Go to consensus.app
2. Enter: "Does daylight exposure improve attention in offices?"
3. Review results and Consensus Meter
4. Export → CSV
5. Save as: L_daylight_AT_attention_consensus.csv
```

**Sample Queries:**
```
• Does natural daylight improve cognitive performance?
• Does ceiling height affect creativity?
• Do indoor plants reduce workplace stress?
• Does background noise impair concentration?
• Does CO2 level affect decision making?
• Do open plan offices reduce productivity?
```

### ELICIT (elicit.com)

**Use for:** Extracting structured data from papers

**Workflow:**
```
1. Go to elicit.com
2. Enter: "What is the effect of daylight on attention?"
3. Add columns: Sample size, Setting, Effect direction
4. Filter by methodology if needed
5. Export → CSV or BibTeX
6. Use "Find similar papers" for each key paper
```

**Power Features:**
- Custom extraction columns
- Methodology filtering
- "Find similar" for snowballing

### SCITE.AI (scite.ai)

**Use for:** Understanding how papers cite each other

**Workflow:**
```
1. Find seminal paper (e.g., Meyers-Levy ceiling height study)
2. Click paper → "Cited by"
3. Filter by "Supporting" to find replications
4. Filter by "Contrasting" to find challenges
5. Export citing papers
```

**Key Use Case:**
If a paper has many "contrasting" citations, the finding is contested. Important for:
- Identifying weak evidence
- Finding research opportunities
- Avoiding overclaiming

### IMPORT WORKFLOW

```bash
# After exporting CSVs from tools:

# 1. Place in organized folders
mkdir -p exports/consensus exports/elicit exports/scite

# 2. Run import script (I've provided import_bibliography.py)
python import_bibliography.py --merge ./exports/ --output master_bibliography.csv

# 3. Import to Article Finder
python cli/main.py import master_bibliography.csv --source manual_mining
```

---

## TRACKING SPREADSHEET

Create a master tracking sheet (I've provided `taxonomy_search_tracker.csv`):

| Cell | Factor | Outcome | Query | Consensus | Elicit | Scite | Total | PDFs | Status |
|------|--------|---------|-------|-----------|--------|-------|-------|------|--------|
| L_AT | Lighting | Attention | daylight attention | 23 | 31 | 45 | 52 | 34 | ✓ |
| L_ME | Lighting | Memory | daylight memory | 8 | 12 | 18 | 22 | 15 | ... |
| S_CR | Spatial | Creativity | ceiling creativity | 5 | 8 | 12 | 14 | 11 | ... |

---

## PDF ACQUISITION STRATEGIES

After building the bibliography, get PDFs:

| Strategy | Coverage | Effort | Legal |
|----------|----------|--------|-------|
| **Unpaywall** (via Retriever) | ~50% | Auto | ✓ |
| **Semantic Scholar** | +10% | Auto | ✓ |
| **Zotero + UCSD Library** | +25% | Semi-auto | ✓ |
| **Google Scholar** | +5% | Manual | ✓ |
| **Author requests** | +5% | Manual | ✓ |
| **ILL** | Remaining | Manual | ✓ |

Your existing Zotero bridge (`cli/main.py zotero`) handles the library integration!

---

## EXPECTED YIELD

Based on neuroarchitecture literature:

| Factor | Est. Papers | Open Access |
|--------|-------------|-------------|
| Luminous (Lighting) | 300-500 | ~60% |
| Spatial | 100-200 | ~50% |
| Biophilic | 200-400 | ~55% |
| Acoustic | 400-600 | ~50% |
| Thermal | 500-800 | ~45% |
| Air Quality | 300-500 | ~50% |
| Visual | 100-200 | ~55% |
| Workspace | 300-500 | ~45% |
| **Total** | **2,200-3,700** | **~50%** |

---

## INTEGRATION WITH ARTICLE EATER

The complete pipeline:

```
┌───────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE ACCUMULATION LOOP                     │
│                                                                    │
│  ┌──────────────┐                         ┌──────────────┐        │
│  │ Bibliographer │                         │   Frontiers  │        │
│  │    Agent      │◄────────────────────────│   (Gaps)     │        │
│  └──────┬───────┘                         └──────▲───────┘        │
│         │                                        │                 │
│         ▼                                        │                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────┴───────┐        │
│  │   Article    │───▶│   Article    │───▶│   Knowledge  │        │
│  │   Finder     │    │    Eater     │    │     Base     │        │
│  │   (Corpus)   │    │ (Extraction) │    │   (Graph)    │        │
│  └──────────────┘    └──────────────┘    └──────────────┘        │
│                                                                    │
│  Current: Manual iteration                                         │
│  Future: Closed-loop automation                                    │
└───────────────────────────────────────────────────────────────────┘
```

---

## QUICK START

```bash
# 1. Initialize bibliographer cells
cd ~/REPOS/article_finder_v3.2
source venv/bin/activate
python cli/main.py bibliographer init

# 2. Check status
python cli/main.py bibliographer status

# 3. Run HIGH priority cells first
python cli/main.py bibliographer run --priority HIGH

# 4. Check for gaps
python cli/main.py bibliographer gaps

# 5. Use discovery to chase citations
python cli/main.py discover --email you@ucsd.edu --iterations 2

# 6. Download PDFs
python cli/main.py download --limit 100

# 7. Use Zotero for paywalled papers
python cli/main.py zotero export --format ris
# ... import to Zotero, use "Find Available PDF" ...
python cli/main.py zotero import
```

---

## FILES PROVIDED

1. **search/bibliographer.py** — The automated agent (add to your codebase)
2. **taxonomy_search_tracker.csv** — Manual tracking spreadsheet
3. **import_bibliography.py** — Script to process manual exports
4. **This guide** — TAXONOMY_INDEXED_REFERENCE_DATABASE_GUIDE.md

---

## SUMMARY

| Approach | When to Use | Effort | Yield |
|----------|-------------|--------|-------|
| **Bibliographer Agent** | Initial sweep, ongoing maintenance | Low (automated) | High volume |
| **BoundedExpander** | After seed corpus established | Low (automated) | Quality citations |
| **Manual Mining** | Critical gaps, high-stakes topics | High (human) | Highest quality |
| **Zotero Bridge** | Paywalled papers | Medium | +25% PDFs |

**Recommended workflow:**
1. Run Bibliographer for systematic coverage
2. Use BoundedExpander to chase citations
3. Manual mining for critical gaps
4. Zotero for paywalled essentials
5. Article Eater for extraction
6. Knowledge graph identifies new frontiers
7. Loop back to step 1

This creates a **self-improving research system**.
