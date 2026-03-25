# Version: 3.2.5
"""
Article Finder v3.2.5 - Bibliographer Agent
Systematic taxonomy-driven literature discovery via API searching.

Unlike the BoundedExpander (citation chasing), the Bibliographer:
1. Works PROACTIVELY through taxonomy cells
2. Searches APIs directly for factor×outcome combinations
3. Tracks progress per cell with persistence
4. Identifies gaps in coverage
5. NEW: Searches for theories, neural mechanisms, and mediators
6. NEW: Uses taxonomy seed phrases for precise queries
7. NEW: Integrates with GapAnalyzer for AE-driven search priorities

Cell Types:
- FACTOR_OUTCOME: Traditional factor×outcome combinations
- THEORY: Theory-testing papers (ART, SRT, Biophilia, etc.)
- NEURAL: Neural mechanism evidence (EEG, fMRI markers)
- MECHANISM: Mediator/pathway evidence for IV→DV relationships

Usage:
    python cli/main.py bibliographer status          # Show progress
    python cli/main.py bibliographer run             # Run full sweep
    python cli/main.py bibliographer run --priority HIGH  # Only HIGH cells
    python cli/main.py bibliographer run --cell env.luminous_out.cognitive
    python cli/main.py bibliographer run --cell-type theory  # Only theory cells
    python cli/main.py bibliographer gaps            # Show under-researched cells
    python cli/main.py bibliographer reset --cell X  # Reset a cell for re-search
"""

import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import requests

logger = logging.getLogger(__name__)


class CellType(Enum):
    """Types of search cells."""
    FACTOR_OUTCOME = "factor_outcome"  # Traditional env_factor × outcome
    THEORY = "theory"                   # Theory-testing papers
    NEURAL = "neural"                   # Neural mechanism evidence
    MECHANISM = "mechanism"             # Mediator/pathway evidence


# ============================================================================
# CONFIGURATION
# ============================================================================

# Priority matrix for factor×outcome combinations
# Maps (factor_prefix, outcome_prefix) -> priority
PRIORITY_OVERRIDES = {
    # HIGH priority - core neuroarchitecture questions
    ('env.luminous', 'out.cognitive'): 'HIGH',
    ('env.luminous', 'out.circadian'): 'HIGH',
    ('env.luminous', 'out.affective'): 'HIGH',
    ('env.spatial', 'out.cognitive'): 'HIGH',
    ('env.spatial', 'out.social'): 'HIGH',
    ('env.biophilic', 'out.affective'): 'HIGH',
    ('env.biophilic', 'out.physiological'): 'HIGH',
    ('env.acoustic', 'out.cognitive'): 'HIGH',
    ('env.acoustic', 'out.affective'): 'HIGH',
    ('env.thermal', 'out.cognitive'): 'HIGH',
    ('env.air', 'out.cognitive'): 'HIGH',
    ('env.air', 'out.physiological'): 'HIGH',
    
    # LOW priority - less central combinations
    ('env.visual', 'out.circadian'): 'LOW',
    ('env.materials', 'out.circadian'): 'LOW',
}

# Default queries per cell (can be expanded)
DEFAULT_LIMIT_PER_API = 50


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CellProgress:
    """Progress tracking for a single taxonomy cell."""
    cell_id: str
    factor_id: str
    factor_name: str
    outcome_id: str
    outcome_name: str
    priority: str = 'MEDIUM'

    # Cell type (NEW in v3.2.5)
    cell_type: str = 'factor_outcome'  # factor_outcome, theory, neural, mechanism

    # Taxonomy seed phrases for query generation (NEW in v3.2.5)
    factor_seeds: List[str] = field(default_factory=list)
    outcome_seeds: List[str] = field(default_factory=list)

    # For theory cells
    theory_id: Optional[str] = None
    theory_seeds: List[str] = field(default_factory=list)

    # Search stats
    queries_executed: int = 0
    openalex_found: int = 0
    s2_found: int = 0
    pubmed_found: int = 0
    total_unique: int = 0
    papers_imported: int = 0
    papers_rejected: int = 0

    # State
    status: str = 'pending'  # pending, in_progress, complete, error
    last_searched: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        # Handle list fields that might cause issues
        return d


@dataclass
class BibliographerState:
    """Persistent state for the Bibliographer agent."""
    cells: Dict[str, CellProgress] = field(default_factory=dict)
    total_papers_found: int = 0
    total_papers_imported: int = 0
    total_papers_rejected: int = 0
    runs_completed: int = 0
    last_run: Optional[str] = None
    
    def save(self, path: Path):
        """Save state to JSON file."""
        data = {
            'cells': {k: v.to_dict() for k, v in self.cells.items()},
            'total_papers_found': self.total_papers_found,
            'total_papers_imported': self.total_papers_imported,
            'total_papers_rejected': self.total_papers_rejected,
            'runs_completed': self.runs_completed,
            'last_run': self.last_run
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> 'BibliographerState':
        """Load state from JSON file."""
        if not path.exists():
            return cls()
        
        with open(path) as f:
            data = json.load(f)
        
        state = cls()
        state.total_papers_found = data.get('total_papers_found', 0)
        state.total_papers_imported = data.get('total_papers_imported', 0)
        state.total_papers_rejected = data.get('total_papers_rejected', 0)
        state.runs_completed = data.get('runs_completed', 0)
        state.last_run = data.get('last_run')
        
        for cell_id, cell_data in data.get('cells', {}).items():
            # Handle backward compatibility with old state files
            # Add default values for new fields
            cell_data.setdefault('cell_type', 'factor_outcome')
            cell_data.setdefault('factor_seeds', [])
            cell_data.setdefault('outcome_seeds', [])
            cell_data.setdefault('theory_id', None)
            cell_data.setdefault('theory_seeds', [])
            state.cells[cell_id] = CellProgress(**cell_data)

        return state


# ============================================================================
# API CLIENTS
# ============================================================================

class OpenAlexSearcher:
    """Search OpenAlex API for papers."""
    
    BASE_URL = "https://api.openalex.org"
    
    def __init__(self, email: str, api_key: str | None = None):
        self.email = email
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers['User-Agent'] = f'ArticleFinder/3.2 (mailto:{email})'
    
    def search(self, query: str, limit: int = 50) -> List[Dict]:
        """Search OpenAlex for papers matching query."""
        papers = []
        
        try:
            params = {
                'search': query,
                'per_page': min(limit, 200),
                'mailto': self.email,
                'filter': 'type:article',
                'select': 'id,doi,title,authorships,publication_year,primary_location,abstract_inverted_index,cited_by_count,open_access'
            }
            if self.api_key:
                params['api_key'] = self.api_key
            
            response = self.session.get(
                f"{self.BASE_URL}/works",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('results', []):
                paper = self._normalize(item)
                if paper:
                    papers.append(paper)
                    
        except Exception as e:
            logger.warning(f"OpenAlex search failed for '{query}': {e}")
        
        return papers
    
    def _normalize(self, item: Dict) -> Optional[Dict]:
        """Normalize OpenAlex item to our format."""
        try:
            # Reconstruct abstract from inverted index
            abstract = self._reconstruct_abstract(item.get('abstract_inverted_index'))
            
            # Extract authors
            authors = []
            for auth in item.get('authorships', []):
                name = auth.get('author', {}).get('display_name')
                if name:
                    authors.append(name)
            
            # Extract journal
            journal = None
            loc = item.get('primary_location', {})
            if loc and loc.get('source'):
                journal = loc['source'].get('display_name')
            
            # Extract DOI
            doi = item.get('doi', '')
            if doi:
                doi = doi.replace('https://doi.org/', '')
            
            return {
                'doi': doi or None,
                'openalex_id': item.get('id'),
                'title': item.get('title', ''),
                'authors': authors,
                'year': item.get('publication_year'),
                'journal': journal,
                'abstract': abstract,
                'citation_count': item.get('cited_by_count', 0),
                'is_open_access': item.get('open_access', {}).get('is_oa', False),
                'source': 'openalex'
            }
        except Exception as e:
            logger.debug(f"Failed to normalize OpenAlex item: {e}")
            return None
    
    def _reconstruct_abstract(self, inverted_index: Optional[Dict]) -> Optional[str]:
        """Reconstruct abstract from OpenAlex inverted index."""
        if not inverted_index:
            return None
        try:
            positions = {}
            for word, indices in inverted_index.items():
                for idx in indices:
                    positions[idx] = word
            if positions:
                max_pos = max(positions.keys())
                words = [positions.get(i, '') for i in range(max_pos + 1)]
                return ' '.join(words)
        except:
            pass
        return None


class SemanticScholarSearcher:
    """Search Semantic Scholar API for papers."""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'ArticleFinder/3.2'
        if self.api_key:
            self.session.headers['x-api-key'] = self.api_key
    
    def search(self, query: str, limit: int = 50) -> List[Dict]:
        """Search Semantic Scholar for papers."""
        papers = []
        
        for retry_without_key in (False, True):
            if retry_without_key and 'x-api-key' not in self.session.headers:
                continue
            params = {
                'query': query,
                'limit': min(limit, 100),
                'fields': 'paperId,externalIds,title,authors,year,venue,abstract,citationCount,isOpenAccess,openAccessPdf'
            }
            response = None
            try:
                if retry_without_key:
                    self.session.headers.pop('x-api-key', None)

                response = self.session.get(
                    f"{self.BASE_URL}/paper/search",
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                for item in data.get('data', []):
                    paper = self._normalize(item)
                    if paper:
                        papers.append(paper)
                break
            except requests.HTTPError as e:
                if (
                    response is not None
                    and response.status_code == 403
                    and not retry_without_key
                    and 'x-api-key' in self.session.headers
                ):
                    logger.warning("Semantic Scholar API key rejected; retrying without key")
                    continue
                logger.warning(f"Semantic Scholar search failed for '{query}': {e}")
                break
            except Exception as e:
                logger.warning(f"Semantic Scholar search failed for '{query}': {e}")
                break
        
        return papers
    
    def _normalize(self, item: Dict) -> Optional[Dict]:
        """Normalize S2 item to our format."""
        try:
            external_ids = item.get('externalIds', {}) or {}
            
            authors = []
            for auth in item.get('authors', []):
                if auth.get('name'):
                    authors.append(auth['name'])
            
            pdf_url = None
            if item.get('openAccessPdf'):
                pdf_url = item['openAccessPdf'].get('url')
            
            return {
                'doi': external_ids.get('DOI'),
                's2_id': item.get('paperId'),
                'pmid': external_ids.get('PubMed'),
                'arxiv_id': external_ids.get('ArXiv'),
                'title': item.get('title', ''),
                'authors': authors,
                'year': item.get('year'),
                'journal': item.get('venue'),
                'abstract': item.get('abstract'),
                'citation_count': item.get('citationCount', 0),
                'is_open_access': item.get('isOpenAccess', False),
                'pdf_url': pdf_url,
                'source': 'semantic_scholar'
            }
        except Exception as e:
            logger.debug(f"Failed to normalize S2 item: {e}")
            return None


class PubMedSearcher:
    """Search PubMed via NCBI E-utilities."""
    
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    def __init__(self, email: str, api_key: str = None):
        self.email = email
        self.api_key = api_key or os.environ.get('NCBI_API_KEY')
        self.session = requests.Session()
    
    def search(self, query: str, limit: int = 50) -> List[Dict]:
        """Search PubMed for papers."""
        papers = []
        
        try:
            # Step 1: Search for PMIDs
            search_params = {
                'db': 'pubmed',
                'term': query,
                'retmax': limit,
                'retmode': 'json',
                'email': self.email,
            }
            if self.api_key:
                search_params['api_key'] = self.api_key
            
            resp = self.session.get(
                f"{self.BASE_URL}/esearch.fcgi",
                params=search_params,
                timeout=30
            )
            resp.raise_for_status()
            pmids = resp.json().get('esearchresult', {}).get('idlist', [])
            
            if not pmids:
                return papers
            
            time.sleep(0.4)  # Rate limiting
            
            # Step 2: Fetch details
            fetch_params = {
                'db': 'pubmed',
                'id': ','.join(pmids),
                'retmode': 'xml',
                'email': self.email,
            }
            if self.api_key:
                fetch_params['api_key'] = self.api_key
            
            fetch_resp = self.session.get(
                f"{self.BASE_URL}/efetch.fcgi",
                params=fetch_params,
                timeout=30
            )
            fetch_resp.raise_for_status()
            
            papers = self._parse_xml(fetch_resp.text)
            
        except Exception as e:
            logger.warning(f"PubMed search failed for '{query}': {e}")
        
        return papers
    
    def _parse_xml(self, xml_text: str) -> List[Dict]:
        """Parse PubMed XML response."""
        import xml.etree.ElementTree as ET
        papers = []
        
        try:
            root = ET.fromstring(xml_text)
            
            for article in root.findall('.//PubmedArticle'):
                paper = self._parse_article(article)
                if paper:
                    papers.append(paper)
                    
        except Exception as e:
            logger.warning(f"PubMed XML parse error: {e}")
        
        return papers
    
    def _parse_article(self, article) -> Optional[Dict]:
        """Parse a single PubMed article element."""
        try:
            medline = article.find('.//MedlineCitation')
            if medline is None:
                return None
            
            pmid = medline.findtext('.//PMID', '')
            article_elem = medline.find('.//Article')
            if article_elem is None:
                return None
            
            title = article_elem.findtext('.//ArticleTitle', '')
            abstract = article_elem.findtext('.//Abstract/AbstractText', '')
            
            # Authors
            authors = []
            for auth in article_elem.findall('.//Author'):
                lastname = auth.findtext('LastName', '')
                forename = auth.findtext('ForeName', '')
                if lastname:
                    authors.append(f"{forename} {lastname}".strip())
            
            # Year
            year = None
            pub_date = article_elem.find('.//PubDate')
            if pub_date is not None:
                year_text = pub_date.findtext('Year')
                if year_text:
                    try:
                        year = int(year_text)
                    except:
                        pass
            
            journal = article_elem.findtext('.//Journal/Title', '')
            
            # DOI
            doi = None
            for eid in article.findall('.//ArticleId'):
                if eid.get('IdType') == 'doi':
                    doi = eid.text
                    break
            
            return {
                'pmid': pmid,
                'doi': doi,
                'title': title,
                'authors': authors,
                'year': year,
                'journal': journal,
                'abstract': abstract,
                'source': 'pubmed'
            }
        except Exception as e:
            logger.debug(f"Failed to parse PubMed article: {e}")
            return None


# ============================================================================
# BIBLIOGRAPHER AGENT
# ============================================================================

class Bibliographer:
    """
    Systematic taxonomy-driven literature discovery agent.
    
    Works through factor×outcome cells, searching multiple APIs,
    scoring results, and importing relevant papers.
    """
    
    def __init__(
        self,
        database,
        email: str,
        state_path: Path = None,
        relevance_threshold: float = 0.40
    ):
        """
        Args:
            database: Database instance (from core.database)
            email: Email for API access
            state_path: Path to save/load progress state
            relevance_threshold: Minimum score to import (0-1)
        """
        self.db = database
        self.email = email
        self.threshold = relevance_threshold
        
        self.state_path = state_path or Path('./data/bibliographer_state.json')
        self.state = BibliographerState.load(self.state_path)
        
        # API clients
        from config.loader import get

        self.openalex = OpenAlexSearcher(email, api_key=get('apis.openalex.api_key'))
        self.s2 = SemanticScholarSearcher()
        self.pubmed = PubMedSearcher(email)
        
        # Scorer (lazy loaded)
        self._scorer = None
        
        # Deduplication tracking
        self._seen_signatures: Set[str] = set()
        self._existing_dois: Set[str] = set()
        
    @property
    def scorer(self):
        """Lazy load taxonomy scorer."""
        if self._scorer is None:
            try:
                from triage.scorer import HierarchicalScorer
                self._scorer = HierarchicalScorer(self.db)
            except Exception as e:
                logger.warning(f"Could not load HierarchicalScorer: {e}")
        return self._scorer
    
    def initialize_cells(self, taxonomy_path: Path = None):
        """
        Initialize cells from taxonomy YAML.
        
        Creates CellProgress for each factor×outcome combination.
        """
        taxonomy_path = taxonomy_path or Path('./config/taxonomy.yaml')
        
        if not taxonomy_path.exists():
            logger.error(f"Taxonomy not found: {taxonomy_path}")
            return
        
        import yaml
        with open(taxonomy_path) as f:
            taxonomy = yaml.safe_load(f)
        
        # Extract top-level factors and outcomes
        factors = self._extract_factors(taxonomy.get('environmental_factors', []))
        outcomes = self._extract_outcomes(taxonomy.get('outcomes', []))
        
        logger.info(f"Found {len(factors)} factors, {len(outcomes)} outcomes")
        
        # Create cells for each combination
        for factor in factors:
            for outcome in outcomes:
                cell_id = f"{factor['id']}_{outcome['id']}"
                
                if cell_id not in self.state.cells:
                    # Determine priority
                    priority = self._get_priority(factor['id'], outcome['id'])
                    
                    self.state.cells[cell_id] = CellProgress(
                        cell_id=cell_id,
                        factor_id=factor['id'],
                        factor_name=factor['name'],
                        outcome_id=outcome['id'],
                        outcome_name=outcome['name'],
                        priority=priority
                    )
        
        self.state.save(self.state_path)
        logger.info(f"Initialized {len(self.state.cells)} cells")
    
    def _extract_factors(self, factors_list: List) -> List[Dict]:
        """Extract factor IDs and names from taxonomy."""
        results = []
        for item in factors_list:
            results.append({
                'id': item['id'],
                'name': item['name'],
                'keywords': item.get('seeds', [])
            })
            # Include level-2 children
            for child in item.get('children', []):
                results.append({
                    'id': child['id'],
                    'name': child['name'],
                    'keywords': child.get('seeds', [])
                })
        return results
    
    def _extract_outcomes(self, outcomes_list: List) -> List[Dict]:
        """Extract outcome IDs and names from taxonomy."""
        results = []
        for item in outcomes_list:
            results.append({
                'id': item['id'],
                'name': item['name'],
                'keywords': item.get('seeds', [])
            })
            for child in item.get('children', []):
                results.append({
                    'id': child['id'],
                    'name': child['name'],
                    'keywords': child.get('seeds', [])
                })
        return results
    
    def _get_priority(self, factor_id: str, outcome_id: str) -> str:
        """Determine priority for a factor×outcome cell."""
        # Check exact match first
        for (f_prefix, o_prefix), priority in PRIORITY_OVERRIDES.items():
            if factor_id.startswith(f_prefix) and outcome_id.startswith(o_prefix):
                return priority
        return 'MEDIUM'

    # =========================================================================
    # NEW IN v3.2.5: Extended Cell Initialization
    # =========================================================================

    def initialize_all_cells(self, taxonomy_path: Path = None):
        """
        Initialize ALL cell types from taxonomy.

        Creates cells for:
        - factor×outcome combinations (original)
        - theory testing
        - neural mechanism evidence
        - mechanism/mediator evidence
        """
        taxonomy_path = taxonomy_path or Path('./config/taxonomy.yaml')

        if not taxonomy_path.exists():
            logger.error(f"Taxonomy not found: {taxonomy_path}")
            return

        import yaml
        with open(taxonomy_path) as f:
            taxonomy = yaml.safe_load(f)

        # Store taxonomy for query generation
        self._taxonomy = taxonomy

        # 1. Factor×Outcome cells (original behavior)
        self.initialize_cells(taxonomy_path)

        # 2. Theory cells
        self._initialize_theory_cells(taxonomy)

        # 3. Neural mechanism cells
        self._initialize_neural_cells(taxonomy)

        # 4. Mechanism cells (from existing factor×outcome with evidence)
        self._initialize_mechanism_cells(taxonomy)

        self.state.save(self.state_path)
        logger.info(f"Total cells initialized: {len(self.state.cells)}")

    def _initialize_theory_cells(self, taxonomy: Dict):
        """Initialize cells for each theory in the taxonomy."""
        theories = taxonomy.get('theory', [])
        factors = self._extract_factors(taxonomy.get('environmental_factors', []))

        added = 0
        for theory_group in theories:
            # Include both level-1 and level-2 theories
            all_theories = [theory_group]
            all_theories.extend(theory_group.get('children', []))

            for theory in all_theories:
                theory_id = theory.get('id', '')
                theory_name = theory.get('name', '')
                theory_seeds = theory.get('seeds', [])

                if not theory_id:
                    continue

                cell_id = f"theory:{theory_id}"

                if cell_id not in self.state.cells:
                    self.state.cells[cell_id] = CellProgress(
                        cell_id=cell_id,
                        factor_id=theory_id,
                        factor_name=theory_name,
                        outcome_id='',
                        outcome_name='',
                        priority='HIGH',  # Theory testing is high priority
                        cell_type='theory',
                        theory_id=theory_id,
                        theory_seeds=theory_seeds
                    )
                    added += 1

        logger.info(f"Initialized {added} theory cells")

    def _initialize_neural_cells(self, taxonomy: Dict):
        """Initialize cells for neural outcomes × environmental factors."""
        factors = self._extract_factors(taxonomy.get('environmental_factors', []))
        outcomes = taxonomy.get('outcomes', [])

        # Find neural outcomes (recursively)
        neural_outcomes = []
        for outcome in outcomes:
            if 'neural' in outcome.get('id', ''):
                neural_outcomes.append(outcome)
                neural_outcomes.extend(self._flatten_children(outcome))
            else:
                # Check children
                for child in outcome.get('children', []):
                    if 'neural' in child.get('id', ''):
                        neural_outcomes.append(child)
                        neural_outcomes.extend(self._flatten_children(child))

        added = 0
        for factor in factors:
            for neural in neural_outcomes:
                cell_id = f"neural:{factor['id']}_{neural.get('id', '')}"

                if cell_id not in self.state.cells:
                    self.state.cells[cell_id] = CellProgress(
                        cell_id=cell_id,
                        factor_id=factor['id'],
                        factor_name=factor['name'],
                        outcome_id=neural.get('id', ''),
                        outcome_name=neural.get('name', ''),
                        priority='HIGH',  # Neural evidence is valuable
                        cell_type='neural',
                        factor_seeds=factor.get('keywords', []),
                        outcome_seeds=neural.get('seeds', [])
                    )
                    added += 1

        logger.info(f"Initialized {added} neural cells")

    def _initialize_mechanism_cells(self, taxonomy: Dict):
        """Initialize cells for mechanism/mediator evidence."""
        factors = self._extract_factors(taxonomy.get('environmental_factors', []))
        outcomes = self._extract_outcomes(taxonomy.get('outcomes', []))

        # Focus on high-priority factor×outcome pairs that need mechanism evidence
        added = 0
        for (f_prefix, o_prefix), priority in PRIORITY_OVERRIDES.items():
            if priority == 'HIGH':
                # Find matching factors and outcomes
                for factor in factors:
                    if factor['id'].startswith(f_prefix):
                        for outcome in outcomes:
                            if outcome['id'].startswith(o_prefix):
                                cell_id = f"mechanism:{factor['id']}_{outcome['id']}"

                                if cell_id not in self.state.cells:
                                    self.state.cells[cell_id] = CellProgress(
                                        cell_id=cell_id,
                                        factor_id=factor['id'],
                                        factor_name=factor['name'],
                                        outcome_id=outcome['id'],
                                        outcome_name=outcome['name'],
                                        priority='MEDIUM',
                                        cell_type='mechanism',
                                        factor_seeds=factor.get('keywords', []),
                                        outcome_seeds=outcome.get('keywords', [])
                                    )
                                    added += 1

        logger.info(f"Initialized {added} mechanism cells")

    def _flatten_children(self, node: Dict) -> List[Dict]:
        """Recursively flatten children of a taxonomy node."""
        result = []
        for child in node.get('children', []):
            result.append(child)
            result.extend(self._flatten_children(child))
        return result

    def initialize_from_gaps(self, gap_analyzer=None):
        """
        Initialize cells from GapAnalyzer priority queries.

        This enables AE-driven search: AE tells us what's missing,
        we create targeted search cells to fill those gaps.
        """
        if gap_analyzer is None:
            try:
                from search.gap_analyzer import GapAnalyzer
                gap_analyzer = GapAnalyzer(self.db)
            except ImportError:
                logger.warning("GapAnalyzer not available")
                return

        gaps = gap_analyzer.get_all_gaps(limit=50)

        added = 0
        for gap in gaps:
            cell_id = f"gap:{gap.gap_id}"

            if cell_id not in self.state.cells:
                # Create cell from gap
                self.state.cells[cell_id] = CellProgress(
                    cell_id=cell_id,
                    factor_id=gap.taxonomy_cells[0] if gap.taxonomy_cells else '',
                    factor_name=gap.description,
                    outcome_id=gap.taxonomy_cells[1] if len(gap.taxonomy_cells) > 1 else '',
                    outcome_name='',
                    priority='HIGH' if gap.priority > 0.7 else 'MEDIUM',
                    cell_type=gap.gap_type.value,
                    factor_seeds=gap.suggested_queries[:3],
                    outcome_seeds=gap.suggested_queries[3:6] if len(gap.suggested_queries) > 3 else []
                )
                added += 1

        self.state.save(self.state_path)
        logger.info(f"Initialized {added} gap-driven cells")

    def run(
        self,
        priority_filter: Optional[str] = None,
        cell_filter: Optional[str] = None,
        cell_type_filter: Optional[str] = None,
        limit_per_api: int = DEFAULT_LIMIT_PER_API,
        skip_complete: bool = True
    ) -> Dict[str, Any]:
        """
        Run the bibliographer agent.

        Args:
            priority_filter: Only process cells with this priority
            cell_filter: Only process specific cell ID
            cell_type_filter: Only process cells of this type (theory, neural, mechanism, factor_outcome)
            limit_per_api: Max papers per API per cell
            skip_complete: Skip already-complete cells

        Returns:
            Run statistics
        """
        self.state.last_run = datetime.now().isoformat()

        # Pre-load existing DOIs for deduplication
        self._load_existing_dois()

        # Select cells to process
        cells = self._select_cells(priority_filter, cell_filter, skip_complete, cell_type_filter)
        
        if not cells:
            logger.info("No cells to process")
            return {'cells_processed': 0}
        
        logger.info(f"Processing {len(cells)} cells")
        
        total_found = 0
        total_imported = 0
        total_rejected = 0
        
        for cell in cells:
            try:
                found, imported, rejected = self._process_cell(cell, limit_per_api)
                total_found += found
                total_imported += imported
                total_rejected += rejected
                
                cell.status = 'complete'
                cell.last_searched = datetime.now().isoformat()
                
                # Save after each cell
                self.state.save(self.state_path)
                
                # Rate limiting
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error processing cell {cell.cell_id}: {e}")
                cell.status = 'error'
                cell.error_message = str(e)
                self.state.save(self.state_path)
        
        self.state.total_papers_found += total_found
        self.state.total_papers_imported += total_imported
        self.state.total_papers_rejected += total_rejected
        self.state.runs_completed += 1
        self.state.save(self.state_path)
        
        return {
            'cells_processed': len(cells),
            'papers_found': total_found,
            'papers_imported': total_imported,
            'papers_rejected': total_rejected
        }
    
    def _load_existing_dois(self):
        """Pre-load DOIs from database for deduplication."""
        try:
            # This depends on your database API
            papers = self.db.search_papers("", limit=10000)
            for paper in papers:
                if paper.get('doi'):
                    self._existing_dois.add(paper['doi'].lower())
        except Exception as e:
            logger.warning(f"Could not pre-load DOIs: {e}")
    
    def _select_cells(
        self,
        priority_filter: Optional[str],
        cell_filter: Optional[str],
        skip_complete: bool,
        cell_type_filter: Optional[str] = None
    ) -> List[CellProgress]:
        """Select cells to process based on filters."""
        cells = []

        for cell in self.state.cells.values():
            if cell_filter and cell.cell_id != cell_filter:
                continue
            if priority_filter and cell.priority != priority_filter:
                continue
            if skip_complete and cell.status == 'complete':
                continue
            if cell_type_filter and cell.cell_type != cell_type_filter:
                continue
            cells.append(cell)

        # Sort by priority, then by cell type (theory and neural first)
        type_order = {'theory': 0, 'neural': 1, 'mechanism': 2, 'factor_outcome': 3}
        priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        cells.sort(key=lambda c: (
            priority_order.get(c.priority, 1),
            type_order.get(c.cell_type, 3)
        ))

        return cells
    
    def _process_cell(
        self,
        cell: CellProgress,
        limit: int
    ) -> Tuple[int, int, int]:
        """
        Process a single taxonomy cell.
        
        Returns:
            (papers_found, papers_imported, papers_rejected)
        """
        logger.info(f"Processing: {cell.factor_name} × {cell.outcome_name}")
        cell.status = 'in_progress'
        
        # Generate queries
        queries = self._generate_queries(cell)
        
        all_papers = []
        
        # Search each API
        for query in queries[:3]:  # Limit queries per cell
            logger.debug(f"  Query: {query}")
            
            # OpenAlex
            try:
                oa_papers = self.openalex.search(query, limit=limit)
                all_papers.extend(oa_papers)
                cell.openalex_found += len(oa_papers)
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"  OpenAlex error: {e}")
            
            # Semantic Scholar
            try:
                s2_papers = self.s2.search(query, limit=limit)
                all_papers.extend(s2_papers)
                cell.s2_found += len(s2_papers)
                time.sleep(1)  # S2 is rate-limited
            except Exception as e:
                logger.debug(f"  S2 error: {e}")
            
            # PubMed
            try:
                pm_papers = self.pubmed.search(query, limit=limit)
                all_papers.extend(pm_papers)
                cell.pubmed_found += len(pm_papers)
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"  PubMed error: {e}")
        
        cell.queries_executed = len(queries[:3]) * 3
        
        # Deduplicate
        unique_papers = self._deduplicate(all_papers)
        cell.total_unique = len(unique_papers)
        
        logger.info(f"  Found {len(all_papers)}, {len(unique_papers)} unique")
        
        # Score and import
        imported = 0
        rejected = 0
        
        for paper in unique_papers:
            result = self._evaluate_and_import(paper, cell.cell_id)
            if result == 'imported':
                imported += 1
            elif result == 'rejected':
                rejected += 1
        
        cell.papers_imported = imported
        cell.papers_rejected = rejected
        
        logger.info(f"  Imported {imported}, rejected {rejected}")
        
        return len(unique_papers), imported, rejected
    
    def _generate_queries(self, cell: CellProgress) -> List[str]:
        """
        Generate search queries for a cell.

        v3.2.5: Uses taxonomy seed phrases for precise queries.
        Handles different cell types with appropriate strategies.
        """
        cell_type = cell.cell_type

        if cell_type == 'theory':
            return self._generate_theory_queries(cell)
        elif cell_type == 'neural':
            return self._generate_neural_queries(cell)
        elif cell_type == 'mechanism':
            return self._generate_mechanism_queries(cell)
        else:
            return self._generate_factor_outcome_queries(cell)

    def _generate_factor_outcome_queries(self, cell: CellProgress) -> List[str]:
        """Generate queries for factor×outcome cells using seed phrases."""
        queries = []

        # Use seed phrases if available (much more precise)
        factor_seeds = cell.factor_seeds or []
        outcome_seeds = cell.outcome_seeds or []

        if factor_seeds and outcome_seeds:
            # Cross-product of specific seeds
            for f_seed in factor_seeds[:3]:
                for o_seed in outcome_seeds[:2]:
                    queries.append(f'"{f_seed}" "{o_seed}"')

            # Add context-qualified queries
            if factor_seeds:
                queries.append(f'"{factor_seeds[0]}" building occupants effect')
                queries.append(f'"{factor_seeds[0]}" indoor environment study')

        # Fallback to name-based queries (original behavior)
        if not queries or len(queries) < 3:
            factor = cell.factor_name.lower().replace('_', ' ')
            outcome = cell.outcome_name.lower().replace('_', ' ')

            queries.append(f'"{factor}" "{outcome}" effect')
            queries.append(f'"{factor}" "{outcome}" building')
            queries.append(f'indoor "{factor}" "{outcome}"')

        return queries[:8]

    def _generate_theory_queries(self, cell: CellProgress) -> List[str]:
        """Generate queries for theory-testing papers."""
        queries = []
        theory_seeds = cell.theory_seeds or []
        theory_name = cell.factor_name  # Theory name stored in factor_name

        # DOMAIN CONTEXT - all queries should include domain terms
        domain_terms = ['nature', 'environment', 'restorative', 'architecture', 'building']

        # Use theory seeds - but only if they're long enough to be specific
        for seed in theory_seeds[:3]:
            # Skip short seeds (like "ART") that match too many things
            if len(seed) > 5:
                queries.append(f'"{seed}" nature environment')
                queries.append(f'"{seed}" restorative building')
            else:
                # For short seeds, combine with full theory name
                if theory_name:
                    queries.append(f'"{seed}" "{theory_name}"')

        # Theory name queries - always most reliable
        if theory_name:
            queries.append(f'"{theory_name}" empirical study nature')
            queries.append(f'"{theory_name}" environment experiment')
            queries.append(f'"{theory_name}" restorative architecture')
            queries.append(f'"{theory_name}" built environment')

        # If still need more queries, add domain-specific versions
        if len(queries) < 6:
            queries.append(f'{theory_name} nature restoration cognitive')
            queries.append(f'{theory_name} green space attention')

        return queries[:8]

    def _generate_neural_queries(self, cell: CellProgress) -> List[str]:
        """Generate queries for neural mechanism evidence."""
        queries = []
        factor_seeds = cell.factor_seeds or []
        outcome_seeds = cell.outcome_seeds or []
        neural_id = cell.outcome_id or ''

        # Combine factor with neural terms
        if factor_seeds:
            for f_seed in factor_seeds[:2]:
                if outcome_seeds:
                    queries.append(f'"{f_seed}" "{outcome_seeds[0]}"')
                queries.append(f'"{f_seed}" brain neural')
                queries.append(f'"{f_seed}" neuroimaging')

        # Add specific neural modality queries
        if 'eeg' in neural_id.lower():
            factor_name = cell.factor_name.lower().replace('_', ' ')
            queries.append(f'"{factor_name}" EEG study')
            queries.append(f'"{factor_name}" alpha waves')
            queries.append(f'"{factor_name}" brain electrical activity')
        elif 'fmri' in neural_id.lower():
            factor_name = cell.factor_name.lower().replace('_', ' ')
            queries.append(f'"{factor_name}" fMRI neuroimaging')
            queries.append(f'"{factor_name}" brain activation')

        return queries[:8]

    def _generate_mechanism_queries(self, cell: CellProgress) -> List[str]:
        """Generate queries for mechanism/mediator evidence."""
        queries = []
        factor_seeds = cell.factor_seeds or []
        outcome_seeds = cell.outcome_seeds or []

        if factor_seeds and outcome_seeds:
            f_seed = factor_seeds[0]
            o_seed = outcome_seeds[0]

            queries.append(f'"{f_seed}" mechanism "{o_seed}"')
            queries.append(f'"{f_seed}" mediates "{o_seed}"')
            queries.append(f'"{f_seed}" pathway "{o_seed}"')
            queries.append(f'how "{f_seed}" affects "{o_seed}"')
            queries.append(f'"{f_seed}" "{o_seed}" mediation analysis')

        # Fallback
        if not queries:
            factor = cell.factor_name.lower().replace('_', ' ')
            outcome = cell.outcome_name.lower().replace('_', ' ')
            queries.append(f'"{factor}" mechanism "{outcome}"')
            queries.append(f'"{factor}" mediator "{outcome}"')

        return queries[:6]
    
    def _deduplicate(self, papers: List[Dict]) -> List[Dict]:
        """Deduplicate papers by DOI or title signature."""
        unique = {}
        
        for paper in papers:
            sig = self._signature(paper)
            
            # Skip if we've seen this in this session
            if sig in self._seen_signatures:
                continue
            
            # Skip if DOI exists in database
            doi = paper.get('doi')
            if doi and doi.lower() in self._existing_dois:
                self._seen_signatures.add(sig)
                continue
            
            if sig not in unique:
                unique[sig] = paper
            else:
                # Merge: prefer record with more data
                existing = unique[sig]
                if paper.get('abstract') and not existing.get('abstract'):
                    existing['abstract'] = paper['abstract']
                if paper.get('doi') and not existing.get('doi'):
                    existing['doi'] = paper['doi']
        
        return list(unique.values())
    
    def _signature(self, paper: Dict) -> str:
        """Generate deduplication signature."""
        if paper.get('doi'):
            return f"doi:{paper['doi'].lower()}"
        
        title = paper.get('title', '')
        title_norm = ''.join(c for c in title.lower() if c.isalnum())[:60]
        year = paper.get('year', 'unknown')
        return f"title:{title_norm}:{year}"
    
    def _evaluate_and_import(self, paper: Dict, cell_id: str) -> str:
        """
        Evaluate paper relevance and import if above threshold.
        
        Returns: 'imported', 'rejected', or 'duplicate'
        """
        sig = self._signature(paper)
        
        if sig in self._seen_signatures:
            return 'duplicate'
        
        self._seen_signatures.add(sig)
        
        # Score against taxonomy
        score = 0.0  # Default if scorer unavailable
        triage_decision = 'pending'
        defer_reason = None  # Track if we need to defer instead of reject

        if self.scorer:
            try:
                result = self.scorer.score_paper(paper)
                score = result.get('triage_score', 0.0)
                triage_decision = result.get('triage_decision', 'pending')

                # Reject if scorer says reject
                if triage_decision == 'reject':
                    return 'rejected'
            except ValueError as e:
                logger.warning(f"Scorer not initialized (no centroids?): {e}")
                defer_reason = 'scorer_not_initialized'
            except Exception as e:
                logger.warning(f"Scoring failed: {e}")
                defer_reason = 'scoring_error'
        else:
            logger.warning("Scorer unavailable - deferring paper for later scoring")
            defer_reason = 'scorer_unavailable'

        # If scorer failed, import as pending_scorer for later processing
        if defer_reason:
            try:
                paper_data = {
                    'title': paper.get('title'),
                    'authors': paper.get('authors', []),
                    'year': paper.get('year'),
                    'venue': paper.get('journal') or paper.get('venue'),
                    'doi': paper.get('doi'),
                    'abstract': paper.get('abstract'),
                    'url': paper.get('pdf_url') or paper.get('url'),
                    'source': f"bibliographer:{cell_id}",
                    'ingest_method': 'bibliographer',
                    'status': 'pending_scorer',
                    'triage_score': None,
                    'triage_decision': 'pending'
                }
                paper_data = {k: v for k, v in paper_data.items() if v is not None}
                self.db.add_paper(paper_data)

                if paper.get('doi'):
                    self._existing_dois.add(paper['doi'].lower())

                return 'deferred'
            except Exception as e:
                logger.debug(f"Deferred import failed: {e}")
                return 'rejected'

        if score < self.threshold:
            return 'rejected'
        
        # Import to database
        # v3.2.3 schema: paper_id, doi, title, authors, year, venue, abstract, url
        #                source, ingest_method, status, triage_score, triage_decision
        try:
            paper_data = {
                'title': paper.get('title'),
                'authors': paper.get('authors', []),
                'year': paper.get('year'),
                'venue': paper.get('journal') or paper.get('venue'),  # Schema uses 'venue' not 'journal'
                'doi': paper.get('doi'),
                'abstract': paper.get('abstract'),
                'url': paper.get('pdf_url') or paper.get('url'),
                'source': f"bibliographer:{cell_id}",
                'ingest_method': 'bibliographer',
                'status': 'candidate',
                'triage_score': score,
                'triage_decision': triage_decision
            }
            
            # Remove None values to avoid SQL issues
            paper_data = {k: v for k, v in paper_data.items() if v is not None}
            
            self.db.add_paper(paper_data)
            
            if paper.get('doi'):
                self._existing_dois.add(paper['doi'].lower())
            
            return 'imported'
            
        except Exception as e:
            logger.debug(f"Import failed: {e}")
            return 'rejected'
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bibliographer status."""
        total = len(self.state.cells)
        complete = sum(1 for c in self.state.cells.values() if c.status == 'complete')
        pending = sum(1 for c in self.state.cells.values() if c.status == 'pending')
        errors = sum(1 for c in self.state.cells.values() if c.status == 'error')
        
        by_priority = {}
        for priority in ['HIGH', 'MEDIUM', 'LOW']:
            cells = [c for c in self.state.cells.values() if c.priority == priority]
            by_priority[priority] = {
                'total': len(cells),
                'complete': sum(1 for c in cells if c.status == 'complete'),
                'papers_imported': sum(c.papers_imported for c in cells)
            }
        
        return {
            'total_cells': total,
            'complete': complete,
            'pending': pending,
            'in_progress': sum(1 for c in self.state.cells.values() if c.status == 'in_progress'),
            'errors': errors,
            'by_priority': by_priority,
            'total_papers_found': self.state.total_papers_found,
            'total_papers_imported': self.state.total_papers_imported,
            'total_papers_rejected': self.state.total_papers_rejected,
            'runs_completed': self.state.runs_completed,
            'last_run': self.state.last_run
        }
    
    def get_gaps(self, min_papers: int = 5) -> List[Dict]:
        """Find cells with fewer than min_papers."""
        gaps = []
        
        for cell in self.state.cells.values():
            if cell.papers_imported < min_papers:
                gaps.append({
                    'cell_id': cell.cell_id,
                    'factor': cell.factor_name,
                    'outcome': cell.outcome_name,
                    'priority': cell.priority,
                    'papers': cell.papers_imported,
                    'status': cell.status
                })
        
        # Sort by priority then papers
        priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        gaps.sort(key=lambda g: (priority_order.get(g['priority'], 1), g['papers']))
        
        return gaps
    
    def reset_cell(self, cell_id: str):
        """Reset a cell to allow re-processing."""
        if cell_id in self.state.cells:
            cell = self.state.cells[cell_id]
            cell.status = 'pending'
            cell.queries_executed = 0
            cell.openalex_found = 0
            cell.s2_found = 0
            cell.pubmed_found = 0
            cell.total_unique = 0
            cell.papers_imported = 0
            cell.papers_rejected = 0
            cell.error_message = None
            self.state.save(self.state_path)
            logger.info(f"Reset cell: {cell_id}")


# ============================================================================
# CLI INTEGRATION
# ============================================================================

def cmd_bibliographer(args, database):
    """CLI command handler for bibliographer."""
    email = args.email or os.environ.get('OPENALEX_EMAIL', 'research@ucsd.edu')
    
    biblio = Bibliographer(
        database=database,
        email=email,
        relevance_threshold=getattr(args, 'threshold', 0.35)
    )
    
    subcommand = getattr(args, 'subcmd', 'status')
    
    if subcommand == 'init':
        biblio.initialize_cells()
        print(f"Initialized {len(biblio.state.cells)} cells")
        
    elif subcommand == 'status':
        status = biblio.get_status()
        print("\n=== Bibliographer Status ===")
        print(f"Cells: {status['complete']}/{status['total_cells']} complete")
        print(f"  Pending: {status['pending']}")
        print(f"  Errors: {status['errors']}")
        print(f"\nBy priority:")
        for p, data in status['by_priority'].items():
            print(f"  {p}: {data['complete']}/{data['total']} cells, {data['papers_imported']} papers")
        print(f"\nTotals:")
        print(f"  Papers found: {status['total_papers_found']}")
        print(f"  Papers imported: {status['total_papers_imported']}")
        print(f"  Papers rejected: {status['total_papers_rejected']}")
        print(f"  Runs completed: {status['runs_completed']}")
        print(f"  Last run: {status['last_run']}")
        
    elif subcommand == 'run':
        if not biblio.state.cells:
            print("No cells initialized. Run 'bibliographer init' first.")
            return 1
            
        results = biblio.run(
            priority_filter=getattr(args, 'priority', None),
            cell_filter=getattr(args, 'cell', None),
            limit_per_api=getattr(args, 'limit', 50)
        )
        print(f"\n=== Run Complete ===")
        print(f"Cells processed: {results['cells_processed']}")
        print(f"Papers found: {results['papers_found']}")
        print(f"Papers imported: {results['papers_imported']}")
        print(f"Papers rejected: {results['papers_rejected']}")
        
    elif subcommand == 'gaps':
        min_papers = getattr(args, 'min_papers', 5)
        gaps = biblio.get_gaps(min_papers)
        
        print(f"\n=== Gaps (cells with < {min_papers} papers) ===")
        if not gaps:
            print("No gaps found!")
        else:
            current_priority = None
            for gap in gaps:
                if gap['priority'] != current_priority:
                    current_priority = gap['priority']
                    print(f"\n{current_priority} Priority:")
                print(f"  {gap['cell_id']:40} = {gap['papers']} papers ({gap['status']})")
                
    elif subcommand == 'reset':
        cell_id = getattr(args, 'cell', None)
        if cell_id:
            biblio.reset_cell(cell_id)
            print(f"Reset cell: {cell_id}")
        else:
            print("Specify --cell to reset")
    
    return 0
