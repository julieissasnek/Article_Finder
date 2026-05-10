# Version: 3.2.2
"""
Article Finder v3 - Database Schema and Operations
SQLite database with full multi-facet classification support
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from core.schema_registry import apply_pending_schema_migrations

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "article_finder.db"


def get_schema_sql() -> str:
    """Return the complete database schema."""
    return """
    -- ============================================================
    -- CORE TABLES
    -- ============================================================
    
    -- Papers table: Core corpus
    CREATE TABLE IF NOT EXISTS papers (
        paper_id TEXT PRIMARY KEY,              -- doi:10.xxx or sha256:xxx fallback
        doi TEXT UNIQUE,
        title TEXT NOT NULL,
        authors TEXT,                           -- JSON array
        year INTEGER,
        venue TEXT,
        publisher TEXT,
        abstract TEXT,
        url TEXT,
        
        -- Ingestion tracking
        source TEXT,                            -- excel|zotero|api|upload|citation_chase
        ingest_method TEXT,                     -- crossref|openalex|semanticscholar|zotero|manual
        finder_run_id TEXT,
        retrieved_at TEXT,
        
        -- File tracking
        pdf_path TEXT,
        pdf_sha256 TEXT,
        pdf_bytes INTEGER,
        
        -- Status state machine
        status TEXT DEFAULT 'candidate',        -- See STATUS_TRANSITIONS
        
        -- Triage scores (computed from taxonomy)
        triage_score REAL,
        triage_decision TEXT,                   -- send_to_eater|review|reject
        triage_reasons TEXT,                    -- JSON array
        
        -- Article Eater integration
        ae_job_path TEXT,                       -- Path to job bundle sent to AE
        ae_output_path TEXT,                    -- Path to AE output bundle
        ae_run_id TEXT,
        ae_profile TEXT,                        -- fast|standard|deep
        ae_status TEXT,                         -- SUCCESS|PARTIAL_SUCCESS|FAIL
        ae_n_claims INTEGER,
        ae_n_rules INTEGER,
        ae_confidence REAL,
        ae_warnings TEXT,                       -- JSON array
        
        -- Topic/Relevance scoring (from abstract_fetcher)
        off_topic_flag INTEGER DEFAULT 0,
        off_topic_score REAL,
        topic_score REAL,
        topic_decision TEXT,                    -- on_topic|off_topic|needs_abstract|possibly_off_topic
        topic_stage TEXT,                       -- final|needs_abstract
        
        -- Metadata
        tags TEXT,                              -- JSON array
        human_notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
    CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
    CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
    CREATE INDEX IF NOT EXISTS idx_papers_triage ON papers(triage_decision);
    
    -- ============================================================
    -- TAXONOMY TABLES
    -- ============================================================
    
    -- Facets: The orthogonal classification dimensions
    CREATE TABLE IF NOT EXISTS facets (
        facet_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT
    );
    
    -- Facet nodes: Hierarchical nodes within each facet
    CREATE TABLE IF NOT EXISTS facet_nodes (
        node_id TEXT PRIMARY KEY,               -- e.g., 'env.luminous.daylight'
        facet_id TEXT NOT NULL,
        parent_id TEXT,                         -- NULL for root nodes
        level INTEGER NOT NULL,                 -- 0, 1, 2, 3...
        name TEXT NOT NULL,
        description TEXT,
        seeds TEXT,                             -- JSON array of seed phrases
        FOREIGN KEY (facet_id) REFERENCES facets(facet_id),
        FOREIGN KEY (parent_id) REFERENCES facet_nodes(node_id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_nodes_facet ON facet_nodes(facet_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_parent ON facet_nodes(parent_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_level ON facet_nodes(level);
    
    -- Node centroids: Embedding vectors for each taxonomy node
    CREATE TABLE IF NOT EXISTS node_centroids (
        node_id TEXT PRIMARY KEY,
        embedding BLOB,                         -- Serialized numpy array
        embedding_model TEXT,                   -- e.g., 'all-MiniLM-L6-v2'
        exemplar_papers TEXT,                   -- JSON array of paper_ids
        computed_at TEXT,
        FOREIGN KEY (node_id) REFERENCES facet_nodes(node_id)
    );
    
    -- Paper facet scores: Multi-label classification per facet
    CREATE TABLE IF NOT EXISTS paper_facet_scores (
        paper_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        score REAL NOT NULL,                    -- 0.0 to 1.0
        classification_method TEXT,             -- embedding|manual|ae_extracted
        classified_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (paper_id, node_id),
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
        FOREIGN KEY (node_id) REFERENCES facet_nodes(node_id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_facet_scores_paper ON paper_facet_scores(paper_id);
    CREATE INDEX IF NOT EXISTS idx_facet_scores_node ON paper_facet_scores(node_id);
    CREATE INDEX IF NOT EXISTS idx_facet_scores_score ON paper_facet_scores(score);
    
    -- ============================================================
    -- CITATION NETWORK
    -- ============================================================
    
    -- Citations: Paper-to-paper citation links
    CREATE TABLE IF NOT EXISTS citations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_paper_id TEXT NOT NULL,          -- Paper containing the reference
        cited_paper_id TEXT,                    -- Resolved paper_id (may be NULL)
        cited_doi TEXT,                         -- DOI if known
        cited_title TEXT,                       -- For matching when DOI unavailable
        cited_authors TEXT,                     -- For matching
        cited_year INTEGER,
        citation_context TEXT,                  -- Surrounding text if extracted
        discovered_via TEXT,                    -- pdf_extraction|api|zotero
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (source_paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
        FOREIGN KEY (cited_paper_id) REFERENCES papers(paper_id) ON DELETE SET NULL,
        UNIQUE(source_paper_id, cited_doi)
    );
    
    CREATE INDEX IF NOT EXISTS idx_citations_source ON citations(source_paper_id);
    CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_paper_id);
    CREATE INDEX IF NOT EXISTS idx_citations_doi ON citations(cited_doi);
    
    -- Expansion queue: Papers discovered but not yet in corpus
    CREATE TABLE IF NOT EXISTS expansion_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doi TEXT UNIQUE,
        title TEXT,
        authors TEXT,
        year INTEGER,
        discovered_from TEXT,                   -- paper_id that referenced this
        discovery_count INTEGER DEFAULT 1,       -- How many papers cite this
        priority_score REAL,
        status TEXT DEFAULT 'pending',          -- pending|fetching|fetched|not_found|rejected
        rejection_reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_expansion_status ON expansion_queue(status);
    CREATE INDEX IF NOT EXISTS idx_expansion_priority ON expansion_queue(priority_score DESC);
    
    -- ============================================================
    -- ARTICLE EATER OUTPUTS
    -- ============================================================
    
    -- Claims: Extracted findings from Article Eater
    CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,              -- doi:...#c07
        paper_id TEXT NOT NULL,
        claim_type TEXT,                        -- causal|associational|null|moderated|mechanistic
        statement TEXT NOT NULL,
        
        -- Constructs (denormalized for search)
        environment_factors TEXT,               -- JSON array
        outcomes TEXT,                          -- JSON array
        mediators TEXT,                         -- JSON array
        moderators TEXT,                        -- JSON array
        
        -- Study details
        design TEXT,
        sample_n INTEGER,
        population TEXT,
        setting TEXT,
        task TEXT,
        
        -- Statistics
        effect_size_type TEXT,                  -- d|r|eta2|OR|RR
        effect_size_value REAL,
        p_value REAL,
        ci95_low REAL,
        ci95_high REAL,
        
        -- Provenance
        evidence_spans TEXT,                    -- JSON array
        ae_confidence REAL,
        ae_run_id TEXT,
        
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_claims_paper ON claims(paper_id);
    CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);
    CREATE INDEX IF NOT EXISTS idx_claims_effect ON claims(effect_size_value);
    
    -- Rules: Bayesian rule candidates from Article Eater
    CREATE TABLE IF NOT EXISTS rules (
        rule_id TEXT PRIMARY KEY,               -- doi:...#r03
        paper_id TEXT NOT NULL,
        rule_type TEXT,                         -- edge|cpd_hint|prior|constraint|interaction
        
        lhs TEXT NOT NULL,                      -- JSON array
        rhs TEXT NOT NULL,                      -- JSON array
        polarity TEXT,                          -- positive|negative|null|u_shaped|unknown
        
        strength_kind TEXT,
        strength_type TEXT,
        strength_value REAL,
        
        population TEXT,                        -- JSON array
        setting TEXT,                           -- JSON array  
        boundary_conditions TEXT,               -- JSON array
        
        evidence_links TEXT,                    -- JSON array of claim_ids
        ae_confidence REAL,
        ae_run_id TEXT,
        
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_rules_paper ON rules(paper_id);
    CREATE INDEX IF NOT EXISTS idx_rules_type ON rules(rule_type);
    CREATE INDEX IF NOT EXISTS idx_rules_polarity ON rules(polarity);
    
    -- ============================================================
    -- EMBEDDINGS (for semantic search)
    -- ============================================================
    
    -- Paper embeddings: Abstract/title embeddings for semantic search
    CREATE TABLE IF NOT EXISTS paper_embeddings (
        paper_id TEXT PRIMARY KEY,
        embedding BLOB NOT NULL,                -- Serialized numpy array
        embedding_model TEXT NOT NULL,
        text_hash TEXT,                         -- Hash of text used for embedding
        computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );
    
    -- ============================================================
    -- AUDIT & VERSIONING
    -- ============================================================
    
    -- ============================================================
    -- EXTRACTED TABLES
    -- ============================================================

    -- Extracted tables from PDFs
    CREATE TABLE IF NOT EXISTS extracted_tables (
        table_id TEXT PRIMARY KEY,           -- paper_id#t01
        paper_id TEXT NOT NULL,
        table_number INTEGER,                 -- 1, 2, 3...
        caption TEXT,
        table_type TEXT,                      -- results|demographics|summary|methodology|unknown

        -- Content in multiple formats
        raw_html TEXT,                        -- Original HTML if from PDF parser
        structured_json TEXT,                 -- JSON: {headers: [], rows: [[...]]}
        markdown TEXT,                        -- Markdown table representation

        -- Location & extraction metadata
        page_number INTEGER,
        extraction_method TEXT,               -- pdfplumber|camelot|tabula|llm|manual
        extraction_confidence REAL,

        -- Content flags
        has_statistics INTEGER DEFAULT 0,     -- Contains p-values, effect sizes, etc.
        has_sample_sizes INTEGER DEFAULT 0,   -- Contains N values
        needs_review INTEGER DEFAULT 0,

        -- Provenance
        extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        reviewer_notes TEXT,

        FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_tables_paper ON extracted_tables(paper_id);
    CREATE INDEX IF NOT EXISTS idx_tables_type ON extracted_tables(table_type);
    CREATE INDEX IF NOT EXISTS idx_tables_stats ON extracted_tables(has_statistics);

    -- ============================================================
    -- AUDIT & VERSIONING
    -- ============================================================

    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
        description TEXT
    );

    -- Insert initial schema version
    INSERT OR IGNORE INTO schema_version (version, description)
    VALUES (1, 'Initial schema with multi-facet taxonomy support');

    -- Schema version 2: extracted_tables
    INSERT OR IGNORE INTO schema_version (version, description)
    VALUES (2, 'Added extracted_tables for PDF table tracking');
    """


# Status state machine
STATUS_TRANSITIONS = {
    'candidate': ['pending_scorer', 'rejected', 'downloaded', 'queued_for_eater'],
    'pending_scorer': ['candidate', 'rejected', 'downloaded', 'queued_for_eater'],
    'rejected': [],  # Terminal
    'downloaded': ['queued_for_eater', 'rejected'],
    'queued_for_eater': ['sent_to_eater', 'rejected'],
    'sent_to_eater': ['eater_running'],
    'eater_running': ['processed_success', 'processed_partial', 'processed_fail'],
    'processed_success': ['needs_human_review'],
    'processed_partial': ['needs_human_review', 'queued_for_eater'],
    'processed_fail': ['queued_for_eater', 'rejected'],
    'needs_human_review': ['processed_success', 'rejected', 'queued_for_eater'],
}


class Database:
    """Article Finder database operations."""
    
    def __init__(self, db_path: Optional[Path] = None):
        # Handle both string and Path inputs
        if db_path is None:
            self.db_path = DEFAULT_DB_PATH
        elif isinstance(db_path, str):
            self.db_path = Path(db_path)
        else:
            self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database with schema."""
        with self.connection() as conn:
            conn.executescript(get_schema_sql())
            apply_pending_schema_migrations(conn)
    
    @contextmanager
    def connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    # ================================================================
    # PAPER OPERATIONS
    # ================================================================
    
    def add_paper(self, paper: Dict[str, Any]) -> str:
        """Add a paper to the database."""
        with self.connection() as conn:
            # Generate paper_id if not provided
            if 'paper_id' not in paper:
                if paper.get('doi'):
                    paper['paper_id'] = f"doi:{paper['doi']}"
                else:
                    import hashlib
                    title_hash = hashlib.sha256(paper['title'].encode()).hexdigest()[:12]
                    paper['paper_id'] = f"sha256:{title_hash}"
            
            # Serialize JSON fields
            for field in ['authors', 'triage_reasons', 'ae_warnings', 'tags']:
                if field in paper and isinstance(paper[field], (list, dict)):
                    paper[field] = json.dumps(paper[field])
            
            paper['updated_at'] = datetime.utcnow().isoformat()
            
            columns = ', '.join(paper.keys())
            placeholders = ', '.join(['?' for _ in paper])
            
            conn.execute(
                f"INSERT OR REPLACE INTO papers ({columns}) VALUES ({placeholders})",
                list(paper.values())
            )
            
            return paper['paper_id']
    
    def get_paper(self, paper_id: str) -> Optional[Dict]:
        """Get a paper by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            
            if row:
                return self._row_to_dict(row)
            return None
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict]:
        """Get a paper by DOI."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE doi = ?", (doi,)
            ).fetchone()
            
            if row:
                return self._row_to_dict(row)
            return None
    
    def update_paper_status(self, paper_id: str, new_status: str) -> bool:
        """Update paper status with state machine validation."""
        paper = self.get_paper(paper_id)
        if not paper:
            return False
        
        current_status = paper.get('status', 'candidate')
        
        # Validate transition
        if new_status not in STATUS_TRANSITIONS.get(current_status, []):
            raise ValueError(
                f"Invalid status transition: {current_status} -> {new_status}. "
                f"Valid transitions: {STATUS_TRANSITIONS.get(current_status, [])}"
            )
        
        with self.connection() as conn:
            conn.execute(
                "UPDATE papers SET status = ?, updated_at = ? WHERE paper_id = ?",
                (new_status, datetime.utcnow().isoformat(), paper_id)
            )
        
        return True
    
    def get_papers_by_status(self, status: str, limit: int = 1000) -> List[Dict]:
        """Get papers by status OR triage_decision field.
        
        This method checks both the 'status' field and 'triage_decision' field
        for backwards compatibility with code that uses either convention.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM papers 
                   WHERE status = ? OR triage_decision = ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (status, status, limit)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def search_papers(
        self,
        query: Optional[str] = None,
        status: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Search papers with filters."""
        conditions = []
        params = []
        
        if query:
            conditions.append("(title LIKE ? OR abstract LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        
        if status:
            conditions.append("status = ?")
            params.append(status)
        
        if year_min:
            conditions.append("year >= ?")
            params.append(year_min)
        
        if year_max:
            conditions.append("year <= ?")
            params.append(year_max)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM papers WHERE {where_clause} ORDER BY year DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    # ================================================================
    # TAXONOMY OPERATIONS
    # ================================================================
    
    def load_taxonomy(self, taxonomy_data: Dict) -> None:
        """Load taxonomy from parsed YAML data."""
        with self.connection() as conn:
            # Load facets
            for facet in taxonomy_data.get('facets', []):
                conn.execute(
                    "INSERT OR REPLACE INTO facets (facet_id, name, description) VALUES (?, ?, ?)",
                    (facet['id'], facet['name'], facet.get('description'))
                )
            
            # Load nodes for each facet tree
            for facet_key in ['environmental_factors', 'outcomes', 'subjects', 'settings', 
                             'methodology', 'modality', 'cross_modal', 'theory', 'evidence_strength']:
                if facet_key in taxonomy_data:
                    self._load_nodes_recursive(
                        conn, 
                        taxonomy_data[facet_key], 
                        facet_key, 
                        parent_id=None
                    )
    
    def _load_nodes_recursive(
        self, 
        conn, 
        nodes: List[Dict], 
        facet_id: str, 
        parent_id: Optional[str]
    ) -> None:
        """Recursively load taxonomy nodes."""
        for node in nodes:
            seeds_json = json.dumps(node.get('seeds', []))
            
            conn.execute(
                """INSERT OR REPLACE INTO facet_nodes 
                   (node_id, facet_id, parent_id, level, name, description, seeds)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    node['id'],
                    facet_id,
                    parent_id,
                    node.get('level', 0),
                    node['name'],
                    node.get('description'),
                    seeds_json
                )
            )
            
            # Recurse into children
            if 'children' in node:
                self._load_nodes_recursive(conn, node['children'], facet_id, node['id'])
    
    def get_taxonomy_nodes(self, facet_id: Optional[str] = None) -> List[Dict]:
        """Get taxonomy nodes, optionally filtered by facet."""
        with self.connection() as conn:
            if facet_id:
                rows = conn.execute(
                    "SELECT * FROM facet_nodes WHERE facet_id = ? ORDER BY level, node_id",
                    (facet_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM facet_nodes ORDER BY facet_id, level, node_id"
                ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def get_node(self, node_id: str) -> Optional[Dict]:
        """Get a single taxonomy node."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM facet_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            
            if row:
                return self._row_to_dict(row)
            return None
    
    # ================================================================
    # CLASSIFICATION OPERATIONS
    # ================================================================
    
    def set_paper_facet_score(
        self, 
        paper_id: str, 
        node_id: str, 
        score: float,
        method: str = 'embedding'
    ) -> None:
        """Set a paper's score for a taxonomy node."""
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO paper_facet_scores 
                   (paper_id, node_id, score, classification_method, classified_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (paper_id, node_id, score, method, datetime.utcnow().isoformat())
            )
    
    def get_paper_facet_scores(self, paper_id: str) -> Dict[str, float]:
        """Get all facet scores for a paper."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT node_id, score FROM paper_facet_scores WHERE paper_id = ?",
                (paper_id,)
            ).fetchall()
            
            return {row['node_id']: row['score'] for row in rows}
    
    def get_papers_by_facet(
        self, 
        node_id: str, 
        min_score: float = 0.5,
        limit: int = 100
    ) -> List[Dict]:
        """Get papers classified to a taxonomy node."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT p.*, pfs.score as facet_score
                   FROM papers p
                   JOIN paper_facet_scores pfs ON p.paper_id = pfs.paper_id
                   WHERE pfs.node_id = ? AND pfs.score >= ?
                   ORDER BY pfs.score DESC
                   LIMIT ?""",
                (node_id, min_score, limit)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    # ================================================================
    # CLAIMS & RULES OPERATIONS
    # ================================================================
    
    def add_claim(self, claim: Dict[str, Any]) -> str:
        """Add a claim from Article Eater."""
        # Serialize JSON fields
        for field in ['environment_factors', 'outcomes', 'mediators', 'moderators', 'evidence_spans']:
            if field in claim and isinstance(claim[field], (list, dict)):
                claim[field] = json.dumps(claim[field])
        
        with self.connection() as conn:
            columns = ', '.join(claim.keys())
            placeholders = ', '.join(['?' for _ in claim])
            
            conn.execute(
                f"INSERT OR REPLACE INTO claims ({columns}) VALUES ({placeholders})",
                list(claim.values())
            )
            
            return claim['claim_id']
    
    def add_rule(self, rule: Dict[str, Any]) -> str:
        """Add a rule from Article Eater."""
        # Serialize JSON fields
        for field in ['lhs', 'rhs', 'population', 'setting', 'boundary_conditions', 'evidence_links']:
            if field in rule and isinstance(rule[field], (list, dict)):
                rule[field] = json.dumps(rule[field])
        
        with self.connection() as conn:
            columns = ', '.join(rule.keys())
            placeholders = ', '.join(['?' for _ in rule])
            
            conn.execute(
                f"INSERT OR REPLACE INTO rules ({columns}) VALUES ({placeholders})",
                list(rule.values())
            )
            
            return rule['rule_id']
    
    def get_claims_by_paper(self, paper_id: str) -> List[Dict]:
        """Get all claims for a paper."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM claims WHERE paper_id = ?", (paper_id,)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def get_rules_by_paper(self, paper_id: str) -> List[Dict]:
        """Get all rules for a paper."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rules WHERE paper_id = ?", (paper_id,)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    # ================================================================
    # CITATION OPERATIONS
    # ================================================================
    
    def add_citation(
        self,
        source_paper_id: str,
        cited_doi: Optional[str] = None,
        cited_title: Optional[str] = None,
        cited_authors: Optional[str] = None,
        cited_year: Optional[int] = None,
        citation_context: Optional[str] = None,
        discovered_via: str = 'pdf_extraction'
    ) -> None:
        """Add a citation link."""
        with self.connection() as conn:
            # Check if cited paper exists
            cited_paper_id = None
            if cited_doi:
                paper = self.get_paper_by_doi(cited_doi)
                if paper:
                    cited_paper_id = paper['paper_id']
            
            conn.execute(
                """INSERT OR IGNORE INTO citations 
                   (source_paper_id, cited_paper_id, cited_doi, cited_title, 
                    cited_authors, cited_year, citation_context, discovered_via)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_paper_id, cited_paper_id, cited_doi, cited_title,
                 cited_authors, cited_year, citation_context, discovered_via)
            )
    
    def get_citations_from(self, paper_id: str) -> List[Dict]:
        """Get papers cited by a paper (forward references)."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM citations WHERE source_paper_id = ?", (paper_id,)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def get_citations_to(self, paper_id: str) -> List[Dict]:
        """Get papers that cite a paper (backward references)."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM citations WHERE cited_paper_id = ?", (paper_id,)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def get_all_citations(self, limit: int = 1000) -> list[dict]:
        """Get recent citations up to a limit."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM citations
                   ORDER BY id DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]

    # ================================================================
    # EXPANSION QUEUE OPERATIONS
    # ================================================================
    
    def add_to_expansion_queue(
        self,
        doi: str,
        title: Optional[str] = None,
        discovered_from: Optional[str] = None,
        priority_score: float = 0.5
    ) -> None:
        """Add a paper to the expansion queue."""
        with self.connection() as conn:
            # Check if already in queue
            existing = conn.execute(
                "SELECT * FROM expansion_queue WHERE doi = ?", (doi,)
            ).fetchone()
            
            if existing:
                # Increment discovery count
                conn.execute(
                    """UPDATE expansion_queue 
                       SET discovery_count = discovery_count + 1,
                           priority_score = MAX(priority_score, ?),
                           updated_at = ?
                       WHERE doi = ?""",
                    (priority_score, datetime.utcnow().isoformat(), doi)
                )
            else:
                conn.execute(
                    """INSERT INTO expansion_queue 
                       (doi, title, discovered_from, priority_score)
                       VALUES (?, ?, ?, ?)""",
                    (doi, title, discovered_from, priority_score)
                )
    
    def get_expansion_queue(self, status: str = 'pending', limit: int = 50) -> List[Dict]:
        """Get papers in the expansion queue."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM expansion_queue 
                   WHERE status = ?
                   ORDER BY priority_score DESC, discovery_count DESC
                   LIMIT ?""",
                (status, limit)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def update_expansion_queue_status(self, doi: str, status: str):
        """Update the status of an expansion queue item."""
        with self.connection() as conn:
            conn.execute(
                "UPDATE expansion_queue SET status = ? WHERE doi = ?",
                (status, doi)
            )
    
    def get_papers_by_triage_status(self, status: str, limit: int = 100) -> List[Dict]:
        """Get papers with a specific triage decision status."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM papers 
                   WHERE triage_decision = ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (status, limit)
            ).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    # ================================================================
    # EXTRACTED TABLES OPERATIONS
    # ================================================================

    def add_extracted_table(self, table_data: Dict[str, Any]) -> str:
        """Add an extracted table from a PDF."""
        with self.connection() as conn:
            # Generate table_id if not provided
            if 'table_id' not in table_data:
                paper_id = table_data['paper_id']
                table_num = table_data.get('table_number', 1)
                table_data['table_id'] = f"{paper_id}#t{table_num:02d}"

            columns = ', '.join(table_data.keys())
            placeholders = ', '.join(['?' for _ in table_data])

            conn.execute(
                f"INSERT OR REPLACE INTO extracted_tables ({columns}) VALUES ({placeholders})",
                list(table_data.values())
            )

            return table_data['table_id']

    def get_tables_by_paper(self, paper_id: str) -> List[Dict]:
        """Get all extracted tables for a paper."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM extracted_tables WHERE paper_id = ? ORDER BY table_number",
                (paper_id,)
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def get_table(self, table_id: str) -> Optional[Dict]:
        """Get a single extracted table by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM extracted_tables WHERE table_id = ?", (table_id,)
            ).fetchone()

            if row:
                return self._row_to_dict(row)
            return None

    def get_tables_with_statistics(self, limit: int = 100) -> List[Dict]:
        """Get tables that contain statistical data."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM extracted_tables
                   WHERE has_statistics = 1
                   ORDER BY extracted_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def get_tables_needing_review(self, limit: int = 100) -> List[Dict]:
        """Get tables flagged for review."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM extracted_tables
                   WHERE needs_review = 1 AND reviewed_at IS NULL
                   ORDER BY extracted_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    # ================================================================
    # STATISTICS
    # ================================================================

    def get_corpus_stats(self) -> Dict[str, Any]:
        """Get summary statistics for the corpus."""
        with self.connection() as conn:
            stats = {}

            # Paper counts by status
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM papers GROUP BY status"
            ).fetchall()
            stats['papers_by_status'] = {row['status']: row['count'] for row in rows}
            stats['total_papers'] = sum(stats['papers_by_status'].values())

            # Claims and rules
            stats['total_claims'] = conn.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
            stats['total_rules'] = conn.execute(
                "SELECT COUNT(*) FROM rules"
            ).fetchone()[0]
            
            # Expansion queue
            stats['expansion_queue_pending'] = conn.execute(
                "SELECT COUNT(*) FROM expansion_queue WHERE status = 'pending'"
            ).fetchone()[0]
            
            # Citation network
            stats['total_citations'] = conn.execute(
                "SELECT COUNT(*) FROM citations"
            ).fetchone()[0]

            # Extracted tables
            try:
                stats['total_tables'] = conn.execute(
                    "SELECT COUNT(*) FROM extracted_tables"
                ).fetchone()[0]
                stats['tables_with_stats'] = conn.execute(
                    "SELECT COUNT(*) FROM extracted_tables WHERE has_statistics = 1"
                ).fetchone()[0]
                stats['tables_needing_review'] = conn.execute(
                    "SELECT COUNT(*) FROM extracted_tables WHERE needs_review = 1 AND reviewed_at IS NULL"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                # Table doesn't exist yet
                stats['total_tables'] = 0
                stats['tables_with_stats'] = 0
                stats['tables_needing_review'] = 0

            return stats
    
    # ================================================================
    # HELPERS
    # ================================================================
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert a database row to a dictionary, parsing JSON fields."""
        d = dict(row)
        
        # Parse JSON fields
        json_fields = ['authors', 'triage_reasons', 'ae_warnings', 'tags',
                       'environment_factors', 'outcomes', 'mediators', 'moderators',
                       'evidence_spans', 'lhs', 'rhs', 'population', 'setting',
                       'boundary_conditions', 'evidence_links', 'seeds']
        
        for field in json_fields:
            if field in d and d[field]:
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        
        return d


# Convenience function
def get_database(db_path: Optional[Path] = None) -> Database:
    """Get a database instance."""
    return Database(db_path)
