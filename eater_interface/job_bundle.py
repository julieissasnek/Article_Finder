# Version: 3.2.2
"""
Article Finder v3 - Job Bundle Builder
Creates job bundles in the format expected by Article Eater (ae.paper.v1 schema)
"""

import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict


@dataclass
class PaperSource:
    """Source tracking for the paper."""
    finder_run_id: str
    ingest_method: str
    retrieved_at: str


@dataclass
class PaperTriage:
    """Triage information from Article Finder."""
    score: float
    decision: str
    reasons: List[str]
    facet_scores: Dict[str, float]  # Top taxonomy matches


@dataclass
class PaperFiles:
    """File integrity information."""
    pdf_sha256: str
    pdf_bytes: int


@dataclass 
class PaperRights:
    """Rights/license information."""
    license: str = "unknown"
    allowed_storage: bool = True


@dataclass
class PaperNotes:
    """Human annotations."""
    human_notes: str = ""
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class PaperMetadata:
    """
    Complete paper metadata for Article Eater.
    Matches the ae.paper.v1 schema exactly.
    """
    schema: str
    paper_id: str
    doi: Optional[str]
    title: str
    authors: List[Dict[str, Any]]
    year: Optional[int]
    venue: Optional[str]
    publisher: Optional[str]
    url: Optional[str]
    source: PaperSource
    triage: PaperTriage
    files: PaperFiles
    rights: PaperRights
    notes: PaperNotes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = {
            'schema': self.schema,
            'paper_id': self.paper_id,
            'doi': self.doi,
            'title': self.title,
            'authors': self.authors,
            'year': self.year,
            'venue': self.venue,
            'publisher': self.publisher,
            'url': self.url,
            'source': asdict(self.source),
            'triage': {
                'score': self.triage.score,
                'decision': self.triage.decision,
                'reasons': self.triage.reasons,
                'facet_scores': self.triage.facet_scores
            },
            'files': asdict(self.files),
            'rights': asdict(self.rights),
            'notes': {
                'human_notes': self.notes.human_notes,
                'tags': self.notes.tags
            }
        }
        return d


def compute_pdf_hash(pdf_path: Path) -> tuple[str, int]:
    """Compute SHA256 hash and byte count for a PDF file."""
    sha256 = hashlib.sha256()
    with open(pdf_path, 'rb') as f:
        data = f.read()
        sha256.update(data)
    return sha256.hexdigest(), len(data)


def generate_run_id() -> str:
    """Generate a unique run ID for this finder session."""
    return f"af.run.{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}"


class JobBundleBuilder:
    """
    Builds job bundles for Article Eater.
    
    A job bundle is a directory containing:
    - paper.pdf (required)
    - paper.json (required, ae.paper.v1 schema)
    - abstract.txt (optional)
    - fulltext.txt (optional, if pre-extracted)
    - citations.json (optional, if pre-extracted references)
    """
    
    SCHEMA_VERSION = "ae.paper.v1"
    
    def __init__(self, output_base_dir: Path):
        """
        Initialize the job bundle builder.
        
        Args:
            output_base_dir: Base directory for job bundles
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = generate_run_id()
    
    def build_bundle(
        self,
        paper_record: Dict[str, Any],
        pdf_path: Path,
        include_abstract: bool = True,
        include_fulltext: bool = False,
        fulltext_path: Optional[Path] = None,
        include_citations: bool = False,
        citations: Optional[List[Dict]] = None
    ) -> Path:
        """
        Build a complete job bundle for Article Eater.
        
        Args:
            paper_record: Paper record from Article Finder database
            pdf_path: Path to the PDF file
            include_abstract: Whether to include abstract.txt
            include_fulltext: Whether to include fulltext.txt
            fulltext_path: Path to pre-extracted fulltext
            include_citations: Whether to include citations.json
            citations: List of citation records
            
        Returns:
            Path to the created bundle directory
        """
        # Create bundle directory with safe name
        safe_id = self._make_safe_filename(paper_record['paper_id'])
        bundle_name = f"job_{safe_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        bundle_path = self.output_base_dir / bundle_name
        bundle_path.mkdir(parents=True, exist_ok=True)
        
        # Copy PDF
        pdf_dest = bundle_path / "paper.pdf"
        shutil.copy2(pdf_path, pdf_dest)
        
        # Compute file integrity info
        pdf_sha256, pdf_bytes = compute_pdf_hash(pdf_dest)
        
        # Build paper.json metadata
        metadata = self._build_metadata(paper_record, pdf_sha256, pdf_bytes)
        
        # Write paper.json
        paper_json_path = bundle_path / "paper.json"
        with open(paper_json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)
        
        # Optional: abstract.txt
        if include_abstract and paper_record.get('abstract'):
            abstract_path = bundle_path / "abstract.txt"
            with open(abstract_path, 'w', encoding='utf-8') as f:
                f.write(paper_record['abstract'])
        
        # Optional: fulltext.txt
        if include_fulltext and fulltext_path and fulltext_path.exists():
            shutil.copy2(fulltext_path, bundle_path / "fulltext.txt")
        
        # Optional: citations.json
        if include_citations and citations:
            citations_path = bundle_path / "citations.json"
            with open(citations_path, 'w', encoding='utf-8') as f:
                json.dump(citations, f, indent=2, ensure_ascii=False)
        
        return bundle_path
    
    def _build_metadata(
        self, 
        paper_record: Dict[str, Any],
        pdf_sha256: str,
        pdf_bytes: int
    ) -> PaperMetadata:
        """Build the paper.json metadata object."""
        
        # Parse authors if string
        authors = paper_record.get('authors', [])
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except json.JSONDecodeError:
                # Try to parse simple comma-separated format
                authors = [{'name': a.strip()} for a in authors.split(',')]
        
        # Ensure authors is list of dicts
        if authors and isinstance(authors[0], str):
            authors = [{'name': a, 'orcid': None} for a in authors]
        
        # Build triage info
        triage_reasons = paper_record.get('triage_reasons', [])
        if isinstance(triage_reasons, str):
            try:
                triage_reasons = json.loads(triage_reasons)
            except json.JSONDecodeError:
                triage_reasons = [triage_reasons]
        
        # Get facet scores if available
        facet_scores = paper_record.get('facet_scores', {})
        if isinstance(facet_scores, str):
            try:
                facet_scores = json.loads(facet_scores)
            except json.JSONDecodeError:
                facet_scores = {}
        
        # Build tags
        tags = paper_record.get('tags', [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = [t.strip() for t in tags.split(',') if t.strip()]
        
        metadata = PaperMetadata(
            schema=self.SCHEMA_VERSION,
            paper_id=paper_record['paper_id'],
            doi=paper_record.get('doi'),
            title=paper_record['title'],
            authors=authors,
            year=paper_record.get('year'),
            venue=paper_record.get('venue'),
            publisher=paper_record.get('publisher'),
            url=paper_record.get('url'),
            source=PaperSource(
                finder_run_id=self.run_id,
                ingest_method=paper_record.get('ingest_method', 'unknown'),
                retrieved_at=paper_record.get('retrieved_at', datetime.utcnow().isoformat())
            ),
            triage=PaperTriage(
                score=paper_record.get('triage_score', 0.0),
                decision=paper_record.get('triage_decision', 'send_to_eater'),
                reasons=triage_reasons,
                facet_scores=facet_scores
            ),
            files=PaperFiles(
                pdf_sha256=pdf_sha256,
                pdf_bytes=pdf_bytes
            ),
            rights=PaperRights(
                license=paper_record.get('license', 'unknown'),
                allowed_storage=True
            ),
            notes=PaperNotes(
                human_notes=paper_record.get('human_notes', ''),
                tags=tags
            )
        )
        
        return metadata
    
    def _make_safe_filename(self, paper_id: str) -> str:
        """Convert paper_id to a safe filename."""
        # Replace problematic characters
        safe = paper_id.replace(':', '_').replace('/', '_').replace('\\', '_')
        safe = safe.replace('.', '_').replace(' ', '_')
        # Truncate if too long
        if len(safe) > 100:
            safe = safe[:100]
        return safe
    
    def validate_bundle(self, bundle_path: Path) -> Dict[str, Any]:
        """
        Validate a job bundle has all required components.
        
        Returns dict with 'valid' bool and 'errors' list.
        """
        errors = []
        
        # Check required files
        pdf_path = bundle_path / "paper.pdf"
        json_path = bundle_path / "paper.json"
        
        if not pdf_path.exists():
            errors.append("Missing required file: paper.pdf")
        
        if not json_path.exists():
            errors.append("Missing required file: paper.json")
        else:
            # Validate paper.json schema
            try:
                with open(json_path) as f:
                    metadata = json.load(f)
                
                if metadata.get('schema') != self.SCHEMA_VERSION:
                    errors.append(f"Wrong schema version: {metadata.get('schema')}")
                
                required_fields = ['paper_id', 'title', 'source', 'triage', 'files']
                for field in required_fields:
                    if field not in metadata:
                        errors.append(f"Missing required field: {field}")
                
                # Validate file hash matches
                if pdf_path.exists() and 'files' in metadata:
                    actual_hash, actual_bytes = compute_pdf_hash(pdf_path)
                    if metadata['files'].get('pdf_sha256') != actual_hash:
                        errors.append("PDF hash mismatch")
                    if metadata['files'].get('pdf_bytes') != actual_bytes:
                        errors.append("PDF size mismatch")
                        
            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in paper.json: {e}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'bundle_path': str(bundle_path)
        }


class BatchBundleBuilder:
    """Build multiple job bundles for batch processing."""
    
    def __init__(self, output_base_dir: Path):
        self.builder = JobBundleBuilder(output_base_dir)
        self.results = []
    
    def add_paper(
        self,
        paper_record: Dict[str, Any],
        pdf_path: Path,
        **kwargs
    ) -> Optional[Path]:
        """Add a paper to the batch."""
        try:
            bundle_path = self.builder.build_bundle(paper_record, pdf_path, **kwargs)
            validation = self.builder.validate_bundle(bundle_path)
            
            self.results.append({
                'paper_id': paper_record['paper_id'],
                'bundle_path': str(bundle_path),
                'valid': validation['valid'],
                'errors': validation['errors']
            })
            
            if validation['valid']:
                return bundle_path
            else:
                return None
                
        except Exception as e:
            self.results.append({
                'paper_id': paper_record.get('paper_id', 'unknown'),
                'bundle_path': None,
                'valid': False,
                'errors': [str(e)]
            })
            return None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get batch processing summary."""
        valid_count = sum(1 for r in self.results if r['valid'])
        return {
            'total': len(self.results),
            'valid': valid_count,
            'failed': len(self.results) - valid_count,
            'results': self.results
        }
    
    def get_valid_bundles(self) -> List[Path]:
        """Get list of valid bundle paths."""
        return [Path(r['bundle_path']) for r in self.results if r['valid'] and r['bundle_path']]
