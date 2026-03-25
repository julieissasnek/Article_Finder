# Neuroarchitecture System Architecture Review
## Comprehensive Analysis & Integration Plan
### Date: 2026-01-25

---

# TABLE OF CONTENTS

1. [System Overview](#system-overview)
2. [Article Finder (AF) Architecture](#article-finder-af-architecture)
3. [Article Eater (AE) Architecture](#article-eater-ae-architecture)
4. [BN_graphical Architecture](#bn_graphical-architecture)
5. [Tagging Contractor Analysis](#tagging-contractor-analysis)
6. [Outcome Contractor Analysis](#outcome-contractor-analysis)
7. [Expert Panel Review](#expert-panel-review)
8. [RAG & Knowledge Extraction Research](#rag--knowledge-extraction-research)
9. [Proposed Contracts](#proposed-contracts)
10. [Integration Recommendations](#integration-recommendations)
11. [Implementation Plan](#implementation-plan)

---

# SYSTEM OVERVIEW

## Active Repositories

| Repository | Purpose | Status |
|------------|---------|--------|
| Article_Finder_v3_2_3 | Corpus curation & taxonomy-bounded discovery | Production |
| Article_Eater_PostQuinean_v1 | Quinean epistemic extraction engine | Production |
| BN_graphical | Bayesian causal inference (new version) | Development |
| BN | Bayesian causal inference (old version) | Legacy |
| Tagging_Contractor | Antecedent vocabulary (424 tags) | Production |
| Outcome_Contractor | Consequent vocabulary (23 seed terms) | Prototype |

## Revised System Architecture

```
                            LITERATURE (PDFs)
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         ARTICLE FINDER (AF)                              │
│  Taxonomy-bounded corpus curation & discovery                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ ingest → triage (9-facet) → expand → bundle → send to AE           │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ ae.paper.v1
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         ARTICLE EATER (AE)                               │
│  Quinean epistemic extraction engine                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ extract → beliefs → web coherence → bridge warrants → persistence  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  Key: Web of Belief (1300+ lines), theory registry, reflective equil.   │
└───────────┬───────────────────────────────────────────────────────────┬──┘
            │                                                           │
            │ theory priors                                             │ rules, claims
            │ tested predictions                                        │
            ▼                                                           ▼
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│    BAYESIAN NETWORK (BN)        │         │     OUTCOME_CONTRACTOR          │
│    ┌─────────────────────────┐  │         │    (Consequent Vocabulary)      │
│    │ BN_graphical (NEW):     │  │         │ ┌────────────────────────────┐  │
│    │ • 3-layer causal model  │  │         │ │ 23 seed terms (7 domains)  │  │
│    │ • Goldilocks functions  │  │         │ │ Resolution + candidate Q   │  │
│    │ • MCMC uncertainty      │  │         │ │ Export to AF/AE/BN         │  │
│    │ • Partial do-calculus   │  │         │ │ GAPS: ops, epistemic lvls  │  │
│    └─────────────────────────┘  │         │ └────────────────────────────┘  │
└─────────────────┬───────────────┘         └─────────────────────────────────┘
                  │ attribute vectors
                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        TAGGING_CONTRACTOR                               │
│                     (Antecedent Vocabulary)                             │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ 424 tags across 25 domains (56% 2D-extractable)                   │ │
│  │ Contracts: image_tagger, bn, article_eater                        │ │
│  │ GAPS: thermal, acoustic, window quality, furniture ergonomics     │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        IMAGE TAGGING MODULE                             │
│  (Vision → Attribute Extraction)                                        │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ VLM classifiers, photometric analysis, depth estimation           │ │
│  │ Semantic segmentation (SegFormer-B5), object detection            │ │
│  │ Regional/localized extraction (71.5% of tags benefit)             │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

# ARTICLE FINDER (AF) ARCHITECTURE

## Overview
**Article Finder v3.2.3** is a specialized research literature management system for neuroarchitecture research. It's a corpus curation and knowledge synthesis platform that:
- Ingests papers from diverse sources
- Classifies them against a 9-facet taxonomy
- Expands the corpus through citation following
- Integrates with Article Eater for claim extraction

## Key Statistics
- **Version:** 3.2.3
- **Lines of Code:** ~24,926 Python
- **Major Modules:** 12
- **Taxonomy Nodes:** 1000+
- **Database Tables:** 15+

## Module Structure

### CORE (`/core/`)
- `database.py`: SQLite schema and operations
- Tables: papers, facets, facet_nodes, paper_scores, queue, ae_claims, ae_rules

### INGEST (`/ingest/`)
- `smart_importer.py`: Fuzzy column detection (50+ variants)
- `citation_parser.py`: MDPI, APA, MLA, Chicago, Vancouver parsing
- `doi_resolver.py`: CrossRef + OpenAlex integration
- `pdf_downloader.py`: Unpaywall integration
- `zotero_bridge.py`: Zotero local library integration

### TRIAGE (`/triage/`)
- `taxonomy_loader.py`: 9-facet YAML taxonomy (1850 lines)
- `embeddings.py`: sentence-transformers (all-MiniLM-L6-v2)
- `scorer.py`: HierarchicalScorer with cosine similarity
- `classifier.py`: Batch classification with thresholds

### SEARCH (`/search/`)
- `bounded_expander.py`: Taxonomy-filtered citation expansion
- `deduplicator.py`: DOI + fuzzy title + author matching
- `citation_network.py`: Citation graph management
- `discovery_orchestrator.py`: Full pipeline automation
- `gap_analyzer.py`: Knowledge gap identification

### EATER_INTERFACE (`/eater_interface/`)
- `pipeline.py`: AF→AE orchestration
- `job_bundle.py`: ae.paper.v1 bundle creation
- `invoker.py`: AE CLI execution
- `output_parser.py`: AE output import

### KNOWLEDGE (`/knowledge/`)
- `semantic_search.py`: Vector similarity search
- `claim_graph.py`: Paper→Claim→Construct graph
- `query_engine.py`: Natural language queries
- `synthesis.py`: Meta-analytic aggregation

## 9-Facet Taxonomy

1. **Environmental Factors (IVs)**: Luminous, Thermal, Acoustic, Air Quality, Spatial, Materials, Biophilic, Visual Aesthetics, Wayfinding, User Control
2. **Outcomes (DVs)**: Cognitive, Affective, Social, Behavioral, Physiological, Neural, Health
3. **Subjects**: Age, Role, Special populations, Cultural/Geographic
4. **Settings**: Educational, Workplace, Healthcare, Residential, Public/Commercial, Outdoor, Laboratory
5. **Methodology**: Experimental, Observational, Survey, Physiological, Synthesis
6. **Modality**: Physical, Simulated (VR/AR)
7. **Cross-Modal Interactions**: Vision×Audition, Vision×Thermal, etc.
8. **Theoretical Framework**: Restoration, Perception, Preference, Environmental, Design
9. **Evidence Strength**: Experimental, Observational, Synthesized, Theoretical

## Data Flow

```
[Paper Sources] → [Smart Import] → [DOI Resolution] → [Database]
                                          ↓
                                    [PDF Download]
                                          ↓
[Taxonomy] → [Semantic Scorer] → [Triage Filter] → [Job Bundle Creator]
                                          ↓
                              [Article Eater]
                                          ↓
[Knowledge Synthesis] ← [AE Output Parser] ← [Claims/Rules]
```

---

# ARTICLE EATER (AE) ARCHITECTURE

## Overview
**Article_Eater V22.0.0 (Post-Quinean)** is an AI-powered research synthesis system implementing Quinean Web of Belief epistemology rather than foundationalist Bayesian networks.

## PostQuinean Philosophy

The system instantiates Quine's coherentist epistemology where:
- No level has privileged epistemic status
- Warrant flows bidirectionally (mutual constraint)
- Coherence across the entire web is the criterion of acceptance
- Even "observations" are uncertain and revisable
- Findings can exist as "stubs" without immediate theory attachment

## Three-Track Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       INPUT: PDF Corpus                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
   TRACK A:                          TRACK B:
   EXTRACTION                        EPISTEMIC LAYER
   ┌─────────────────────┐          ┌──────────────────────────┐
   │ app/tasks/pipeline  │          │ Quinean Engine           │
   │ PDF→Claims→Rules    │────────▶ │ • web_of_belief.py       │
   │ (Contract-shaped)   │          │ • extraction_to_web.py   │
   └─────────────────────┘          │ • bridge_warrants.py     │
                                    └──────────┬───────────────┘
                                               │
        ┌──────────────────────────────────────┘
        ▼
   TRACK C: DATABASE
   ┌──────────────────────┐
   │ Persistence Layer    │
   │ • web_persistence    │
   │ • theory_registry    │
   │ • ae.db (SQLite)     │
   └──────────────────────┘
```

## Key Modules

### Epistemic Engine
| Module | Lines | Purpose |
|--------|-------|---------|
| `web_of_belief.py` | 1300+ | Core coherentist epistemology engine |
| `extraction_to_web.py` | 600+ | Maps claims → Beliefs, rules → Constraints |
| `bridge_warrants.py` | 1000+ | Bridge warrant types and lifecycle |
| `refined_epistemic.py` | 900+ | Boghossian semantics, Glymour dependencies |
| `abstraction_levels.py` | 600+ | Theory nesting, criterial rules |
| `validation.py` | 500+ | Five validation phases |
| `web_persistence.py` | 2000+ | Persist web state, inverse-variance weighting |

### Belief System
- **Belief Levels:** THEORETICAL, INTERMEDIATE, EMPIRICAL, OBSERVATIONAL
- **Belief Status:** STUB, TENTATIVE, ESTABLISHED, ENTRENCHED, ANOMALOUS
- **Constraints:** SUPPORTS, CONTRADICTS, EXPLAINS, INSTANTIATES, ANALOGOUS, BRIDGES
- **Causal Direction:** UNKNOWN, CORRELATIONAL, FORWARD, REVERSE, BIDIRECTIONAL

## Contracts (ae_af/)

| Schema | Purpose |
|--------|---------|
| `ae.claim.v1.schema.json` | Individual extracted claims |
| `ae.rule.v1.schema.json` | Synthesized rules |
| `ae.paper.v1.schema.json` | Input paper metadata |
| `ae.result.v1.schema.json` | Top-level output |
| `ae.web_state.v1.schema.json` | Web state serialization |
| `ae.bridge.v1.schema.json` | Bridge warrants |

## Sprint Status (V22.0.0)

All 9 sprints complete with 247+ tests passing:
- Sprint 1: Extraction→Web mapper ✅
- Sprint 2: Pipeline integration + serialization ✅
- Sprint 3: Bridge warrants ✅
- Sprint 4: Outcome taxonomy extensions ✅
- Sprint 5: Persistence & accumulation ✅
- Sprint 6: Causal structure & scope conditions ✅
- Sprint 7: Environment taxonomy ✅
- Sprint 8: Multi-theory validation ✅
- Sprint 9: Gold standard corpus ✅

---

# BN_GRAPHICAL ARCHITECTURE

## Overview
Three-layer Bayesian causal inference model predicting psychological outcomes from interior space image attributes.

## Architecture

```
IMAGE → ATTRIBUTES (Layer 1) → MEDIATORS (Layer 2) → OUTCOMES (Layer 3)
         Computer Vision    Psychological Perceptions   Psychological States
         Linear + Goldilocks  Bayesian Regression     Causal Inference
```

## Key Innovation: Goldilocks Functions

Instead of linear relationships, the system recognizes optimal levels:
- Too little wood coverage = cold/sterile
- Too much wood coverage = dark/oppressive
- **Optimal ≈ 40% coverage**

Mathematical form: `f(x) = exp(-(x - optimal)² / (2×width²))`

The system **learns optimal values and tolerances from data** via Bayesian inference.

## Module Structure

### Statistical Engine (4,799 lines)

| Module | Lines | Purpose |
|--------|-------|---------|
| `core.py` | 455 | Goldilocks functions, convergence checks, calibration |
| `model_a.py` | 1,238 | Attributes → Mediators (hierarchical regression) |
| `model_b.py` | 1,479 | Mediators → Outcomes (causal SEM) |
| `pipeline.py` | 686 | End-to-end integration, uncertainty propagation |
| `database.py` | 519 | PostgreSQL interface |
| `schemas.py` | 339 | Pydantic validation |

### Model A: Attributes → Mediators
```
M_j = β₀ + Σᵢ βᵢ × f(Attribute_i) + ε

Where:
- f(·) ∈ {linear, goldilocks}
- Goldilocks: f(x) = β × exp(-(x - θ)² / (2τ²))
- ε ~ Normal(0, σ²)
```

### Model B: Mediators → Outcomes
- NetworkX DiGraph with provenance-tracked edges
- Each edge has evidence quality (theory/observational/experimental/validated)
- Implements do-calculus for interventional queries (partial)

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| POST /predict | Core prediction with uncertainty |
| POST /predict-difference | Interventional queries |
| GET /causal-graph/{version} | Graph structure |
| GET /health, /status, /models | Administrative |
| POST /cache/clear, /reload-models | Management |

## GUI Applications

1. **Image Analyzer**: Form input, real-time prediction, what-if analysis
2. **Graph Explorer**: Interactive visualization, node details, edge list
3. **Admin Dashboard**: Health monitoring, model versions, actions

## Database Schema (PostgreSQL)

- **images**: Metadata
- **attributes**: CV-extracted features
- **mediator_ratings**: Human ratings (30 raters per image)
- **outcome_ratings**: Psychological state measures
- **model_parameters**: Posterior distributions
- **causal_graph**: Edge definitions with provenance
- **goldilocks_parameters**: Learned optimal points

## Dependencies

Critical: pymc==5.10.4, pytensor==2.18.6, numpy==1.24.3, arviz==0.17.0

## Test Coverage

144 passing tests (locally without DB), 176 expected with full PostgreSQL

## Critical Caveats

1. **No Real Data**: Trained only on synthetic data
2. **Graph Surgery Missing**: Do-calculus incomplete
3. **Environment Sensitive**: PyMC/numpy/pytensor version fragile
4. **Causal Claims Unvalidated**: All edges theory-based, no RCT validation

---

# TAGGING CONTRACTOR ANALYSIS

## Overview
Production-ready neuroarchitecture tag registry containing **424 tags** across **25 domains**.

## Coverage Summary

| Category | Tags | Status |
|----------|------|--------|
| Article Eater Antecedents (env.ae.*) | 92 | ACTIVE |
| V1 Standard Lighting/Spatial | 82 | ACTIVE |
| V2A Neuroarchitecture Tags | 74 | ACTIVE |
| CNFA Computational Metrics | 48 | ACTIVE |
| Other (affective, cognitive, biophilia, sound, touch, smell) | 128 | MIXED |

## Extractability

| Status | Count | Percentage |
|--------|-------|------------|
| Fully Extractable (2D) | 239 | 56.4% |
| Partially Extractable | 173 | 40.8% |
| Not Extractable (2D) | 12 | 2.8% |

## Defined Contracts

1. **image_tagger_contract_v0.2.8.json**: Input/output for vision extraction
2. **bn_contract_v0.2.8.json**: Mapping to BN attributes
3. **article_eater_contract_v0.2.8.json**: Search term expansion

## Critical Gaps

### High Priority (20 tags needed)
- **Window Quality**: window_wall_ratio, view_distance_layering, window_operability_cues
- **Thermal Cues**: surface_warmth_cues, visible_air_movement, hvac_visibility
- **Acoustic Cues**: hard_absorptive_ratio, echo_presence_cues, sound_masking_affordances
- **Furniture Ergonomic**: seating_height_variety, back_support_visibility, posture_variety_cues
- **Spatial Sequence**: compression_release_ratio, vista_revelation_rate, sightline_clarity

### Localization Requirement
71.5% of tags (303/424) require or benefit from spatial localization. Currently only 4% support regional tagging.

---

# OUTCOME CONTRACTOR ANALYSIS

## Overview
Canonical vocabulary authority for human-side outcomes (DVs). Status: **Working Prototype (v1.0.0)**

## Current State

| Component | Status | Completeness |
|-----------|--------|--------------|
| Database (6 tables) | ✓ Working | 90% |
| Term resolution | ✓ Working | 80% |
| Export (4 formats) | ✓ Working | 75% |
| CLI (12 commands) | ✓ Working | 90% |
| Harvesting from AE | ✓ Working | 85% |
| Operationalizations | ⚠ Schema only | 10% |
| Epistemic levels | ✗ Missing | 0% |
| Theory mappings | ✗ In AE, not OC | 0% |
| Tests | ✗ None | 0% |

## Seed Data (23 terms)

| Domain | Terms |
|--------|-------|
| cog | cog, cog.attention, cog.attention.sustained, cog.attention.selective, cog.memory, cog.memory.working, cog.performance |
| affect | affect, affect.mood, affect.mood.positive, affect.mood.negative, affect.stress, affect.anxiety |
| behav | behav, behav.productivity, behav.sleep |
| social | social, social.interaction, social.collaboration |
| physio | physio, physio.fatigue, physio.alertness |
| health | health, health.wellbeing |

## Required Enhancements

1. Add operationalization management (CLI + export)
2. Add epistemic level metadata to schema
3. Integrate CNFA architectural outcomes (arch.*, art.*)
4. Add theory relevance mappings
5. Write test suite (target: 50 tests)
6. Harmonize with AE's outcome_taxonomy.py

---

# EXPERT PANEL REVIEW

## Panel Composition

| Expert | Domain | Perspective |
|--------|--------|-------------|
| Dr. Judea Pearl | Causal inference | Do-calculus, graph surgery, counterfactuals |
| Dr. Nancy Cartwright | Philosophy of science | Causal powers, mechanisms, warrants |
| Dr. Clark Glymour | Causal discovery | PC algorithm, constraint-based methods |
| Dr. Herbert Simon | Bounded rationality | Multi-level abstraction, satisficing |
| Bovens & Hartmann | Probabilistic coherence | Coherence measures, belief expansion |

## BN Comparative Analysis

| Dimension | BN (Old) | BN_graphical (New) | Assessment |
|-----------|----------|-------------------|------------|
| Architecture | 3-layer | 3-layer | Both sound |
| Functional Forms | Linear only | **Goldilocks (learned)** | NEW superior |
| Inference | MCMC (PyMC5) | MCMC (PyMC5) | Equivalent |
| Uncertainty | Full posterior | Full posterior | Both excellent |
| Do-calculus | Documented only | **Partial implementation** | Both incomplete |
| Graph Surgery | Not implemented | Not implemented | **Critical gap** |
| GUI | Basic | **Vue.js + Vanilla (3 apps)** | NEW much better |
| Provenance | Basic | **Comprehensive edge tracking** | NEW superior |
| Validation | Basic tests | **144 tests + calibration** | NEW more rigorous |
| Database | SQLite | PostgreSQL (16 tables) | NEW more scalable |

## Panel Comments

### Dr. Judea Pearl (on do-calculus)
> "Both implementations claim interventional capabilities but neither performs proper graph surgery. The do-operator requires removing incoming edges to the intervention node. What you have is essentially P(Y|X=x) dressed up as P(Y|do(X=x))."

**Recommendation:** Implement graph surgery, backdoor/frontdoor criterion checking, identifiability verification.

### Dr. Nancy Cartwright (on mechanism warrants)
> "The Goldilocks functions are a step forward. But the priors come from 'literature review' without specifying the causal powers involved. Without mechanism, you have correlation dressed as causation."

**Recommendation:** Integrate with AE's bridge warrants—document mechanism, enabling conditions, scope boundaries.

### Dr. Clark Glymour (on structure validation)
> "Neither BN validates its causal graph from data. You assume the structure based on theory, then fit parameters. This is backwards from discovery."

**Recommendation:** Add validation phase using PC-algorithm-style conditional independence tests.

### Dr. Herbert Simon (on bounded rationality)
> "The three-layer abstraction is appropriate for satisficing. But 30+ attributes without clear aggregation rules creates complexity. Multi-level abstraction requires explicit roll-up functions."

**Recommendation:** Define aggregation rules from Tagging_Contractor's fine-grained tags to BN's input attributes.

### Bovens & Hartmann (on coherence)
> "For Quinean integration, both BNs need a coherence metric evaluating the entire model against the Web of Belief. Currently, BN outputs predictions independent of AE's epistemic state."

**Recommendation:** Add coherence feedback loop—BN prediction → Belief node → coherence check → anomaly triggers investigation.

## Quinean Adaptation Recommendations

### 1. Bidirectional Warrant
```
Current:  Theory → Priors → BN → Predictions
Quinean:  Theory ↔ Priors ↔ BN ↔ Predictions ↔ Web of Belief
```

### 2. Revisable Observations
```
Current:  Attributes are fixed inputs
Quinean:  Attributes have uncertainty + can be revised by theory
```

### 3. Coherence as Criterion
```
Current:  R² on held-out test set
Quinean:  Global coherence across BN + AE + literature
```

### 4. No Privileged Level
```
Current:  Observations → Mediators → Outcomes (hierarchical)
Quinean:  All three levels mutually constrain
```

---

# RAG & KNOWLEDGE EXTRACTION RESEARCH

## RAG Best Practices (2025-2026)

### Anthropic's Contextual Retrieval
- Prepends chunk-specific explanatory context before embedding
- Reduces failed retrievals by 49%, 67% with reranking
- Use hybrid search (sparse BM25 + dense semantic embeddings)

### Advanced RAG Types
| Type | Description | Use Case |
|------|-------------|----------|
| Self-RAG | Self-reflective mechanism | Reduces hallucinations by 52% |
| GraphRAG | Combines vector search with KGs | Up to 99% search precision |
| Corrective RAG | Web searches to correct outdated retrievals | Time-sensitive domains |
| Adaptive RAG | Dynamically adjusts retrieval strategies | Variable query complexity |

## Knowledge Extraction Pipeline

```
Stage 1: Document Parsing & Segmentation
    ↓
Stage 2: Entity & Relationship Extraction
    ↓
Stage 3: Cross-Paragraph Refinement
    ↓
Stage 4: Full-Text Verification & Validation
```

## Neuro-Symbolic Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              Neural Component (LLM)                             │
│    - Pattern recognition                                        │
│    - Semantic understanding                                     │
│    - Candidate answer generation                                │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│           Symbolic Solver (Separate)                            │
│    - Logical consistency checking                               │
│    - Knowledge graph grounding                                  │
│    - Rule-based verification                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Bayesian + Coherentist Integration

### Traditional Pearl Hierarchy
1. Association (seeing): P(Y|X)
2. Intervention (doing): P(Y|do(X))
3. Counterfactuals (imagining): P(Y_x|X', Y')

### Quinean Reconceptualization
| Traditional View | Coherentist Adaptation |
|-----------------|----------------------|
| Observations are foundational | Observations are theory-laden and revisable |
| Causal structure is inferred from data | Causal structure and data mutually constrain |
| Counterfactuals depend on lower levels | All levels provide mutual constraints |
| Bottom-up inference | Bidirectional belief propagation |
| Privileged observational status | Coherence as criterion of acceptance |

---

# PROPOSED CONTRACTS

## Contract 1: Unified Taxonomy Contract

```yaml
schema: "neuroarch.taxonomy.v1"
version: "1.0.0"

antecedents:
  source: "Tagging_Contractor"
  path: "/core/trs-core/v0.2.8/registry/registry_v0.2.8.json"
  count: 424
  domains: 25

consequents:
  source: "Outcome_Contractor"
  path: "/contracts/oc_export/outcome_vocab.json"
  count: 100+ (target)
  domains: 7+

mappings:
  antecedent_to_consequent: "rules.jsonl"
  consequent_to_theory: "theory_outcome_relevance.json"
  antecedent_to_bn: "bn_contract_v0.2.8.json"
```

## Contract 2: Antecedent Tag Contract

```json
{
  "schema": "neuroarch.antecedent.v1",
  "tag_id": "env.v2a_070.prospect_refuge",
  "canonical_name": "Prospect-Refuge Balance",
  "domain": "spatial",
  "level": 3,

  "extraction": {
    "2d_extractable": "partial",
    "3d_extractable": "yes",
    "method": ["monocular_depth", "semantic_segmentation"],
    "confidence_threshold": 0.75
  },

  "localization": {
    "scope": "region",
    "typical_regions": ["seating_zone", "entryway"]
  },

  "bn_mapping": {
    "bn_attribute": "prospect_refuge_ratio",
    "aggregation": "weighted_mean",
    "functional_form": "goldilocks",
    "optimal_prior": 0.6,
    "width_prior": 0.15
  },

  "theory_relevance": {
    "prospect_refuge_theory": 0.95,
    "attention_restoration_theory": 0.60
  }
}
```

## Contract 3: Consequent Outcome Contract

```json
{
  "schema": "neuroarch.consequent.v1",
  "term_id": "affect.stress.perceived",
  "canonical_name": "Perceived Stress",
  "domain": "affect",
  "level": 3,

  "cognates": ["stress", "psychological stress"],

  "operationalizations": [
    {
      "measure_id": "PSS-10",
      "measure_name": "Perceived Stress Scale (10-item)",
      "measure_type": "self_report",
      "epistemic_level": "EMPIRICAL",
      "validity": 0.85
    }
  ],

  "epistemic_level_default": "INTERMEDIATE",

  "theory_relevance": {
    "stress_recovery_theory": 0.95,
    "allostatic_load_model": 0.85
  },

  "bn_mapping": {
    "bn_outcome": "stress",
    "direction_from_warmth": "negative"
  },

  "causal_pathways": {
    "mechanism": "HPA axis activation, sympathetic arousal",
    "enabling_conditions": ["acute or chronic exposure"]
  }
}
```

## Contract 4: BN ↔ AE Coherence Contract

```json
{
  "schema": "neuroarch.coherence.v1",

  "bn_to_ae": {
    "prediction_as_belief": {
      "belief_level": "EMPIRICAL",
      "belief_status": "TENTATIVE",
      "source_type": "model_prediction"
    },
    "trigger_coherence_check": true,
    "anomaly_threshold": 0.3
  },

  "ae_to_bn": {
    "theory_priors": {
      "source": "theory_registry",
      "update_frequency": "on_web_state_change"
    }
  },

  "bidirectional_feedback": {
    "low_coherence_actions": ["flag_for_review", "suggest_prior_revision"],
    "high_coherence_actions": ["strengthen_theory_confidence"]
  }
}
```

---

# INTEGRATION RECOMMENDATIONS

## Problem 1: One-Way Flow
**Current:** AF→AE only. AE cannot influence AF's triage or search.
**Solution:** AE publishes `theory_gap` events; AF subscribes and triggers targeted search.

## Problem 2: Duplicate Taxonomies
**Current:** AF has `taxonomy.yaml`; AE has `outcome_taxonomy.py`
**Solution:** Single source of truth in `/contracts/shared/`

## Problem 3: No Feedback Loop
**Current:** Extracted claims don't refine AF's scoring model
**Solution:** Evidence propagation: claim → prediction test → theory confidence → prior update

## Problem 4: BN Isolation
**Current:** BN outputs independent of AE's epistemic state
**Solution:** Coherence feedback loop; BN predictions become Belief nodes

## Recommended Communication Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SHARED KNOWLEDGE LAYER                        │
│  contracts/shared/                                               │
│    ├── taxonomy.v2.schema.json    (unified 9-facet)             │
│    ├── theory.v1.schema.json      (theory definitions)          │
│    ├── prediction.v1.schema.json  (testable predictions)        │
│    └── evidence.v1.schema.json    (test results)                │
└──────────────────────────────────────────────────────────────────┘
                    │                           │
        ┌───────────┴───────────┐   ┌──────────┴────────────┐
        ▼                       ▼   ▼                        ▼
┌───────────────────┐     ┌─────────────────────────────────────┐
│   ARTICLE FINDER  │     │           ARTICLE EATER             │
│ Listens for:      │◄────│ Publishes:                          │
│ • theory_gap      │     │ • theory_gap                        │
│ • evidence_need   │     │ • evidence_need                     │
│ Publishes:        │────►│ Listens for:                        │
│ • paper_queued    │     │ • paper_queued                      │
└───────────────────┘     └─────────────────────────────────────┘
```

---

# IMPLEMENTATION PLAN

## Phase 1: Foundation (Weeks 1-4)

### 1.1 Unify Taxonomies
- Create `/contracts/shared/` directory
- Merge TC's registry + OC's vocabulary + AE's extensions
- Define single-source-of-truth
- Version: taxonomy.v1

### 1.2 Complete Outcome_Contractor
- Add operationalization CLI commands
- Add epistemic level to schema and exports
- Integrate CNFA architectural outcomes
- Add theory relevance mappings
- Write test suite (target: 50 tests)

### 1.3 Extend Tagging_Contractor
- Add 20 high-priority tags
- Enable regional tagging for 300+ existing tags
- Update BN contract with new attributes

## Phase 2: Integration (Weeks 5-8)

### 2.1 BN_graphical Quinean Adaptation
- Implement graph surgery for do-calculus
- Add structure validation (PC-algorithm checks)
- Create coherence feedback loop to AE
- Document mechanisms for all Goldilocks relationships

### 2.2 AF ↔ AE Bidirectional Communication
- AE publishes `theory_gap` events
- AF subscribes and triggers targeted search
- Implement evidence propagation loop
- Add web state export for AF visualization

### 2.3 BN ↔ AE Integration
- BN predictions → Belief nodes in web
- AE coherence checks on predictions
- Theory priors → BN prior updates
- Anomaly detection triggers investigation

## Phase 3: Validation (Weeks 9-12)

### 3.1 End-to-End Pipeline Test
- Import papers → Extract claims → Build rules → Predict outcomes
- Compare BN predictions to literature claims
- Measure coherence across entire system

### 3.2 Real Data Collection
- Define minimum viable dataset (50 images, 30 raters)
- Collect human ratings for mediators and outcomes
- Train BN on real data; validate calibration

### 3.3 Expert Panel Review
- Convene panel for architecture review
- Validate contract completeness
- Identify remaining gaps

## Phase 4: Expansion (Weeks 13-16)

### 4.1 Image Tagger Implementation
- Deploy SegFormer-B5 for semantic segmentation
- Deploy Depth Anything V2 for depth estimation
- Implement 20 new tag extractors
- Validate on benchmark images

### 4.2 Consequent Tag Discovery
- Harvest new outcomes from AE claims
- Implement candidate clustering (LLM-assisted)
- Build review interface for new consequents

### 4.3 Theory-Driven Discovery Loop
- AE identifies under-tested theories
- AF searches for testing papers
- AE extracts evidence
- BN validates predictions
- Loop closes

---

# APPENDIX: Key File Locations

## Article Finder
- `/Users/davidusa/REPOS/Article_Finder_v3_2_3/`
- Config: `config/taxonomy.yaml`
- Contracts: `contracts/ports.json`

## Article Eater
- `/Users/davidusa/REPOS/Article_Eater_PostQuinean_v1/`
- Core: `src/services/web_of_belief.py`
- Contracts: `contracts/ae_af/schemas/`

## BN_graphical
- `/Users/davidusa/REPOS/BN_graphical/`
- Engine: `statistical_engine/`
- API: `api/`

## Tagging Contractor
- `/Users/davidusa/REPOS/Tagging_Contractor/`
- Registry: `core/trs-core/v0.2.8/registry/registry_v0.2.8.json`
- Contracts: `core/trs-core/v0.2.8/contracts/`

## Outcome Contractor
- `/Users/davidusa/REPOS/Outcome_Contractor/`
- Core: `core/`
- Schema: `schemas/oc.export.v1.schema.json`

---

*Document generated: 2026-01-25*
*Author: Claude Code Architecture Review*
