<!-- Version: 3.2.2 -->
# EXPERT PANEL REVIEW: Article Finder v3.2.2

## Panel Composition

| Expert | Domain | Focus |
|--------|--------|-------|
| **Dr. Catalogus** | Library & Information Science | Metadata standards, corpus management, controlled vocabularies |
| **Dr. Vector** | RAG Systems | Embeddings, retrieval, similarity search |
| **Dr. Emergent** | Post-RAG Architectures | Knowledge graphs, structured extraction, agentic systems |
| **Dr. Architect** | Systems Design | Scalability, maintainability, data flow |
| **Dr. Kirsh** | Domain Theory | Neuroarchitecture research methodology, scientific validity |

---

## EXECUTIVE SUMMARY

Article Finder v3.2.2 represents a **hybrid approach** combining:
1. Traditional library science (faceted classification, controlled vocabulary)
2. Modern ML (embeddings, semantic similarity)
3. Structured knowledge extraction (claims, rules via Article Eater)

**Overall Assessment**: The system is well-conceived but sits at a critical **architectural crossroads**. It has components of both RAG and post-RAG approaches without fully committing to either.

---

## 1. LIBRARY SCIENCE PERSPECTIVE (Dr. Catalogus)

### Strengths

**Faceted Classification**: The 9-facet taxonomy is excellent:
- Environmental Factors (IVs)
- Outcomes (DVs)  
- Subjects (Population)
- Settings (Building Typology)
- Methodology
- Modality (Real/Virtual)
- Cross-Modal Interactions
- Theoretical Framework
- Evidence Strength

This mirrors professional thesauri (MESH, Art & Architecture Thesaurus) and enables **post-coordinated indexing** - papers can be found by combining facets.

**Hierarchical Seeds**: Seed phrases for taxonomy nodes enable automatic classification while maintaining human-intelligible categories.

### Concerns

**C1. No Authority Control**
The system lacks authority files for:
- Author name normalization beyond simple surname extraction
- Institutional affiliations
- Geographic standardization (country codes vs. full names)

*Recommendation*: Integrate ORCID for authors, ROR for institutions.

**C2. Citation Format Chaos**
Supporting 5+ citation formats (MDPI, APA, MLA, Chicago, Vancouver) is pragmatic but creates inconsistency. The parsed data lacks confidence scores.

*Recommendation*: Add `parse_confidence` field; prefer DOI-resolved metadata over parsed.

**C3. Missing Subject Headings**
While the taxonomy is rich, there's no mapping to standard subject headings (e.g., Library of Congress, PsycINFO descriptors).

*Recommendation*: Add optional LCSH/PsycINFO mappings to taxonomy nodes for interoperability.

**C4. Provenance Tracking Incomplete**
`source` field tracks where data came from, but doesn't track:
- Which fields came from which source
- Confidence per field
- Update history

*Recommendation*: Implement field-level provenance using the existing `ae.provenance.v1` schema pattern.

---

## 2. RAG SYSTEMS PERSPECTIVE (Dr. Vector)

### Current Implementation

```
Paper → Embed(title + abstract) → Compare to Node Centroids → Score per Facet → Triage
```

Using `all-MiniLM-L6-v2` (384-dim, fast, general-purpose).

### Strengths

**Centroid-based Classification**: Computing centroids from seed phrases and scoring papers against them is efficient and interpretable. Better than pure k-NN for classification.

**Caching**: Embedding cache prevents redundant computation.

**Hierarchical Scoring**: Scoring at multiple levels (L1, L2, L3) of the taxonomy enables granular classification.

### Concerns

**C5. Domain Mismatch**
`all-MiniLM-L6-v2` is trained on general text. Academic abstracts use domain-specific vocabulary that may not embed well.

*Benchmark needed*: Compare against:
- `allenai/specter2` (academic papers)
- `pritamdeka/S-PubMedBert-MS-MARCO` (biomedical)
- Fine-tuned model on neuroarchitecture corpus

**C6. No Negative Examples**
Centroids are built from positive seeds only. There's no mechanism to:
- Define what a node is NOT
- Handle boundary cases
- Push away from adjacent concepts

*Recommendation*: Add `negative_seeds` to taxonomy nodes (e.g., for "daylighting": negative seeds could be "artificial lighting only").

**C7. Static Embeddings**
Paper embeddings are computed once at ingest. If taxonomy evolves:
- Old papers aren't re-scored
- Centroid updates don't propagate

*Recommendation*: Add `last_scored_at` timestamp; periodic re-scoring job.

**C8. No Retrieval Augmentation**
Despite having embeddings, there's no actual RAG pipeline for querying:
- "Find papers about daylight effects on mood"
- "What do studies say about open offices and concentration?"

*Recommendation*: Add semantic search endpoint using paper embeddings.

---

## 3. POST-RAG PERSPECTIVE (Dr. Emergent)

### The Paradigm Shift

RAG retrieves text chunks and hopes the LLM synthesizes correctly. Post-RAG approaches instead:
1. **Pre-extract structured knowledge** (claims, relations, entities)
2. **Build knowledge graphs** from extracted structures
3. **Query the graph** rather than retrieving documents
4. **Ground LLM responses** in verified graph facts

### Assessment: Halfway There

Article Finder has **excellent bones** for post-RAG:

| Component | Status | Gap |
|-----------|--------|-----|
| Structured Claims Schema | ✅ Excellent | - |
| Claims Extraction | 🔶 Via Article Eater | Not integrated in main flow |
| Knowledge Graph | ❌ Missing | No graph database, no relations |
| Claim-based Retrieval | ❌ Missing | Can't query by claim content |
| Contradiction Detection | ❌ Missing | No claim comparison |
| Evidence Synthesis | ❌ Missing | Can't aggregate claims |

### The Vision: What This Could Be

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT FLOW                             │
│  Papers → Classify → Triage → AE → Claims (stored, unused)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 POTENTIAL FLOW                              │
│  Papers → Claims → Knowledge Graph → Query Interface        │
│                       ↓                                     │
│              ┌───────────────────┐                          │
│              │ "Does daylight    │                          │
│              │  improve mood?"   │                          │
│              └─────────┬─────────┘                          │
│                        ↓                                    │
│  ┌─────────────────────────────────────────────────┐        │
│  │ 12 claims from 8 papers:                        │        │
│  │ • 9 positive effects (avg ES: d=0.45)          │        │
│  │ • 2 null findings                               │        │
│  │ • 1 negative (specific condition)              │        │
│  │ Moderators: exposure duration, season          │        │
│  └─────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### Critical Recommendations

**C9. Add Graph Layer**
Claims already have structured constructs (`environment_factors`, `outcomes`, `mediators`). These should form edges in a knowledge graph:

```
(daylighting)--[increases]->(positive_affect)
    |                           |
    | moderator: exposure_time  | effect_size: d=0.45
    | setting: office           | n=120
```

Technology options:
- Neo4j (full graph DB)
- NetworkX + SQLite (lightweight, current stack)
- LlamaIndex PropertyGraph

**C10. Claim Deduplication & Aggregation**
Multiple papers may make similar claims. Need:
- Claim similarity detection (embedding-based)
- Meta-analytic aggregation (combine effect sizes)
- Contradiction flagging

**C11. Provenance Chain**
Current: `paper → claim`
Needed: `paper → text_span → claim → rule → synthesis`

Every fact should trace back to exact source text.

---

## 4. SYSTEMS DESIGN PERSPECTIVE (Dr. Architect)

### Architecture Assessment

```
┌──────────────────────────────────────────────────────────┐
│                     CURRENT ARCHITECTURE                  │
│                                                          │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐  │
│  │ Ingest  │ → │ Triage  │ → │ Search  │ → │ Eater   │  │
│  │         │   │ Scoring │   │ Expand  │   │Interface│  │
│  └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘  │
│       │             │             │             │        │
│       └─────────────┴─────────────┴─────────────┘        │
│                         ↓                                │
│              ┌──────────────────┐                        │
│              │    SQLite DB     │                        │
│              │  (single file)   │                        │
│              └──────────────────┘                        │
└──────────────────────────────────────────────────────────┘
```

### Strengths

**S1. SQLite Simplicity**: Single-file database is perfect for research tool. No server, easy backup, portable.

**S2. Modular Design**: Clean separation between ingest/triage/search/eater modules.

**S3. Schema-Driven Contracts**: JSON schemas for Article Eater interface ensure compatibility.

**S4. Lazy Loading**: Embedding model only loads when needed, reducing startup time.

### Concerns

**C12. Single-Process Bottleneck**
Embedding, API calls, and database writes all happen sequentially. For 1000+ paper corpus:
- Embedding 1000 abstracts: ~5 minutes
- Fetching citations: ~15 minutes (rate-limited)
- No parallelization

*Recommendation*: Add async processing; consider job queue (even simple file-based).

**C13. No Incremental Updates**
Discovery orchestrator runs full passes. If interrupted:
- No checkpointing
- Must restart from beginning
- Risk of duplicate processing

*Recommendation*: Add `processed_at` timestamps; resume from last checkpoint.

**C14. Memory Pressure with Large Corpus**
`search_papers(limit=10000)` loads all papers into memory. With 10K+ papers with embeddings:
- ~15MB just for 384-dim embeddings
- Full paper objects: ~50MB+

*Recommendation*: Streaming/pagination for large operations; on-disk embedding index (FAISS, Annoy).

**C15. No API Layer**
Everything is CLI or Streamlit. No REST API for:
- Integration with other tools
- Remote access
- Programmatic queries

*Recommendation*: Add FastAPI layer (optional, for future extensibility).

**C16. Configuration Sprawl**
Settings in:
- `config/settings.yaml`
- `config/settings.local.yaml`
- Hardcoded defaults throughout

*Recommendation*: Centralize with clear precedence; document all settings.

---

## 5. DOMAIN THEORY PERSPECTIVE (Dr. Kirsh)

### The Scientific Goal

Article Finder serves a specific scientific purpose: **systematic mapping of environment-behavior relationships in built spaces**. This is not just corpus management—it's knowledge synthesis infrastructure for a nascent field.

### Epistemological Assessment

**Claim Structure is Excellent**
The `ae.claim.v1` schema captures exactly what matters:
- Causal vs. associational vs. mechanistic claims
- Explicit effect sizes and confidence intervals
- Moderators and mediators
- Evidence grounding in source text

This enables **meta-scientific analysis**: How many causal claims? What's the average effect size for daylight studies? Where are the gaps?

### Concerns

**C17. Vision Bias in Taxonomy**
The taxonomy is heavily weighted toward visual/luminous environment. Compare node counts:

| Facet | L1 Nodes | L2 Nodes | L3 Nodes |
|-------|----------|----------|----------|
| Luminous | 3 | 12 | 40+ |
| Acoustic | 2 | 8 | 20 |
| Thermal | 2 | 6 | 15 |
| Olfactory | 1 | 3 | 8 |

This reflects literature bias but also perpetuates it via the relevance filter.

*Recommendation*: Add weighting to compensate for understudied modalities.

**C18. Cross-Modal Interactions Underdeveloped**
Real environments are multi-sensory. The `cross_modal` facet exists but:
- Has only 5 nodes
- No systematic coverage of modality pairs
- No interaction type taxonomy (masking, enhancement, etc.)

*Recommendation*: Expand cross-modal taxonomy based on Goldilocks framework.

**C19. No Theoretical Integration**
The `theory` facet lists theories but doesn't track:
- Which claims support/contradict which theories
- Theory evolution over time
- Competing predictions

*Recommendation*: Add claim-theory links; enable theory-driven queries.

**C20. Effect Size Aggregation Missing**
The data structure supports effect sizes, but no tooling for:
- Forest plots
- Heterogeneity analysis (I²)
- Moderator analysis
- Publication bias detection

*Recommendation*: Add meta-analytic module; integrate with existing claim structure.

**C21. No Inverted-U Support**
The Goldilocks framework posits inverted-U relationships (optimal ranges). Current claim structure supports only monotonic effects. Need:
- Quadratic effect representation
- Optimal range specification
- Zone of proximal development marking

---

## PRIORITY MATRIX

| ID | Issue | Impact | Effort | Priority |
|----|-------|--------|--------|----------|
| C9 | Add Graph Layer | High | High | P1 |
| C5 | Domain-Specific Embeddings | High | Medium | P1 |
| C8 | Semantic Search | High | Low | P1 |
| C10 | Claim Aggregation | High | Medium | P1 |
| C12 | Parallel Processing | Medium | Medium | P2 |
| C6 | Negative Examples | Medium | Low | P2 |
| C7 | Re-scoring Job | Medium | Low | P2 |
| C17 | Vision Bias Weighting | Medium | Low | P2 |
| C13 | Incremental Updates | Medium | Medium | P2 |
| C20 | Meta-Analysis Module | High | High | P3 |
| C19 | Theory Links | Medium | Medium | P3 |
| C21 | Inverted-U Support | Medium | Medium | P3 |
| C1 | Authority Control | Low | Medium | P3 |
| C15 | API Layer | Low | Medium | P4 |

---

## RECOMMENDED NEXT SPRINT: Knowledge Graph Foundation

### Goal
Transform Article Finder from a **corpus manager** to a **knowledge synthesis engine**.

### Deliverables

1. **Claim Embedding Index**
   - Embed claim statements
   - Enable "find similar claims" queries
   - Cluster claims by topic

2. **Lightweight Graph Layer**
   - NetworkX-based (no new dependencies)
   - Nodes: Papers, Claims, Constructs (IVs/DVs)
   - Edges: paper→claim, claim→construct, construct→construct

3. **Query Interface**
   - "What affects [outcome]?"
   - "What does [environment factor] affect?"
   - "Show contradictory claims about [topic]"

4. **Claim Deduplication**
   - Detect semantically similar claims
   - Link to same underlying finding
   - Track replication vs. contradiction

### Implementation Sketch

```python
# New files:
knowledge/claim_graph.py      # NetworkX graph construction
knowledge/claim_embeddings.py # Claim-level embeddings
knowledge/query_engine.py     # Natural language queries
knowledge/synthesis.py        # Effect size aggregation

# New CLI commands:
python cli/main.py graph build           # Build claim graph
python cli/main.py graph query "daylight mood"  # Query graph
python cli/main.py synthesis --topic env.luminous.daylight  # Meta-analysis
```

---

## CONCLUSION

Article Finder v3.2.2 is a **solid foundation** with genuine innovation in:
- Faceted taxonomy for interdisciplinary field
- Structured claim extraction (via Article Eater)
- Bounded expansion with taxonomy filtering

The critical gap is **using the extracted knowledge**. Claims are extracted but not connected, aggregated, or queryable. The next phase should focus on building the **knowledge graph layer** that transforms this from a paper database into a claim-centric synthesis engine.

The domain-specific nature of neuroarchitecture research—with its cross-modal interactions, inverted-U relationships, and theory-driven questions—demands more than standard RAG. The structured claim approach positions this system well for the post-RAG paradigm, but that potential remains unrealized.

**Bottom Line**: The architecture is 70% of the way to something genuinely novel. The remaining 30%—knowledge graph, claim synthesis, theory integration—is where the real scientific value lies.

---

*Review conducted: January 2026*
*Panel: Catalogus, Vector, Emergent, Architect, Kirsh*
