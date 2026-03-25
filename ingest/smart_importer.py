# Version: 3.2.2
"""
Article Finder v3.2 - Smart Importer
Intelligently imports references from messy real-world files.

Features:
- Fuzzy column detection (handles 50+ column name variants)
- Automatic citation string parsing
- PDF filename matching
- CrossRef lookup when DOI missing
- Import preview with user confirmation
- Detailed error reporting with fix suggestions
"""

import re
import csv
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Generator
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


@dataclass
class ColumnMapping:
    """Detected column mappings for a file."""
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[str] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    citation: Optional[str] = None  # Full citation string
    url: Optional[str] = None
    
    # Raw column info
    all_columns: List[str] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)
    detection_confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'doi': self.doi,
            'title': self.title,
            'authors': self.authors,
            'year': self.year,
            'venue': self.venue,
            'abstract': self.abstract,
            'citation': self.citation,
            'url': self.url,
            'all_columns': self.all_columns,
            'unmapped_columns': self.unmapped_columns,
            'detection_confidence': self.detection_confidence
        }


class ColumnDetector:
    """
    Detect column types using fuzzy matching and content analysis.
    """
    
    # Column name variants (lowercase for matching)
    COLUMN_VARIANTS = {
        'doi': [
            'doi', 'digital object identifier', 'doi link', 'doi url',
            'article doi', 'paper doi', 'document doi', 'identifier',
            'doi.org', 'dx.doi', 'doi number'
        ],
        'title': [
            'title', 'article title', 'paper title', 'document title',
            'article name', 'paper name', 'work title', 'publication title',
            'study title', 'research title', 'name', 'heading'
        ],
        'authors': [
            'authors', 'author', 'author(s)', 'author names', 'author list',
            'writer', 'writers', 'creator', 'creators', 'by', 'researcher',
            'researchers', 'contributor', 'contributors', 'authorship'
        ],
        'year': [
            'year', 'publication year', 'pub year', 'date', 'publication date',
            'pub date', 'published', 'year published', 'publish year',
            'release year', 'release date', 'issued'
        ],
        'venue': [
            'journal', 'venue', 'publication', 'source', 'journal name',
            'publication venue', 'published in', 'journal title', 'conference',
            'book', 'book title', 'proceedings', 'publisher', 'outlet'
        ],
        'abstract': [
            'abstract', 'summary', 'description', 'synopsis', 'overview',
            'article abstract', 'paper abstract'
        ],
        'citation': [
            'citation', 'reference', 'full reference', 'full citation',
            'reference information', 'bibliographic', 'bibliography',
            'cite', 'ref', 'reference text', 'citation text',
            'formatted reference', 'apa', 'mla', 'chicago'
        ],
        'url': [
            'url', 'link', 'web link', 'article url', 'paper url',
            'web address', 'hyperlink', 'source url', 'access url'
        ]
    }
    
    # DOI pattern for content detection
    DOI_PATTERN = re.compile(r'10\.\d{4,}/[^\s]+')
    
    def detect_columns(self, headers: List[str], sample_rows: List[Dict] = None) -> ColumnMapping:
        """
        Detect column types from headers and optionally sample data.
        
        Args:
            headers: List of column header names
            sample_rows: Optional list of sample data rows for content-based detection
            
        Returns:
            ColumnMapping with detected mappings
        """
        mapping = ColumnMapping(all_columns=headers)
        
        # Phase 1: Header name matching
        header_matches = self._match_headers(headers)
        
        # Phase 2: Content-based detection (if we have sample data)
        content_matches = {}
        if sample_rows:
            content_matches = self._analyze_content(headers, sample_rows)
        
        # Combine matches (content analysis can override header matches)
        combined = {}
        for field_type in self.COLUMN_VARIANTS.keys():
            # Prefer content match if high confidence
            if content_matches.get(field_type, {}).get('confidence', 0) > 0.7:
                combined[field_type] = content_matches[field_type]
            elif header_matches.get(field_type):
                combined[field_type] = header_matches[field_type]
            elif content_matches.get(field_type):
                combined[field_type] = content_matches[field_type]
        
        # Assign to mapping
        for field_type, match_info in combined.items():
            column_name = match_info.get('column')
            if column_name:
                setattr(mapping, field_type, column_name)
        
        # Track unmapped columns
        mapped_cols = {getattr(mapping, f) for f in self.COLUMN_VARIANTS.keys() 
                       if getattr(mapping, f) is not None}
        mapping.unmapped_columns = [h for h in headers if h not in mapped_cols]
        
        # Calculate overall confidence
        mapped_count = sum(1 for f in self.COLUMN_VARIANTS.keys() 
                          if getattr(mapping, f) is not None)
        mapping.detection_confidence = mapped_count / len(self.COLUMN_VARIANTS)
        
        return mapping
    
    def _match_headers(self, headers: List[str]) -> Dict[str, Dict]:
        """Match column headers to field types using fuzzy matching."""
        matches = {}
        
        for header in headers:
            header_lower = header.lower().strip()
            
            for field_type, variants in self.COLUMN_VARIANTS.items():
                # Exact match
                if header_lower in variants:
                    if field_type not in matches or matches[field_type]['confidence'] < 1.0:
                        matches[field_type] = {'column': header, 'confidence': 1.0, 'method': 'exact'}
                    continue
                
                # Fuzzy match
                for variant in variants:
                    ratio = SequenceMatcher(None, header_lower, variant).ratio()
                    if ratio > 0.8:
                        if field_type not in matches or matches[field_type]['confidence'] < ratio:
                            matches[field_type] = {'column': header, 'confidence': ratio, 'method': 'fuzzy'}
                    
                    # Substring match
                    if variant in header_lower or header_lower in variant:
                        score = 0.7
                        if field_type not in matches or matches[field_type]['confidence'] < score:
                            matches[field_type] = {'column': header, 'confidence': score, 'method': 'substring'}
        
        return matches
    
    def _analyze_content(self, headers: List[str], sample_rows: List[Dict]) -> Dict[str, Dict]:
        """Analyze sample content to detect column types."""
        matches = {}
        
        for header in headers:
            values = [row.get(header) for row in sample_rows if row.get(header)]
            if not values:
                continue
            
            # Check for DOI content
            doi_count = sum(1 for v in values if self.DOI_PATTERN.search(str(v)))
            if doi_count > len(values) * 0.5:
                matches['doi'] = {'column': header, 'confidence': 0.9, 'method': 'content_doi'}
            
            # Check for year content (4-digit numbers 1900-2030)
            year_count = sum(1 for v in values 
                           if re.match(r'^(19\d{2}|20[0-2]\d)$', str(v).strip()))
            if year_count > len(values) * 0.7:
                matches['year'] = {'column': header, 'confidence': 0.9, 'method': 'content_year'}
            
            # Check for URL content
            url_count = sum(1 for v in values if str(v).startswith(('http://', 'https://')))
            if url_count > len(values) * 0.5:
                matches['url'] = {'column': header, 'confidence': 0.8, 'method': 'content_url'}
            
            # Check for long text (likely citation or abstract)
            avg_len = sum(len(str(v)) for v in values) / len(values)
            if avg_len > 200:
                # Check if it looks like citations (has years, author patterns)
                citation_indicators = sum(1 for v in values 
                                         if re.search(r'\(\d{4}\)|\d{4}[,.\s]', str(v)))
                if citation_indicators > len(values) * 0.5:
                    matches['citation'] = {'column': header, 'confidence': 0.8, 'method': 'content_citation'}
                elif 'citation' not in matches:
                    matches['abstract'] = {'column': header, 'confidence': 0.6, 'method': 'content_length'}
        
        return matches


class SmartImporter:
    """
    Intelligent importer that handles messy real-world data.
    """
    
    def __init__(self, database=None, doi_resolver=None, citation_parser=None):
        """
        Args:
            database: Database instance for storing papers
            doi_resolver: DOI resolver for metadata lookup
            citation_parser: Citation string parser
        """
        self.db = database
        self.resolver = doi_resolver
        self.citation_parser = citation_parser
        self.column_detector = ColumnDetector()
        
        # Import if not provided
        if self.citation_parser is None:
            try:
                from .citation_parser import CitationParser
                self.citation_parser = CitationParser()
            except ImportError:
                pass
        
        self.stats = self._init_stats()
    
    def _init_stats(self) -> Dict[str, Any]:
        return {
            'total_rows': 0,
            'processed': 0,
            'papers_created': 0,
            'papers_updated': 0,
            'dois_found': 0,
            'dois_resolved': 0,
            'queued': 0,
            'citations_parsed': 0,
            'crossref_lookups': 0,
            'crossref_matches': 0,
            'duplicates': 0,
            'skipped': 0,
            'errors': [],
            'warnings': []
        }
    
    def preview_file(
        self,
        filepath: Path,
        sheet_name: Optional[str] = None,
        max_rows: int = 5
    ) -> Dict[str, Any]:
        """
        Preview a file and detect its structure.
        
        Returns:
            Dictionary with preview info:
            - columns: List of column names
            - column_mapping: Detected column mappings
            - sample_rows: First N rows of data
            - file_info: File metadata
            - suggestions: Suggested actions
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        # Load sample data
        headers, rows = self._load_sample(filepath, sheet_name, max_rows + 5)
        
        # Detect columns
        mapping = self.column_detector.detect_columns(headers, rows[:max_rows])
        
        # Build preview
        preview = {
            'file_info': {
                'name': filepath.name,
                'size': filepath.stat().st_size,
                'type': filepath.suffix.lower(),
                'total_rows': len(rows)
            },
            'columns': headers,
            'column_mapping': mapping.to_dict(),
            'sample_rows': rows[:max_rows],
            'suggestions': []
        }
        
        # Generate suggestions
        if mapping.citation and not mapping.title:
            preview['suggestions'].append({
                'type': 'info',
                'message': f'Found citation column "{mapping.citation}". Will parse citations to extract title/author/year.'
            })
        
        if not mapping.doi and not mapping.citation and not mapping.title:
            preview['suggestions'].append({
                'type': 'warning',
                'message': 'Could not detect DOI, title, or citation columns. Import may fail.',
                'fix': 'Ensure file has at least one of: DOI column, title column, or full citation text.'
            })
        
        if mapping.unmapped_columns:
            preview['suggestions'].append({
                'type': 'info',
                'message': f'Unmapped columns: {", ".join(mapping.unmapped_columns[:5])}'
            })
        
        return preview
    
    def _load_sample(
        self,
        filepath: Path,
        sheet_name: Optional[str],
        max_rows: int
    ) -> Tuple[List[str], List[Dict]]:
        """Load headers and sample rows from file."""
        suffix = filepath.suffix.lower()
        
        if suffix in ['.xlsx', '.xlsm', '.xls']:
            return self._load_excel_sample(filepath, sheet_name, max_rows)
        elif suffix in ['.csv', '.tsv', '.txt']:
            return self._load_csv_sample(filepath, max_rows)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
    
    def _load_excel_sample(
        self,
        filepath: Path,
        sheet_name: Optional[str],
        max_rows: int
    ) -> Tuple[List[str], List[Dict]]:
        """Load sample from Excel file."""
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl required for Excel files. Install: pip install openpyxl")
        
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        
        if sheet_name:
            ws = wb[sheet_name]
        else:
            ws = wb.active
        
        rows_iter = ws.iter_rows(values_only=True)
        
        # Get headers from first row
        headers = [str(cell) if cell else f"Column_{i}" 
                   for i, cell in enumerate(next(rows_iter, []))]
        
        # Get sample rows
        rows = []
        for row_values in rows_iter:
            if len(rows) >= max_rows:
                break
            row = dict(zip(headers, [str(v) if v else "" for v in row_values]))
            rows.append(row)
        
        wb.close()
        return headers, rows
    
    def _load_csv_sample(
        self,
        filepath: Path,
        max_rows: int
    ) -> Tuple[List[str], List[Dict]]:
        """Load sample from CSV file."""
        # Detect delimiter
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            sample = f.read(4096)
            
        # Try to detect dialect
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f, dialect=dialect)
            headers = reader.fieldnames or []
            rows = []
            for row in reader:
                if len(rows) >= max_rows:
                    break
                rows.append(row)
        
        return headers, rows
    
    def import_file(
        self,
        filepath: Path,
        source_name: Optional[str] = None,
        column_mapping: Optional[ColumnMapping] = None,
        sheet_name: Optional[str] = None,
        resolve_dois: bool = True,
        search_crossref: bool = True,
        parse_citations: bool = True,
        queue_only: bool = False,
        limit: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Import papers from a file.
        
        Args:
            filepath: Path to file
            source_name: Source identifier for tracking
            column_mapping: Pre-detected column mapping (if None, auto-detect)
            sheet_name: Excel sheet name (if applicable)
            resolve_dois: Whether to resolve DOIs for metadata
            search_crossref: Whether to search CrossRef when no DOI
            parse_citations: Whether to parse citation strings
            queue_only: Add items to expansion queue instead of corpus
            limit: Maximum rows to import
            progress_callback: Optional callback(current, total) for progress
            
        Returns:
            Import statistics
        """
        filepath = Path(filepath)
        source_name = source_name or filepath.stem
        self.stats = self._init_stats()
        
        logger.info(f"Importing {filepath}")
        
        # Auto-detect columns if not provided
        if column_mapping is None:
            headers, sample = self._load_sample(filepath, sheet_name, 10)
            column_mapping = self.column_detector.detect_columns(headers, sample)
            logger.info(f"Auto-detected columns: DOI={column_mapping.doi}, "
                       f"Title={column_mapping.title}, Citation={column_mapping.citation}")
        
        # Load all rows
        headers, rows = self._load_sample(filepath, sheet_name, limit or 999999)
        self.stats['total_rows'] = len(rows)
        
        # Process each row
        for i, row in enumerate(rows):
            if limit and i >= limit:
                break
            
            try:
                self._process_row(
                    row, column_mapping, source_name,
                    resolve_dois, search_crossref, parse_citations, queue_only
                )
                self.stats['processed'] += 1
            except Exception as e:
                self.stats['errors'].append({
                    'row': i + 2,  # 1-indexed, plus header
                    'error': str(e),
                    'data': {k: str(v)[:50] for k, v in row.items()}
                })
            
            if progress_callback:
                progress_callback(i + 1, len(rows))
        
        logger.info(f"Import complete: {self.stats['papers_created']} created, "
                   f"{self.stats['papers_updated']} updated, "
                   f"{len(self.stats['errors'])} errors")
        
        return self.stats
    
    def _process_row(
        self,
        row: Dict,
        mapping: ColumnMapping,
        source_name: str,
        resolve_dois: bool,
        search_crossref: bool,
        parse_citations: bool,
        queue_only: bool
    ):
        """Process a single row and create/update paper record."""
        paper = {}
        
        # Extract DOI
        doi = None
        if mapping.doi:
            doi = self._extract_doi(row.get(mapping.doi, ''))
        
        # If no DOI column, search all fields
        if not doi:
            for value in row.values():
                doi = self._extract_doi(str(value))
                if doi:
                    break
        
        if doi:
            self.stats['dois_found'] += 1
            paper['doi'] = doi
            paper['paper_id'] = f"doi:{doi}"
            
            # Resolve DOI for full metadata
            if resolve_dois and self.resolver:
                resolved = self._resolve_doi(doi)
                if resolved:
                    paper.update(resolved)
                    self.stats['dois_resolved'] += 1
        
        # Extract direct fields
        if mapping.title and not paper.get('title'):
            paper['title'] = row.get(mapping.title, '').strip()
        
        if mapping.authors and not paper.get('authors'):
            paper['authors'] = self._parse_author_field(row.get(mapping.authors, ''))
        
        if mapping.year and not paper.get('year'):
            year_str = str(row.get(mapping.year, '')).strip()
            if re.match(r'^\d{4}$', year_str):
                paper['year'] = int(year_str)
        
        if mapping.venue and not paper.get('venue'):
            paper['venue'] = row.get(mapping.venue, '').strip()
        
        if mapping.abstract and not paper.get('abstract'):
            paper['abstract'] = row.get(mapping.abstract, '').strip()
        
        if mapping.url and not paper.get('url'):
            paper['url'] = row.get(mapping.url, '').strip()
        
        # Parse citation string if available
        if mapping.citation and parse_citations and self.citation_parser:
            citation_text = row.get(mapping.citation, '').strip()
            if citation_text:
                parsed = self.citation_parser.parse(citation_text)
                self.stats['citations_parsed'] += 1
                
                # Fill in missing fields from citation
                if not paper.get('title') and parsed.title:
                    paper['title'] = parsed.title
                if not paper.get('authors') and parsed.authors:
                    paper['authors'] = parsed.authors
                if not paper.get('year') and parsed.year:
                    paper['year'] = parsed.year
                if not paper.get('venue') and parsed.venue:
                    paper['venue'] = parsed.venue
                if not paper.get('doi') and parsed.doi:
                    paper['doi'] = parsed.doi
                    paper['paper_id'] = f"doi:{parsed.doi}"
                    self.stats['dois_found'] += 1
        
        # CrossRef lookup if still missing DOI
        if search_crossref and not paper.get('doi') and self.resolver:
            if paper.get('title') or paper.get('authors'):
                self.stats['crossref_lookups'] += 1
                crossref_result = self._search_crossref(paper)
                if crossref_result:
                    paper.update(crossref_result)
                    self.stats['crossref_matches'] += 1
        
        # Generate paper_id if still missing
        if not paper.get('paper_id'):
            paper['paper_id'] = self._generate_paper_id(paper, row)
        
        # Skip if no usable data
        if not paper.get('title') and not paper.get('doi'):
            self.stats['skipped'] += 1
            self.stats['warnings'].append({
                'type': 'no_data',
                'message': 'Row has no title or DOI',
                'row_sample': {k: str(v)[:30] for k, v in list(row.items())[:3]}
            })
            return
        
        if queue_only:
            if paper.get('doi'):
                if self.db:
                    self.db.add_to_expansion_queue(
                        paper['doi'],
                        paper.get('title'),
                        source_name,
                        priority_score=0.5
                    )
                self.stats['queued'] += 1
            else:
                self.stats['skipped'] += 1
                self.stats['warnings'].append({
                    'type': 'no_doi_for_queue',
                    'message': 'Queue-only import requires DOI',
                    'row_sample': {k: str(v)[:30] for k, v in list(row.items())[:3]}
                })
            return

        # Add metadata
        paper['source'] = source_name
        paper['status'] = 'candidate'
        paper['retrieved_at'] = datetime.utcnow().isoformat()
        
        # Store in database
        if self.db:
            existing = None
            if paper.get('doi'):
                existing = self.db.get_paper_by_doi(paper['doi'])
            
            if existing:
                # Update existing
                for key, value in paper.items():
                    if value and not existing.get(key):
                        existing[key] = value
                self.db.add_paper(existing)
                self.stats['papers_updated'] += 1
            else:
                self.db.add_paper(paper)
                self.stats['papers_created'] += 1
        else:
            # Just count
            self.stats['papers_created'] += 1
    
    def _extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from text."""
        if not text:
            return None
        
        text = str(text).strip()
        
        # DOI pattern
        pattern = re.compile(r'(?:doi[:\s]*)?(?:https?://(?:dx\.)?doi\.org/)?'
                            r'(10\.\d{4,}/[^\s\]>"\']+)', re.IGNORECASE)
        
        match = pattern.search(text)
        if match:
            doi = match.group(1)
            # Clean trailing punctuation
            doi = doi.rstrip('.,;:')
            return doi.lower()
        
        return None
    
    def _parse_author_field(self, text: str) -> List[str]:
        """Parse an author field into list of author names."""
        if not text:
            return []
        
        # Split by common separators
        text = re.sub(r'\s+and\s+', ';', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*&\s*', ';', text)
        text = re.sub(r'\s*,\s*(?=[A-Z])', ';', text)  # Comma before capital letter
        
        authors = [a.strip() for a in text.split(';') if a.strip()]
        return authors[:20]  # Limit
    
    def _resolve_doi(self, doi: str) -> Optional[Dict]:
        """Resolve DOI to metadata."""
        if not self.resolver:
            return None
        
        try:
            return self.resolver.resolve(doi)
        except Exception as e:
            logger.debug(f"DOI resolution failed for {doi}: {e}")
            return None
    
    def _search_crossref(self, paper: Dict) -> Optional[Dict]:
        """Search CrossRef for paper metadata."""
        if not self.resolver:
            return None
        
        query_parts = []
        
        if paper.get('title'):
            query_parts.append(paper['title'])
        
        if paper.get('authors'):
            if isinstance(paper['authors'], list):
                # Use first author
                query_parts.append(paper['authors'][0])
        
        if not query_parts:
            return None
        
        query = ' '.join(query_parts)[:200]  # Limit query length
        
        try:
            results = self.resolver.search_crossref(query, limit=3)
            if results:
                # Return best match
                return results[0]
        except Exception as e:
            logger.debug(f"CrossRef search failed: {e}")
        
        return None
    
    def _generate_paper_id(self, paper: Dict, row: Dict) -> str:
        """Generate a paper_id when no DOI available."""
        import hashlib
        
        # Use title if available
        if paper.get('title'):
            title_slug = re.sub(r'[^a-z0-9]', '', paper['title'].lower())[:30]
            return f"title:{title_slug}"
        
        # Hash the row content
        content = json.dumps(row, sort_keys=True)
        hash_val = hashlib.md5(content.encode()).hexdigest()[:12]
        return f"hash:{hash_val}"


# Convenience functions
def preview_import(filepath: Path, **kwargs) -> Dict[str, Any]:
    """Preview a file before importing."""
    importer = SmartImporter()
    return importer.preview_file(filepath, **kwargs)


def smart_import(filepath: Path, database=None, **kwargs) -> Dict[str, Any]:
    """Import papers from a file using smart detection."""
    importer = SmartImporter(database=database)
    return importer.import_file(filepath, **kwargs)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Smart file import')
    parser.add_argument('file', type=Path, help='File to import')
    parser.add_argument('--preview', action='store_true', help='Preview only, do not import')
    parser.add_argument('--limit', type=int, help='Maximum rows to import')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    
    importer = SmartImporter()
    
    if args.preview:
        result = importer.preview_file(args.file)
        print(json.dumps(result, indent=2, default=str))
    else:
        result = importer.import_file(args.file, limit=args.limit)
        print(f"\nImport Results:")
        print(f"  Total rows: {result['total_rows']}")
        print(f"  Papers created: {result['papers_created']}")
        print(f"  Papers updated: {result['papers_updated']}")
        print(f"  DOIs found: {result['dois_found']}")
        print(f"  Citations parsed: {result['citations_parsed']}")
        print(f"  Errors: {len(result['errors'])}")
        
        if result['errors'][:5]:
            print(f"\nFirst errors:")
            for err in result['errors'][:5]:
                print(f"  Row {err['row']}: {err['error']}")
