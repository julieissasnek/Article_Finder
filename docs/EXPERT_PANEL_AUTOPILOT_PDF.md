# EXPERT PANEL REVIEW: Autopilot PDF Acquisition & Corpus Growth

## Article Finder v3.2.2 — Operational Effectiveness Assessment

**Review Focus**: Can this system operate autonomously to discover relevant papers and acquire PDFs, given the realities of academic publishing infrastructure?

---

## Panel Composition

| Expert | Domain | Institutional Context |
|--------|--------|----------------------|
| **Dr. Paxton** | Scholarly Communication Infrastructure | Former director of a large university library's digital services; deep knowledge of access mechanisms |
| **Dr. Crawley** | Academic Web Scraping & APIs | 15 years building academic data pipelines at a major bibliometrics firm |
| **Dr. Mendez** | Open Access Policy | Research on OA adoption rates, embargo periods, and publisher behavior (Latin America focus) |
| **Dr. Reiter** | Autonomous Systems Design | Building unattended data collection systems that run for months |
| **Dr. Kirsh** | Domain Theory | Neuroarchitecture research methodology (returning panelist) |

---

## EXECUTIVE SUMMARY

Article Finder v3.2.2 has solid architectural foundations for autonomous operation, but **PDF acquisition is the critical bottleneck** that prevents true "autopilot" operation. The current system relies almost exclusively on Unpaywall for PDF access, which captures approximately **25-40% of the academic literature** depending on discipline. For interdisciplinary fields like neuroarchitecture—which spans architecture, psychology, neuroscience, and environmental health—the OA coverage is highly uneven.

**Key Finding**: The system needs a **multi-channel acquisition strategy** that gracefully handles the reality that most papers require institutional authentication. Without this, corpus growth will plateau at whatever proportion of the literature is openly accessible.

---

## 1. CURRENT STATE ASSESSMENT

### 1.1 What the System Does Well

**Dr. Crawley**: The current pipeline architecture is sound:

```
Seed Papers → Fetch Citations → Score vs Taxonomy → Filter → Queue → Attempt PDF
                    ↓                    ↓
             500 candidates         45 relevant (9%)
                                         ↓
                                    ~12 OA PDFs (27%)
```

The bounded expansion with taxonomy filtering is genuinely valuable—it prevents the corpus from drifting into pure neuroscience or pure architecture. The deduplication logic (DOI + fuzzy title + author overlap) is robust.

**Dr. Reiter**: The orchestration layer (`discovery_orchestrator.py`) has appropriate phase tracking, statistics collection, and error handling. It can resume from failures. The rate limiting and API caching are properly implemented.

### 1.2 The PDF Acquisition Bottleneck

**Dr. Paxton**: Let me be direct: the current PDF acquisition strategy is **insufficient for autonomous operation**. Here's why:

| Source | Current Implementation | Coverage | Reliability |
|--------|----------------------|----------|-------------|
| Unpaywall | ✅ Implemented | 25-40% of literature | High |
| Publisher OA | ❌ Not implemented | Varies by journal | Medium |
| Institutional Repository | ❌ Not implemented | 10-25% additional | Medium |
| Author Self-Archive | ❌ Not implemented | 15-30% additional | Low |
| Preprint Servers | ❌ Not implemented | Growing but discipline-specific | High |
| Library Proxy | ❌ Not possible without user action | ~100% | N/A |

**Current `pdf_downloader.py` Analysis**:

```python
# Lines 56-74: Only checks Unpaywall
def get_pdf_url(self, doi: str) -> Optional[str]:
    data = self.get_paper(doi)
    if not data:
        return None
    
    # Check best OA location
    if data.get('best_oa_location'):
        pdf_url = data['best_oa_location'].get('url_for_pdf')
        ...
```

This single-source strategy means **60-75% of relevant papers will never have PDFs acquired automatically**.

### 1.3 Field-Specific OA Coverage

**Dr. Mendez**: Open Access coverage varies dramatically by subfield. For neuroarchitecture research:

| Subfield | Estimated OA Rate | Why |
|----------|-------------------|-----|
| Environmental Psychology | 20-30% | Psychology journals traditionally low OA |
| Architecture/Design | 15-25% | Design journals rarely OA; many are RIBA/AIA affiliated |
| Neuroscience | 40-50% | Strong preprint culture (bioRxiv), PLOS, etc. |
| Building Science | 25-35% | Energy/sustainability journals increasingly OA |
| Environmental Health | 35-45% | NIH mandate drives OA for funded research |

For an interdisciplinary corpus, expect **30-35% OA coverage** at best.

---

## 2. THE LIBRARY AUTHENTICATION PROBLEM

### 2.1 Why This Is Fundamentally Hard

**Dr. Paxton**: Let me explain why "just log in through the library" isn't automatable:

1. **Authentication Mechanisms Vary**:
   - EZproxy (rewrite URLs): `https://ezproxy.ucsd.edu/login?url=https://doi.org/...`
   - Shibboleth/SAML (federated identity): Multi-step redirects, often with CAPTCHAs
   - IP authentication (on-campus only)
   - VPN + IP authentication
   
2. **Session Management**:
   - Sessions expire (typically 2-8 hours)
   - Concurrent session limits
   - Usage monitoring and rate limiting by publishers

3. **Terms of Service**:
   - Most publisher agreements explicitly prohibit automated downloading
   - Systematic downloading can trigger IP blocks
   - Can endanger entire institution's access

4. **Legal/Ethical Considerations**:
   - Aaron Swartz's case remains cautionary
   - Libraries are careful about enabling bulk access

### 2.2 What IS Possible with Institutional Access

**Dr. Paxton**: Despite limitations, there are legitimate approaches:

**Option A: Manual-Triggered Batch Download**
- User authenticates once via browser
- System queues papers needing PDFs
- User clicks "Download All" and browser handles auth
- PDFs land in watched folder → system processes them

**Option B: Interlibrary Loan (ILL) Integration**
- Automated ILL requests for high-priority papers
- ILL systems often have APIs (OCLC WorldShare, ILLiad)
- PDFs arrive via email → system processes them
- Slower but legitimate and comprehensive

**Option C: Document Delivery Services**
- Commercial services (Copyright Clearance Center, British Library)
- API-accessible, legal, but cost per article ($15-45)
- Good for small number of critical papers

**Option D: Author Contact System**
- Automated emails requesting PDFs from corresponding authors
- Surprisingly effective (30-50% response rate for recent papers)
- Legal and encouraged by most publishers
- ResearchGate/Academia.edu author pages

---

## 3. RECOMMENDED MULTI-CHANNEL ACQUISITION STRATEGY

### 3.1 Tiered Acquisition Pipeline

**Dr. Reiter**: The system needs a **waterfall acquisition strategy** that tries multiple channels in order of effort/cost:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACQUISITION WATERFALL                        │
│                                                                 │
│  Tier 1: Automatic (Zero User Effort)                          │
│  ├── Unpaywall API                     [IMPLEMENTED]           │
│  ├── CORE API (aggregated repositories) [NOT IMPLEMENTED]      │
│  ├── Semantic Scholar API               [NOT IMPLEMENTED]      │
│  ├── PubMed Central API                 [NOT IMPLEMENTED]      │
│  └── Preprint Server APIs               [NOT IMPLEMENTED]      │
│       (bioRxiv, arXiv, SSRN, OSF)                              │
│                                                                 │
│  Tier 2: Semi-Automatic (One-Time User Setup)                  │
│  ├── Watched folder for manual downloads                       │
│  ├── Email inbox scanning for ILL/author PDFs                  │
│  └── Browser extension for one-click save                      │
│                                                                 │
│  Tier 3: User-Triggered Batch                                  │
│  ├── Generate download URLs for library proxy                  │
│  ├── Export to Zotero/Mendeley (they handle auth)              │
│  └── ILL batch request generation                              │
│                                                                 │
│  Tier 4: Active Outreach                                       │
│  ├── Author contact automation (with rate limits)              │
│  └── ResearchGate/Academia.edu scraping (carefully)            │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Implementation Priority

**Dr. Reiter**: For minimum viable autopilot, implement Tier 1 fully first:

| API | Estimated Additional Coverage | Implementation Effort | Priority |
|-----|------------------------------|----------------------|----------|
| CORE (core.ac.uk) | +10-15% | Low (REST API, well-documented) | P0 |
| Semantic Scholar | +5-10% (OA links) | Low | P0 |
| PubMed Central | +5-15% (biomedical papers) | Low | P0 |
| bioRxiv/medRxiv | +5-10% (neuroscience preprints) | Low | P1 |
| arXiv | +2-5% (computational papers) | Low | P1 |
| OSF Preprints | +2-5% (psychology preprints) | Low | P1 |

**Combined Tier 1 estimate: 50-65% coverage** (up from current 25-40%).

### 3.3 Tier 2: The Watched Folder Pattern

**Dr. Reiter**: This is the key to handling authenticated downloads without violating ToS:

```python
# Proposed: ingest/pdf_watcher.py

class PDFWatcherService:
    """
    Watches a folder for new PDFs.
    When user manually downloads via library proxy,
    they drop PDFs here and system matches them.
    """
    
    def __init__(self, watch_dir: Path, database: Database):
        self.watch_dir = watch_dir
        self.db = database
        self.matcher = PDFMatcher(database)  # Fuzzy title/DOI matching
    
    def process_new_files(self):
        """Check for new PDFs and match to paper records."""
        for pdf_path in self.watch_dir.glob("*.pdf"):
            if self._is_new(pdf_path):
                # Extract metadata from PDF
                metadata = self._extract_pdf_metadata(pdf_path)
                
                # Try to match to existing paper record
                paper = self.matcher.match(
                    title=metadata.get('title'),
                    authors=metadata.get('authors'),
                    doi=metadata.get('doi')
                )
                
                if paper:
                    self._link_pdf_to_paper(paper, pdf_path)
                else:
                    self._queue_for_manual_review(pdf_path, metadata)
```

**User workflow**:
1. System shows "Papers needing PDFs" list in UI
2. User clicks paper → opens library proxy URL in browser
3. User downloads PDF, drops in `~/Downloads/ArticleFinder/` folder
4. System auto-matches and processes

This respects ToS while enabling comprehensive coverage.

---

## 4. CONCRETE IMPLEMENTATION RECOMMENDATIONS

### 4.1 P0: Expand Automatic Coverage (Tier 1)

**Deliverable**: `ingest/multi_source_downloader.py`

```python
class MultiSourceDownloader:
    """
    Tries multiple OA sources in sequence.
    """
    
    SOURCES = [
        ('unpaywall', UnpaywallClient),
        ('core', COREClient),
        ('semantic_scholar', SemanticScholarClient),
        ('pubmed_central', PMCClient),
        ('preprints', PreprintAggregator),
    ]
    
    def download(self, paper: Dict) -> DownloadResult:
        """Try each source until success."""
        for source_name, client_class in self.SOURCES:
            client = client_class(email=self.email)
            result = client.try_download(paper)
            
            if result.success:
                return result
            
            # Log attempt for analytics
            self._log_attempt(paper, source_name, result)
        
        # All automatic sources exhausted
        return DownloadResult(
            success=False,
            needs_manual=True,
            suggested_urls=self._generate_manual_urls(paper)
        )
```

**Estimated effort**: 2-3 days
**Estimated coverage improvement**: +15-25%

### 4.2 P0: CORE API Integration

**Dr. Crawley**: CORE (core.ac.uk) aggregates 200+ million items from 10,000+ repositories. Critical for institutional coverage:

```python
class COREClient:
    """Client for CORE API v3."""
    
    BASE_URL = "https://api.core.ac.uk/v3"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(10)  # 10 req/sec
    
    def search_by_doi(self, doi: str) -> Optional[Dict]:
        """Find paper by DOI, get download URL."""
        response = self._request(f"outputs/doi/{quote(doi)}")
        if response and response.get('downloadUrl'):
            return {
                'url': response['downloadUrl'],
                'source': 'core',
                'repository': response.get('repositoryDocument', {}).get('name')
            }
        return None
    
    def search_by_title(self, title: str) -> List[Dict]:
        """Fuzzy title search for when DOI unavailable."""
        # CORE's search is quite good for title matching
        ...
```

**Requires**: Free API key from core.ac.uk (instant registration)

### 4.3 P1: PDF Watcher Service

**Deliverable**: `ingest/pdf_watcher.py` + UI integration

**UI Component** (`ui/pages/8_downloads.py`):
```python
def render_pending_downloads():
    """Show papers needing manual download."""
    pending = get_papers_without_pdf(limit=100)
    
    st.header("Papers Needing Manual Download")
    st.markdown("""
    These papers couldn't be found via Open Access sources.
    Click a paper to open via your library proxy, then save the PDF
    to your watched folder.
    """)
    
    for paper in pending:
        col1, col2, col3 = st.columns([4, 1, 1])
        
        with col1:
            st.write(f"**{paper['title'][:80]}...**")
            st.caption(f"{paper.get('year')} | {paper.get('venue', 'Unknown venue')}")
        
        with col2:
            # Generate library proxy URL
            proxy_url = generate_proxy_url(paper['doi'], st.session_state.library_proxy)
            st.link_button("📖 Library", proxy_url)
        
        with col3:
            # Direct publisher link as fallback
            st.link_button("🔗 DOI", f"https://doi.org/{paper['doi']}")
```

### 4.4 P1: Download Queue & Status Tracking

**Dr. Reiter**: For autopilot operation, need persistent tracking of acquisition attempts:

```sql
-- Add to database schema
CREATE TABLE pdf_acquisition_log (
    paper_id TEXT NOT NULL,
    attempt_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'unpaywall', 'core', 'manual', etc.
    status TEXT NOT NULL,  -- 'success', 'not_found', 'error', 'rate_limited'
    error_message TEXT,
    response_metadata TEXT,  -- JSON blob with source-specific info
    PRIMARY KEY (paper_id, attempt_timestamp)
);

CREATE TABLE pdf_acquisition_queue (
    paper_id TEXT PRIMARY KEY,
    priority INTEGER DEFAULT 0,  -- Higher = more important
    first_queued TEXT NOT NULL,
    last_attempt TEXT,
    attempt_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- 'pending', 'exhausted', 'manual_needed'
    next_retry_after TEXT  -- For rate limiting/backoff
);
```

This enables:
- "Which papers have we never tried to acquire?"
- "Which papers exhausted all automatic sources?"
- "What's our success rate by source?"

### 4.5 P2: Author Contact Automation

**Dr. Mendez**: This is surprisingly effective for recent papers (published within last 3-5 years):

```python
class AuthorContactService:
    """
    Generates polite PDF request emails to corresponding authors.
    Respects rate limits and tracks responses.
    """
    
    EMAIL_TEMPLATE = """
Subject: PDF Request: {title}

Dear {author_name},

I am a researcher at UC San Diego working on neuroarchitecture research.
I am very interested in your paper:

"{title}" ({year})

I was unable to access it through our library and would greatly appreciate
if you could share a PDF copy for my research.

Thank you for your time,
{requester_name}
{requester_institution}
"""
    
    def generate_request(self, paper: Dict) -> Optional[EmailRequest]:
        # Find corresponding author email
        # (Often available in OpenAlex, CrossRef, or paper metadata)
        ...
```

**Dr. Crawley caution**: This must be:
- Rate limited (max 10/day to any single domain)
- Tracked to avoid duplicate requests
- Opt-out mechanism for authors who decline

---

## 5. CORPUS GROWTH PROJECTIONS

### 5.1 Current State Model

**Dr. Reiter**: Given current Unpaywall-only strategy:

```
Starting corpus:          638 papers
Papers with DOI:          ~550 (86%)
OA coverage (Unpaywall):  ~35%
Papers with PDF:          ~190 (30% of total)

Per expansion iteration:
  Papers scored:          500
  Pass filter (9%):       45
  OA available (35%):     16
  Successfully downloaded: ~14 (after errors)

After 3 iterations:
  New papers queued:      ~120
  New PDFs acquired:      ~40
  
After 10 iterations:
  Diminishing returns as corpus saturates nearby literature
  Estimate: ~400 papers, ~140 PDFs (35%)
```

### 5.2 With Multi-Source Strategy (Tier 1 Complete)

```
OA coverage (combined):   ~55%

After 3 iterations:
  New papers queued:      ~120
  New PDFs acquired:      ~65 (vs 40)
  
After 10 iterations:
  Estimate: ~400 papers, ~220 PDFs (55%)
```

### 5.3 With Manual Download Integration (Tier 2)

```
User downloads 20 papers/week for critical gaps

After 3 months:
  Automatic acquisitions: ~220
  Manual acquisitions:    ~240
  Total with PDF:         ~460 (65-70% coverage)
```

**Dr. Kirsh**: For neuroarchitecture research, 65-70% PDF coverage would be **transformative**. Most systematic reviews in this field work with 50-100 papers total. A corpus of 400+ papers with PDFs and extracted claims would be unprecedented.

---

## 6. QUALITY VS. QUANTITY CONSIDERATIONS

### 6.1 The Claim Extraction Dependency

**Dr. Kirsh**: PDFs are only valuable if Article Eater can extract claims. Current bottleneck:

```
Papers with PDF: 190
Papers sent to AE: ?
Papers with extracted claims: ?
Usable claims: ?
```

**Recommendation**: Add claim extraction metrics to dashboard. No point acquiring PDFs if extraction pipeline is backed up.

### 6.2 Prioritization for Manual Downloads

**Dr. Kirsh**: Not all papers are equally important. Suggest priority scoring:

```python
def compute_download_priority(paper: Dict) -> float:
    """Higher = more important to acquire PDF."""
    score = 0.0
    
    # Recency bonus (recent papers more important)
    if paper.get('year'):
        years_old = 2026 - paper['year']
        score += max(0, 10 - years_old)  # 0-10 points
    
    # Citation impact
    citations = paper.get('cited_by_count', 0)
    score += min(10, citations / 10)  # 0-10 points
    
    # Taxonomy relevance
    relevance = paper.get('taxonomy_score', 0)
    score += relevance * 20  # 0-20 points
    
    # Methodology bonus (RCTs, meta-analyses more valuable)
    if 'meta-analysis' in paper.get('title', '').lower():
        score += 15
    if paper.get('methodology_type') == 'randomized_controlled_trial':
        score += 10
    
    return score
```

Manual download effort should target **high-priority, non-OA papers**.

---

## 7. OPERATIONAL RECOMMENDATIONS

### 7.1 Autopilot Mode Definition

**Dr. Reiter**: Define what "autopilot" actually means for this system:

**Level 1: Fire-and-Forget (Current Goal)**
- Run `discover` command, walk away for 24 hours
- System expands corpus, acquires what it can
- Generates report of what needs manual intervention

**Level 2: Supervised Autonomous**
- Daily cron job runs discovery
- Weekly email digest: "23 papers need manual download"
- User does 30-min manual download session
- Repeat

**Level 3: Fully Autonomous (Not Achievable)**
- Would require ToS violations or institutional integration
- Not recommended

### 7.2 Suggested Operational Workflow

```
┌────────────────────────────────────────────────────────────────┐
│                    WEEKLY AUTOPILOT CYCLE                      │
│                                                                │
│  Monday 2am: Cron runs `python cli/main.py discover`          │
│    ├── Expand from recent papers                              │
│    ├── Try all Tier 1 sources for PDFs                        │
│    ├── Queue papers for Article Eater                         │
│    └── Generate digest                                        │
│                                                                │
│  Monday 9am: Email digest arrives                             │
│    "Discovered 47 papers, acquired 28 PDFs                    │
│     19 papers need manual download (sorted by priority)"      │
│                                                                │
│  Tuesday: 30-min manual download session                      │
│    ├── Open top 10 priority papers via library proxy          │
│    ├── Download PDFs to watched folder                        │
│    └── PDF watcher auto-processes                             │
│                                                                │
│  Continuous: Article Eater processes PDFs                     │
│    └── Claims extracted and added to knowledge graph          │
└────────────────────────────────────────────────────────────────┘
```

### 7.3 Metrics Dashboard

Add to Streamlit UI:

```python
def render_acquisition_dashboard():
    st.header("PDF Acquisition Status")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Papers in Corpus", total_papers)
        
    with col2:
        st.metric("With PDF", papers_with_pdf, 
                  delta=f"{papers_with_pdf/total_papers*100:.0f}%")
        
    with col3:
        st.metric("Need Manual", papers_need_manual)
        
    with col4:
        st.metric("Claims Extracted", total_claims)
    
    # Acquisition funnel
    st.subheader("Acquisition Funnel (Last 7 Days)")
    funnel_data = get_acquisition_funnel()
    # Discovered → Filtered → PDF Attempted → PDF Success → AE Processed → Claims
```

---

## 8. RISK ASSESSMENT

### 8.1 Legal/Compliance Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Publisher blocks IP for excessive downloading | Medium | High | Rate limiting, jitter, respect robots.txt |
| Library revokes API access | Low | High | Stay within ToS, document legitimate research use |
| DMCA takedown for hosting PDFs | Low | Medium | PDFs stored locally only, not redistributed |

### 8.2 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unpaywall API changes/deprecation | Medium | High | Multi-source strategy reduces dependency |
| API rate limiting during discovery | High | Medium | Exponential backoff, caching, overnight runs |
| PDF matching fails for manual downloads | Medium | Medium | Multiple matching strategies, manual review queue |

---

## 9. IMPLEMENTATION ROADMAP

### Phase 1: Multi-Source PDF (2 weeks)
- [ ] Implement CORE API client
- [ ] Implement Semantic Scholar PDF lookup
- [ ] Implement PMC client
- [ ] Create `MultiSourceDownloader` with waterfall logic
- [ ] Add acquisition logging to database

### Phase 2: Manual Download Support (1 week)
- [ ] Implement PDF watcher service
- [ ] Add "Papers Needing Download" UI page
- [ ] Implement library proxy URL generator (configurable)
- [ ] Add download priority scoring

### Phase 3: Operational Automation (1 week)
- [ ] Create acquisition dashboard in UI
- [ ] Implement email digest generation
- [ ] Add cron-friendly command mode
- [ ] Integration tests for overnight runs

### Phase 4: Author Contact (Optional, 1 week)
- [ ] Implement author email extraction
- [ ] Create rate-limited request generator
- [ ] Add response tracking
- [ ] Build opt-out list management

---

## 10. CONCLUSION

**Dr. Paxton (Summary)**: Article Finder v3.2.2 has sound bones for autonomous corpus growth. The critical gap is PDF acquisition strategy. The current Unpaywall-only approach will plateau at ~35% coverage—insufficient for comprehensive literature synthesis.

**Dr. Reiter (Summary)**: True "fire-and-forget" autopilot isn't achievable given academic publishing realities, but "supervised autonomous" (30 minutes of human attention per week) can achieve 65-70% coverage—more than sufficient for most research purposes.

**Dr. Crawley (Summary)**: The multi-source strategy (CORE, Semantic Scholar, PMC, preprints) is the lowest-hanging fruit. Implementing these 4 additional sources will meaningfully improve coverage with minimal effort.

**Dr. Kirsh (Summary)**: For neuroarchitecture specifically, the priority scoring should weight methodology heavily. A single well-conducted RCT on daylight and mood is worth more than 50 correlational studies. The system should help identify these high-value targets for manual acquisition.

---

## APPENDIX A: API Reference Summary

| API | Endpoint | Rate Limit | Auth | Notes |
|-----|----------|------------|------|-------|
| Unpaywall | api.unpaywall.org/v2/{doi} | 100K/day | Email | Current impl |
| CORE | api.core.ac.uk/v3 | 10/sec | API key (free) | Best for repositories |
| Semantic Scholar | api.semanticscholar.org | 100/5min (unauth) | Optional API key | Good metadata |
| PMC | eutils.ncbi.nlm.nih.gov | 3/sec (unauth), 10/sec (key) | API key | Biomedical only |
| bioRxiv | api.biorxiv.org | Unclear | None | Preprints |
| CrossRef | api.crossref.org | 50/sec (polite) | Email header | Already implemented |
| OpenAlex | api.openalex.org | 10/sec (polite) | Email | Already implemented |

## APPENDIX B: Library Proxy URL Patterns

```python
LIBRARY_PROXY_PATTERNS = {
    'ezproxy': 'https://{domain}/login?url=https://doi.org/{doi}',
    'oclc': 'https://{domain}/oclc/{doi}',
    'openathens': 'https://go.openathens.net/redirector/{institution}?url=https://doi.org/{doi}',
}

# UCSD specific
UCSD_PROXY = 'https://doi-org.ucsd.idm.oclc.org/{doi}'
```

---

*Review conducted: January 2026*
*Panel: Paxton, Crawley, Mendez, Reiter, Kirsh*
