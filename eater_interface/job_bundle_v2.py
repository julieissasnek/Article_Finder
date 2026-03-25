# Version: 3.2.2
"""
Article Finder v3 - Job Bundle Builder (Contract-Compliant)
Creates job bundles exactly matching ae.paper.v1 schema

Schema source: AE_AF_Contract_Pack_v1/schemas/ae.paper.v1.schema.json
"""

import json
import hashlib
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import jsonschema


# Load schema for validation (path relative to package)
SCHEMA_DIR = Path(__file__).parent.parent / "schemas"


def load_schema(schema_name: str) -> Dict:
    """Load a JSON schema from the schemas directory."""
    schema_path = SCHEMA_DIR / f"{schema_name}.json"
    if schema_path.exists():
        with open(schema_path) as f:
            return json.load(f)
    return {}


def compute_pdf_hash(pdf_path: Path) -> tuple[str, int]:
    """Compute SHA256 hash and byte count for a PDF file."""
    sha256 = hashlib.sha256()
    with open(pdf_path, 'rb') as f:
        data = f.read()
        sha256.update(data)
    return sha256.hexdigest(), len(data)


def compute_json_hash(data: Dict) -> str:
    """Compute SHA256 hash of JSON data."""
    json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(json_str.encode('utf-8')).hexdigest()


def generate_run_id() -> str:
    """Generate a unique run ID for this finder session."""
    return f"af.run.{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"


@dataclass
class Author:
    """Author record matching ae.paper.v1 schema."""
    name: str
    orcid: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {"name": self.name, "orcid": self.orcid}


@dataclass 
class Source:
    """Source tracking matching ae.paper.v1 schema."""
    finder_run_id: str
    ingest_method: str
    retrieved_at: str  # ISO 8601 datetime string
    
    def to_dict(self) -> Dict:
        return {
            "finder_run_id": self.finder_run_id,
            "ingest_method": self.ingest_method,
            "retrieved_at": self.retrieved_at
        }


@dataclass
class Triage:
    """Triage information matching ae.paper.v1 schema."""
    score: float  # 0.0 to 1.0
    decision: str  # e.g., "send_to_eater", "reject", "review"
    reasons: List[str]
    
    def to_dict(self) -> Dict:
        return {
            "score": self.score,
            "decision": self.decision,
            "reasons": self.reasons
        }


@dataclass
class Files:
    """File integrity info matching ae.paper.v1 schema."""
    pdf_sha256: str  # 64 character hex string
    pdf_bytes: int   # File size in bytes
    
    def to_dict(self) -> Dict:
        return {
            "pdf_sha256": self.pdf_sha256,
            "pdf_bytes": self.pdf_bytes
        }


@dataclass
class Rights:
    """Rights/license info matching ae.paper.v1 schema."""
    license: Optional[str] = "unknown"
    allowed_storage: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "license": self.license,
            "allowed_storage": self.allowed_storage
        }


@dataclass
class Notes:
    """Human annotations matching ae.paper.v1 schema."""
    human_notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "human_notes": self.human_notes,
            "tags": self.tags
        }


@dataclass
class PaperMetadata:
    """
    Complete paper metadata matching ae.paper.v1 schema EXACTLY.
    
    Required fields: schema, paper_id, title, authors, year, source, files
    Optional fields: doi, venue, publisher, url, triage, rights, notes
    """
    # Required
    paper_id: str
    title: str
    authors: List[Author]
    year: int  # REQUIRED per schema (1500-3000)
    source: Source
    files: Files
    
    # Optional
    doi: Optional[str] = None
    venue: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    triage: Optional[Triage] = None
    rights: Optional[Rights] = None
    notes: Optional[Notes] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching ae.paper.v1 schema exactly."""
        d = {
            "schema": "ae.paper.v1",
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "authors": [a.to_dict() for a in self.authors],
            "year": self.year,
            "venue": self.venue,
            "publisher": self.publisher,
            "url": self.url,
            "source": self.source.to_dict(),
            "files": self.files.to_dict(),
        }
        
        # Add optional objects only if present
        if self.triage:
            d["triage"] = self.triage.to_dict()
        else:
            d["triage"] = None
            
        if self.rights:
            d["rights"] = self.rights.to_dict()
        else:
            d["rights"] = None
            
        if self.notes:
            d["notes"] = self.notes.to_dict()
        else:
            d["notes"] = None
        
        return d
    
    def validate(self) -> List[str]:
        """Validate against ae.paper.v1 schema. Returns list of errors."""
        schema = load_schema("ae.paper.v1.schema")
        if not schema:
            return ["Schema file not found"]
        
        errors = []
        try:
            jsonschema.validate(self.to_dict(), schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Validation error: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"Schema error: {e.message}")
        
        return errors


class JobBundleBuilder:
    """
    Builds job bundles for Article Eater matching the contract exactly.
    
    Input bundle structure (AF → AE):
    Required:
      - paper.pdf
      - paper.json (validates ae.paper.v1.schema.json)
    Optional:
      - abstract.txt
      - fulltext.txt
      - citations.json
      - figures/
      - tables/
      - overrides.json
    """
    
    SCHEMA_VERSION = "ae.paper.v1"
    
    def __init__(self, output_base_dir: Path, run_id: Optional[str] = None):
        """
        Initialize the job bundle builder.
        
        Args:
            output_base_dir: Base directory for job bundles
            run_id: Optional run ID (generated if not provided)
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or generate_run_id()
    
    def build_bundle(
        self,
        paper_record: Dict[str, Any],
        pdf_path: Path,
        include_abstract: bool = True,
        include_fulltext: bool = False,
        fulltext_path: Optional[Path] = None,
        include_citations: bool = False,
        citations: Optional[List[Dict]] = None,
        validate: bool = True
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
            validate: Whether to validate against schema
            
        Returns:
            Path to the created bundle directory
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        # Create bundle directory with safe name
        safe_id = self._make_safe_filename(paper_record.get('paper_id', 'unknown'))
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
        metadata_dict = metadata.to_dict()
        
        # Validate if requested
        if validate:
            errors = metadata.validate()
            if errors:
                # Clean up and raise
                shutil.rmtree(bundle_path)
                raise ValueError(f"Schema validation failed: {errors}")
        
        # Write paper.json
        paper_json_path = bundle_path / "paper.json"
        with open(paper_json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata_dict, f, indent=2, ensure_ascii=False)
        
        # Optional: abstract.txt
        if include_abstract and paper_record.get('abstract'):
            abstract_path = bundle_path / "abstract.txt"
            with open(abstract_path, 'w', encoding='utf-8') as f:
                f.write(paper_record['abstract'])
        
        # Optional: fulltext.txt
        if include_fulltext and fulltext_path and Path(fulltext_path).exists():
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
        
        # Parse authors - handles multiple formats
        authors_raw = paper_record.get('authors', [])
        if authors_raw is None:
            authors_raw = []

        if isinstance(authors_raw, str):
            try:
                # Try JSON first
                authors_raw = json.loads(authors_raw)
            except json.JSONDecodeError:
                # Parse as string - handle multiple separators
                authors_raw = self._parse_author_string(authors_raw)

        # Convert to Author objects
        authors = []
        for a in authors_raw:
            if isinstance(a, str):
                authors.append(Author(name=a.strip()))
            elif isinstance(a, dict):
                authors.append(Author(
                    name=a.get('name', 'Unknown'),
                    orcid=a.get('orcid')
                ))

        # Ensure at least one author
        if not authors:
            authors = [Author(name="Unknown")]
        
        # Parse year (REQUIRED - must be integer 1500-3000)
        year = paper_record.get('year')
        if year is None:
            year = datetime.utcnow().year  # Default to current year
        year = int(year)
        if year < 1500 or year > 3000:
            year = datetime.utcnow().year
        
        # Build Source (required)
        source = Source(
            finder_run_id=self.run_id,
            ingest_method=paper_record.get('ingest_method', 'unknown'),
            retrieved_at=paper_record.get('retrieved_at') or datetime.utcnow().isoformat() + 'Z'
        )
        
        # Build Files (required)
        files = Files(
            pdf_sha256=pdf_sha256,
            pdf_bytes=pdf_bytes
        )
        
        # Build optional Triage
        triage = None
        if paper_record.get('triage_score') is not None:
            triage_reasons = paper_record.get('triage_reasons', [])
            if triage_reasons is None:
                triage_reasons = []
            if isinstance(triage_reasons, str):
                try:
                    triage_reasons = json.loads(triage_reasons)
                except json.JSONDecodeError:
                    triage_reasons = [triage_reasons] if triage_reasons else []
            
            triage = Triage(
                score=float(paper_record.get('triage_score', 0.0)),
                decision=paper_record.get('triage_decision', 'send_to_eater'),
                reasons=triage_reasons
            )
        
        # Build optional Rights
        rights = Rights(
            license=paper_record.get('license', 'unknown'),
            allowed_storage=True
        )
        
        # Build optional Notes
        tags = paper_record.get('tags', [])
        if tags is None:
            tags = []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = [t.strip() for t in tags.split(',') if t.strip()]
        
        notes = Notes(
            human_notes=paper_record.get('human_notes'),
            tags=tags
        )
        
        # Generate paper_id if not present
        paper_id = paper_record.get('paper_id')
        if not paper_id:
            if paper_record.get('doi'):
                paper_id = f"doi:{paper_record['doi']}"
            else:
                paper_id = f"sha256:{pdf_sha256[:12]}"
        
        return PaperMetadata(
            paper_id=paper_id,
            doi=paper_record.get('doi'),
            title=paper_record.get('title', 'Untitled'),
            authors=authors,
            year=year,
            venue=paper_record.get('venue'),
            publisher=paper_record.get('publisher'),
            url=paper_record.get('url'),
            source=source,
            triage=triage,
            files=files,
            rights=rights,
            notes=notes
        )
    
    def _parse_author_string(self, author_str: str) -> List[Dict[str, str]]:
        """
        Parse an author string into a list of author dicts.

        Handles multiple formats:
        - Semicolon-separated: "Smith, John; Doe, Jane"
        - "and" separated: "Smith, John and Doe, Jane"
        - Comma-separated (when no semicolons): "John Smith, Jane Doe"

        The tricky part is that author names often contain commas (Last, First),
        so we prefer semicolons as the primary separator.
        """
        if not author_str or not author_str.strip():
            return []

        author_str = author_str.strip()

        # Try semicolon first (most reliable for "Last, First" format)
        if ';' in author_str:
            parts = [p.strip() for p in author_str.split(';') if p.strip()]
            return [{'name': p} for p in parts]

        # Try " and " separator
        if ' and ' in author_str.lower():
            # Split on " and " (case insensitive)
            parts = re.split(r'\s+and\s+', author_str, flags=re.IGNORECASE)
            parts = [p.strip() for p in parts if p.strip()]
            return [{'name': p} for p in parts]

        # Check if it looks like "Last, First" format (has comma followed by space and word)
        # If so, treat the whole thing as a single author
        if re.match(r'^[^,]+,\s+[^,]+$', author_str):
            # Single author in "Last, First" format
            return [{'name': author_str}]

        # Fall back to comma-separated (for "First Last, First Last" format)
        if ',' in author_str:
            parts = [p.strip() for p in author_str.split(',') if p.strip()]
            return [{'name': p} for p in parts]

        # No separators - single author
        return [{'name': author_str}]

    def _make_safe_filename(self, paper_id: str) -> str:
        """Convert paper_id to a safe filename."""
        safe = paper_id.replace(':', '_').replace('/', '_').replace('\\', '_')
        safe = safe.replace('.', '_').replace(' ', '_')
        if len(safe) > 100:
            safe = safe[:100]
        return safe
    
    def validate_bundle(self, bundle_path: Path) -> Dict[str, Any]:
        """
        Validate a job bundle has all required components.
        
        Returns dict with 'valid' bool and 'errors' list.
        """
        bundle_path = Path(bundle_path)
        errors = []
        
        # Check required files
        pdf_path = bundle_path / "paper.pdf"
        json_path = bundle_path / "paper.json"
        
        if not pdf_path.exists():
            errors.append("Missing required file: paper.pdf")
        
        if not json_path.exists():
            errors.append("Missing required file: paper.json")
        else:
            try:
                with open(json_path) as f:
                    metadata = json.load(f)
                
                # Check schema version
                if metadata.get('schema') != self.SCHEMA_VERSION:
                    errors.append(f"Wrong schema version: {metadata.get('schema')}")
                
                # Validate against JSON Schema
                schema = load_schema("ae.paper.v1.schema")
                if schema:
                    try:
                        jsonschema.validate(metadata, schema)
                    except jsonschema.ValidationError as e:
                        errors.append(f"Schema validation: {e.message}")
                
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
    
    def __init__(self, output_base_dir: Path, run_id: Optional[str] = None):
        self.builder = JobBundleBuilder(output_base_dir, run_id)
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
                'paper_id': paper_record.get('paper_id', 'unknown'),
                'bundle_path': str(bundle_path),
                'valid': validation['valid'],
                'errors': validation['errors']
            })
            
            return bundle_path if validation['valid'] else None
                
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
            'run_id': self.builder.run_id,
            'results': self.results
        }
    
    def get_valid_bundles(self) -> List[Path]:
        """Get list of valid bundle paths."""
        return [Path(r['bundle_path']) for r in self.results 
                if r['valid'] and r['bundle_path']]
