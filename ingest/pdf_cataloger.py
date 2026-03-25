# Version: 3.2.4
"""
Article Finder v3.2.3 - PDF Cataloger
Creates paper records from PDF files by parsing filenames and optionally extracting metadata.

v3.2.3: Added PDF text extraction and intelligent verification against CrossRef data
        to prevent abstract/title mismatches.

Handles filename patterns:
- Wastiels,_L.,_..._&_He.pdf (author-based)
- 2020_Smith_Daylight_Effects.pdf (year-author-title)
- 10.1016_j.jenvp.2020.01.001.pdf (DOI-based)
- Some Paper Title Here.pdf (title-based)
"""

import re
import logging
import hashlib
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any, Generator, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: Path, max_pages: int = 2, max_chars: int = 5000) -> Optional[str]:
    """
    Extract text from a PDF file using pdftotext.

    Args:
        pdf_path: Path to PDF file
        max_pages: Maximum pages to extract (default: 2, usually enough for title/abstract)
        max_chars: Maximum characters to return

    Returns:
        Extracted text or None if extraction fails
    """
    try:
        # Use pdftotext (from poppler-utils)
        result = subprocess.run(
            ['pdftotext', '-l', str(max_pages), str(pdf_path), '-'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout:
            text = result.stdout[:max_chars]
            return text
    except FileNotFoundError:
        logger.debug("pdftotext not installed, trying PyPDF2")
    except subprocess.TimeoutExpired:
        logger.warning(f"PDF text extraction timed out: {pdf_path}")
    except Exception as e:
        logger.debug(f"pdftotext failed: {e}")

    # Fallback to PyPDF2 if available
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text_parts = []
        for i, page in enumerate(reader.pages[:max_pages]):
            text_parts.append(page.extract_text() or '')
        text = '\n'.join(text_parts)[:max_chars]
        return text if text.strip() else None
    except ImportError:
        logger.debug("PyPDF2 not available")
    except Exception as e:
        logger.debug(f"PyPDF2 extraction failed: {e}")

    return None


def verify_text_matches_title(pdf_text: str, title: str, threshold: float = 0.5) -> Tuple[bool, float]:
    """
    Verify that extracted PDF text is about the same topic as the title.

    Args:
        pdf_text: Text extracted from PDF
        title: Expected title/topic
        threshold: Minimum score to consider a match (0-1)

    Returns:
        Tuple of (matches: bool, score: float)
    """
    if not pdf_text or not title:
        return False, 0.0

    # Extract significant keywords from title
    stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with',
                  'by', 'from', 'at', 'is', 'are', 'was', 'were', 'be', 'been',
                  'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                  'would', 'could', 'should', 'may', 'might', 'must', 'shall'}

    title_words = set(
        w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', title)
        if w.lower() not in stop_words
    )

    if not title_words:
        return True, 1.0  # Can't verify, assume OK

    pdf_text_lower = pdf_text.lower()

    # Check how many title keywords appear in PDF text
    found = sum(1 for w in title_words if w in pdf_text_lower)
    score = found / len(title_words)

    return score >= threshold, score


def verify_abstract_matches_pdf(abstract: str, pdf_text: str, threshold: float = 0.4) -> Tuple[bool, float]:
    """
    Verify that a CrossRef abstract matches the actual PDF content.

    This catches cases where CrossRef returns the wrong paper's abstract.

    Args:
        abstract: Abstract from CrossRef
        pdf_text: Text extracted from PDF
        threshold: Minimum score to consider a match

    Returns:
        Tuple of (matches: bool, score: float)
    """
    if not abstract or not pdf_text:
        return False, 0.0

    # Extract significant words from abstract (longer words, not stopwords)
    stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with',
                  'by', 'from', 'at', 'is', 'are', 'was', 'were', 'be', 'been',
                  'this', 'that', 'these', 'those', 'which', 'what', 'where',
                  'when', 'how', 'why', 'who', 'their', 'them', 'they', 'its'}

    # Get distinctive words from abstract (5+ chars to be more specific)
    abstract_words = set(
        w.lower() for w in re.findall(r'\b[a-zA-Z]{5,}\b', abstract)
        if w.lower() not in stop_words
    )

    if not abstract_words:
        return True, 1.0  # Can't verify

    pdf_text_lower = pdf_text.lower()

    # Check how many abstract keywords appear in PDF
    found = sum(1 for w in abstract_words if w in pdf_text_lower)
    score = found / len(abstract_words)

    logger.debug(f"Abstract verification: {found}/{len(abstract_words)} words found (score={score:.2f})")

    return score >= threshold, score


@dataclass
class PDFMetadata:
    """Metadata extracted from a PDF file."""
    filename: str
    filepath: Path
    file_size: int
    sha256: str
    
    # Extracted info
    authors: List[str] = field(default_factory=list)
    title: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    
    # Matching info
    confidence: float = 0.0
    extraction_method: str = "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'filename': self.filename,
            'filepath': str(self.filepath),
            'file_size': self.file_size,
            'sha256': self.sha256,
            'authors': self.authors,
            'title': self.title,
            'year': self.year,
            'doi': self.doi,
            'confidence': self.confidence,
            'extraction_method': self.extraction_method
        }
    
    @property
    def first_author_surname(self) -> Optional[str]:
        """Get first author's surname for matching."""
        if self.authors:
            surname = self.authors[0]
            # Handle "Smith, John" format
            if ',' in surname:
                surname = surname.split(',')[0]
            # Handle "John Smith" format
            elif ' ' in surname:
                surname = surname.split()[-1]
            return surname.strip()
        return None


class FilenameParser:
    """Parse PDF filenames to extract metadata."""
    
    # DOI pattern in filename (periods replaced with underscores)
    DOI_PATTERN = re.compile(r'10[\._]\d{4,}[\._][^\s]+', re.IGNORECASE)
    
    # Year pattern
    YEAR_PATTERN = re.compile(r'\b(19\d{2}|20[0-2]\d)\b')
    
    # Author patterns in filenames
    AUTHOR_PATTERNS = [
        # "Wastiels,_L.,_&_He" or "Wastiels_L_He"
        re.compile(r'^([A-Z][a-z]+)(?:[,_]\s*[A-Z]\.?)?(?:[,_&]+\s*([A-Z][a-z]+))?'),
        # "Smith_and_Jones" or "Smith-Jones"
        re.compile(r'^([A-Z][a-z]+)[\s_-]+(?:and|&)[\s_-]+([A-Z][a-z]+)'),
        # "SmithJones2020" (CamelCase)
        re.compile(r'^([A-Z][a-z]+)([A-Z][a-z]+)?(?:\d{4})?'),
    ]
    
    def parse(self, filename: str) -> PDFMetadata:
        """Parse a PDF filename to extract metadata."""
        # Remove extension
        name = Path(filename).stem
        
        result = PDFMetadata(
            filename=filename,
            filepath=Path(filename),
            file_size=0,
            sha256=""
        )
        
        # Clean up filename
        name_clean = self._clean_filename(name)
        
        # Try to extract DOI first (most reliable)
        doi = self._extract_doi(name)
        if doi:
            result.doi = doi
            result.extraction_method = 'doi_in_filename'
            result.confidence = 0.9
            return result
        
        # Try to extract year
        result.year = self._extract_year(name_clean)
        
        # Try to extract authors
        result.authors = self._extract_authors(name_clean)
        
        # Try to extract title
        result.title = self._extract_title(name_clean, result.authors, result.year)
        
        # Calculate confidence
        confidence = 0.1
        if result.authors:
            confidence += 0.3
        if result.year:
            confidence += 0.2
        if result.title and len(result.title) > 10:
            confidence += 0.3
        
        result.confidence = confidence
        result.extraction_method = 'filename_parsing'
        
        return result
    
    def _clean_filename(self, name: str) -> str:
        """Clean up filename for parsing."""
        # Replace common separators with spaces
        clean = re.sub(r'[_\-\.]', ' ', name)
        # Remove parentheses and brackets
        clean = re.sub(r'[\(\)\[\]]', ' ', clean)
        # Normalize whitespace
        clean = ' '.join(clean.split())
        return clean
    
    def _extract_doi(self, name: str) -> Optional[str]:
        """Extract DOI from filename."""
        # Replace underscores back to periods for DOI matching
        name_dots = name.replace('_', '.')
        match = self.DOI_PATTERN.search(name_dots)
        if match:
            doi = match.group(0)
            # Normalize
            return doi.lower()
        return None
    
    def _extract_year(self, name: str) -> Optional[int]:
        """Extract year from filename."""
        match = self.YEAR_PATTERN.search(name)
        if match:
            year = int(match.group(1))
            if 1900 <= year <= datetime.now().year + 1:
                return year
        return None
    
    def _extract_authors(self, name: str) -> List[str]:
        """Extract author names from filename."""
        authors = []
        
        for pattern in self.AUTHOR_PATTERNS:
            match = pattern.search(name)
            if match:
                for group in match.groups():
                    if group and len(group) > 1:
                        # Check if it looks like a name (capitalized, reasonable length)
                        if group[0].isupper() and 2 <= len(group) <= 20:
                            authors.append(group)
                break
        
        return authors[:3]  # Limit to 3 authors
    
    def _extract_title(self, name: str, authors: List[str], year: Optional[int]) -> Optional[str]:
        """Extract title from filename."""
        title = name
        
        # Remove authors from beginning
        for author in authors:
            title = re.sub(rf'^{re.escape(author)}\s*', '', title, flags=re.IGNORECASE)
        
        # Remove year
        if year:
            title = title.replace(str(year), '')
        
        # Remove common suffixes
        title = re.sub(r'\s+(?:final|draft|v\d+|copy)$', '', title, flags=re.IGNORECASE)
        
        # Clean up
        title = title.strip(' -_.,')
        
        if len(title) > 5:
            # Capitalize properly
            return title.title()
        
        return None


class PDFCataloger:
    """
    Catalog PDF files in a directory and create paper records.
    """

    RELEVANCE_KEYWORDS = [
        'architecture', 'architectural', 'built environment', 'environment',
        'environmental', 'design', 'lighting', 'light', 'daylight', 'daylighting',
        'acoustics', 'soundscape', 'sound', 'noise', 'biophilic', 'biophilia',
        'neuroarchitecture', 'spatial', 'space', 'sensory', 'perception',
        'cognitive', 'psychology', 'stress', 'wellbeing', 'well-being',
        'occupant', 'indoor', 'comfort', 'thermal', 'air quality',
    ]
    OFF_TOPIC_THRESHOLD = 0.06
    DOI_TEXT_PATTERN = re.compile(
        r'(?:doi[:\s]*)?(?:https?://(?:dx\.)?doi\.org/)?'
        r'(10\.\d{4,9}/[^\s"<>]+)',
        re.IGNORECASE
    )
    
    def __init__(
        self,
        database=None,
        doi_resolver=None,
        pdf_storage_dir: Optional[Path] = None,
        copy_to_storage: bool = False,
        extract_doi_from_text: bool = True
    ):
        """
        Args:
            database: Database instance for storing records
            doi_resolver: DOI resolver for enriching metadata
            pdf_storage_dir: Optional destination for copied PDFs
            copy_to_storage: If True, copy PDFs into storage_dir
            extract_doi_from_text: If True, try to extract DOI from PDF text
        """
        self.db = database
        self.resolver = doi_resolver
        self.filename_parser = FilenameParser()
        self.pdf_storage_dir = Path(pdf_storage_dir) if pdf_storage_dir else None
        self.copy_to_storage = copy_to_storage
        self.extract_doi_from_text = extract_doi_from_text

        if self.copy_to_storage and not self.pdf_storage_dir:
            self.pdf_storage_dir = Path("data/pdfs")
        
        self._reset_stats()

    def _reset_stats(self) -> None:
        self.stats = {
            'total_pdfs': 0,
            'with_doi': 0,
            'matched_crossref': 0,
            'created': 0,
            'updated': 0,
            'copied': 0,
            'already_present': 0,
            'processed': 0,
            'errors': [],
            'failed_files': []
        }

    def reset_stats(self) -> None:
        """Reset cataloging statistics."""
        self._reset_stats()
    
    def catalog_directory(
        self,
        pdf_dir: Path,
        source_name: str = "pdf_catalog",
        resolve_dois: bool = True,
        search_crossref: bool = True,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Catalog all PDFs in a directory.
        
        Args:
            pdf_dir: Directory containing PDFs
            source_name: Source identifier for import tracking
            resolve_dois: Whether to resolve DOIs found in filenames
            search_crossref: Whether to search CrossRef for unidentified papers
            limit: Maximum number of PDFs to process
            
        Returns:
            Statistics dictionary
        """
        self._reset_stats()
        pdf_dir = Path(pdf_dir)
        
        if not pdf_dir.exists():
            raise FileNotFoundError(f"Directory not found: {pdf_dir}")

        pdf_files = list(pdf_dir.glob("*.pdf"))
        self.stats['total_pdfs'] = len(pdf_files)
        
        if limit:
            pdf_files = pdf_files[:limit]
        
        logger.info(f"Cataloging {len(pdf_files)} PDFs from {pdf_dir}")

        if self.copy_to_storage and self.pdf_storage_dir:
            self.pdf_storage_dir.mkdir(parents=True, exist_ok=True)

        for pdf_path in pdf_files:
            self.catalog_file(pdf_path, source_name, resolve_dois, search_crossref)

        return self.stats

    def catalog_file(
        self,
        pdf_path: Path,
        source_name: str = "pdf_catalog",
        resolve_dois: bool = True,
        search_crossref: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Catalog a single PDF file."""
        self.stats['processed'] += 1

        try:
            return self._process_pdf(pdf_path, source_name, resolve_dois, search_crossref)
        except Exception as e:
            logger.warning(f"Error processing {pdf_path.name}: {e}")
            self.stats['errors'].append(f"{pdf_path.name}: {e}")
            self.stats['failed_files'].append(pdf_path.name)
            return None
    
    def _process_pdf(
        self,
        pdf_path: Path,
        source_name: str,
        resolve_dois: bool,
        search_crossref: bool
    ) -> Optional[Dict]:
        """Process a single PDF file."""
        # Parse filename
        metadata = self.filename_parser.parse(pdf_path.name)
        metadata.filepath = pdf_path
        metadata.file_size = pdf_path.stat().st_size
        metadata.sha256 = self._compute_hash(pdf_path)

        if not metadata.doi and self.extract_doi_from_text:
            text_doi = self._extract_doi_from_pdf_text(pdf_path)
            if text_doi:
                metadata.doi = text_doi
                metadata.extraction_method = 'doi_in_text'
                metadata.confidence = max(metadata.confidence, 0.7)
        
        # Try to enrich with DOI resolution
        paper_data = None
        
        if metadata.doi:
            self.stats['with_doi'] += 1
            
            if resolve_dois and self.resolver:
                paper_data = self.resolver.resolve(metadata.doi)
                if paper_data:
                    logger.debug(f"Resolved DOI for {pdf_path.name}")
        
        # If no DOI, try CrossRef search by title/author
        if paper_data is None and search_crossref and self.resolver:
            if metadata.title or metadata.authors:
                paper_data = self._search_crossref(metadata)
                if paper_data:
                    self.stats['matched_crossref'] += 1
                    logger.debug(f"Found CrossRef match for {pdf_path.name}")

        if self.copy_to_storage:
            stored_path = self._copy_to_storage(pdf_path, metadata)
            metadata.filepath = stored_path
            metadata.file_size = stored_path.stat().st_size
        
        # Build paper record
        paper = self._build_paper_record(metadata, paper_data, source_name)
        
        # Store in database
        if self.db and paper:
            try:
                existing = None
                if paper.get('doi'):
                    existing = self.db.get_paper_by_doi(paper['doi'])
                
                if existing:
                    # Update with PDF path
                    existing['pdf_path'] = str(metadata.filepath)
                    existing['pdf_sha256'] = metadata.sha256
                    existing['pdf_bytes'] = metadata.file_size
                    self.db.add_paper(existing)
                    self.stats['updated'] += 1
                else:
                    self.db.add_paper(paper)
                    self.stats['created'] += 1
                    
            except Exception as e:
                logger.warning(f"Database error for {pdf_path.name}: {e}")
                self.stats['errors'].append(f"{pdf_path.name}: {e}")
        
        return paper

    def _extract_doi_from_pdf_text(self, pdf_path: Path) -> Optional[str]:
        """Try to extract a DOI from the PDF text."""
        pdf_text = extract_pdf_text(pdf_path, max_pages=2, max_chars=8000)
        if not pdf_text:
            return None

        match = self.DOI_TEXT_PATTERN.search(pdf_text)
        if not match:
            return None

        doi = match.group(1).strip().rstrip(').,;]')
        return doi.lower() if doi else None

    def _safe_filename(self, doi: Optional[str], title: Optional[str], fallback: str) -> str:
        """Generate a safe filename for PDF storage."""
        if doi:
            safe = doi.replace('/', '_').replace(':', '_')
            return f"{safe}.pdf"

        base = title or fallback or "paper"
        safe = re.sub(r'[^\w\s-]', '', base)[:80]
        safe = re.sub(r'\s+', '_', safe).strip('_')
        if not safe:
            safe = "paper"
        return f"{safe}.pdf"

    def _copy_to_storage(self, source: Path, metadata: PDFMetadata) -> Path:
        """Copy a PDF to the storage directory if configured."""
        if not self.pdf_storage_dir:
            return source

        storage_dir = self.pdf_storage_dir

        try:
            source_resolved = source.resolve()
            storage_resolved = storage_dir.resolve()
            source_resolved.relative_to(storage_resolved)
            self.stats['already_present'] += 1
            return source
        except Exception:
            pass

        storage_dir.mkdir(parents=True, exist_ok=True)
        filename = self._safe_filename(metadata.doi, metadata.title, source.stem)
        dest = storage_dir / filename

        if dest.exists():
            try:
                if self._compute_hash(dest) == metadata.sha256:
                    self.stats['already_present'] += 1
                    return dest
            except Exception:
                pass

            stem = dest.stem
            suffix = 1
            while dest.exists():
                dest = storage_dir / f"{stem}_{suffix}.pdf"
                suffix += 1

        shutil.copy2(source, dest)
        self.stats['copied'] += 1
        return dest
    
    def _compute_hash(self, filepath: Path) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def _search_crossref(self, metadata: PDFMetadata) -> Optional[Dict]:
        """
        Search CrossRef for paper metadata with PDF content verification.

        This method now verifies that CrossRef results actually match the PDF
        content before accepting them, preventing wrong DOI/abstract matches.
        """
        if not self.resolver:
            return None

        # Build search query
        query_parts = []

        if metadata.first_author_surname:
            query_parts.append(metadata.first_author_surname)

        if metadata.title:
            # Use first few words of title
            title_words = metadata.title.split()[:5]
            query_parts.extend(title_words)

        if not query_parts:
            return None

        query = ' '.join(query_parts)

        try:
            results = self.resolver.search_crossref(query, limit=3)

            if results:
                # Score results by match quality
                best_match = None
                best_score = 0

                for result in results:
                    score = self._score_match(metadata, result)
                    if score > best_score:
                        best_score = score
                        best_match = result

                # STOPGAP: Raised threshold from 0.5 to 0.7 to prevent wrong DOI matches
                # See claim_verifier.py for detection of past mismatches
                if best_score >= 0.7 and best_match:
                    # NEW: Verify against actual PDF content before accepting
                    if self._verify_crossref_match(metadata, best_match):
                        logger.info(f"CrossRef match verified and accepted (score={best_score:.2f})")
                        return best_match
                    else:
                        logger.warning(f"CrossRef match rejected: PDF content doesn't match (score={best_score:.2f})")
                        return None
                else:
                    logger.debug(f"CrossRef match rejected (score={best_score:.2f} < 0.7)")

        except Exception as e:
            logger.debug(f"CrossRef search failed: {e}")

        return None

    def _verify_crossref_match(self, metadata: PDFMetadata, crossref_result: Dict) -> bool:
        """
        Verify a CrossRef result against actual PDF content.

        This catches cases where CrossRef returns the wrong paper's metadata
        (e.g., "Integrating Natural Light..." matched to "Integrating Access...").

        Returns True if:
        - PDF text extraction fails (can't verify, accept match)
        - PDF text matches CrossRef title/abstract
        - No abstract available to verify (can't verify, accept match)

        Returns False if:
        - PDF text clearly doesn't match CrossRef abstract/title
        """
        pdf_path = metadata.filepath

        # Extract text from PDF
        pdf_text = extract_pdf_text(pdf_path, max_pages=2, max_chars=5000)

        if not pdf_text or len(pdf_text.strip()) < 100:
            # Can't extract enough text - accept the match on score alone
            logger.debug(f"PDF text extraction failed or insufficient, accepting match on score")
            return True

        crossref_title = crossref_result.get('title', '')
        crossref_abstract = crossref_result.get('abstract', '')

        # Check 1: Does PDF text match the CrossRef title?
        if crossref_title:
            title_matches, title_score = verify_text_matches_title(pdf_text, crossref_title)
            logger.debug(f"PDF-title verification: matches={title_matches}, score={title_score:.2f}")

            if not title_matches and title_score < 0.3:
                # Very low title match - definitely wrong paper
                logger.warning(f"PDF content doesn't match CrossRef title (score={title_score:.2f})")
                return False

        # Check 2: Does PDF text match the CrossRef abstract?
        if crossref_abstract:
            abstract_matches, abstract_score = verify_abstract_matches_pdf(crossref_abstract, pdf_text)
            logger.debug(f"PDF-abstract verification: matches={abstract_matches}, score={abstract_score:.2f}")

            if not abstract_matches and abstract_score < 0.25:
                # Very low abstract match - definitely wrong paper
                logger.warning(f"CrossRef abstract doesn't match PDF content (score={abstract_score:.2f})")
                return False

        # Passed verification or couldn't verify
        return True
    
    def _score_match(self, metadata: PDFMetadata, crossref_result: Dict) -> float:
        """
        Score how well a CrossRef result matches our metadata.

        IMPORTANT: This scoring is critical for avoiding wrong DOI matches.
        A wrong match can pollute the database with incorrect abstracts.

        Returns score 0-1, where:
        - < 0.7: Reject (too risky)
        - >= 0.7: Accept (high confidence match)
        """
        score = 0.0
        title_overlap = 0.0

        # Author match (required for high confidence)
        author_matched = False
        if metadata.first_author_surname and crossref_result.get('authors'):
            cr_authors = crossref_result['authors']
            if isinstance(cr_authors, list) and cr_authors:
                first_author = cr_authors[0]
                if isinstance(first_author, dict):
                    cr_surname = first_author.get('family', first_author.get('name', ''))
                else:
                    cr_surname = str(first_author)

                if metadata.first_author_surname.lower() in cr_surname.lower():
                    score += 0.35
                    author_matched = True

        # Year match
        if metadata.year and crossref_result.get('year'):
            if metadata.year == crossref_result['year']:
                score += 0.2

        # Title similarity - STRICTER matching
        if metadata.title and crossref_result.get('title'):
            # Remove common words that cause false matches
            stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with'}

            meta_words = set(w.lower() for w in metadata.title.split() if len(w) > 2)
            meta_words -= stop_words

            cr_words = set(w.lower() for w in crossref_result['title'].split() if len(w) > 2)
            cr_words -= stop_words

            if meta_words:
                # Bidirectional overlap - both directions must match well
                overlap_meta = len(meta_words & cr_words) / len(meta_words)
                overlap_cr = len(meta_words & cr_words) / max(len(cr_words), 1)
                title_overlap = min(overlap_meta, overlap_cr)  # Use stricter of two

                score += 0.45 * title_overlap

        # STOPGAP: Require minimum title overlap to prevent wrong matches
        # "Integrating Natural Light" vs "Integrating Access and Functional Needs"
        # would have low overlap and be rejected
        if title_overlap < 0.4:
            # Title doesn't match well enough - cap the score
            score = min(score, 0.5)
            logger.debug(f"Low title overlap ({title_overlap:.2f}), capping score at 0.5")

        # STOPGAP: Require author match for high confidence
        if not author_matched and score > 0.5:
            score = min(score, 0.6)
            logger.debug("No author match, capping score at 0.6")

        return score
    
    def _build_paper_record(
        self,
        metadata: PDFMetadata,
        crossref_data: Optional[Dict],
        source_name: str
    ) -> Dict[str, Any]:
        """Build a paper record from metadata."""
        paper = {}
        
        # Use CrossRef data if available, fall back to filename parsing
        if crossref_data:
            paper = {
                'doi': crossref_data.get('doi'),
                'title': crossref_data.get('title', metadata.title or metadata.filename),
                'authors': crossref_data.get('authors', metadata.authors),
                'year': crossref_data.get('year', metadata.year),
                'venue': crossref_data.get('venue'),
                'publisher': crossref_data.get('publisher'),
                'abstract': crossref_data.get('abstract'),
                'url': crossref_data.get('url'),
            }
        else:
            paper = {
                'doi': metadata.doi,
                'title': metadata.title or metadata.filename,
                'authors': metadata.authors,
                'year': metadata.year,
            }
        
        # Generate paper_id
        if paper.get('doi'):
            paper['paper_id'] = f"doi:{paper['doi']}"
        else:
            paper['paper_id'] = f"sha256:{metadata.sha256[:12]}"
        
        # Add file info
        paper['pdf_path'] = str(metadata.filepath)
        paper['pdf_sha256'] = metadata.sha256
        paper['pdf_bytes'] = metadata.file_size
        
        # Add tracking info
        paper['source'] = source_name
        paper['ingest_method'] = 'pdf_catalog'
        paper['status'] = 'candidate'
        paper['retrieved_at'] = datetime.utcnow().isoformat()
        
        # Topic/relevance scoring
        abstract = (paper.get('abstract') or '').lower()
        title_text = (paper.get('title') or '').lower()
        if abstract:
            score = self._relevance_score(abstract)
            paper['topic_score'] = score
            paper['topic_stage'] = 'final'
            paper['topic_decision'] = 'on_topic' if score >= self.OFF_TOPIC_THRESHOLD else 'off_topic'
            paper['off_topic_score'] = score
            paper['off_topic_flag'] = 1 if paper['topic_decision'] == 'off_topic' else 0
        else:
            score = self._relevance_score(title_text)
            paper['topic_score'] = score
            paper['topic_stage'] = 'needs_abstract'
            if score < self.OFF_TOPIC_THRESHOLD:
                paper['topic_decision'] = 'possibly_off_topic'
                paper['off_topic_score'] = score
                paper['off_topic_flag'] = 0
                if self.db:
                    queue_key = paper.get('doi') or self._queue_key_from_title(paper.get('title') or '')
                    if queue_key:
                        self.db.add_to_expansion_queue(
                            queue_key,
                            title=paper.get('title'),
                            discovered_from=paper.get('paper_id'),
                            priority_score=0.8,
                        )
            else:
                paper['topic_decision'] = 'needs_abstract'
                paper['off_topic_score'] = score
                paper['off_topic_flag'] = 0
        
        return paper
    
    def _relevance_score(self, text: str) -> float:
        """Score text relevance based on keyword matches."""
        tokens = self._tokenize_text(text)
        if not tokens:
            return 0.0
        hits = 0
        for kw in self.RELEVANCE_KEYWORDS:
            if kw in text:
                hits += 1
        return hits / max(len(self.RELEVANCE_KEYWORDS), 1)

    def _tokenize_text(self, text: str) -> set:
        """Tokenize text for comparison."""
        clean = re.sub(r'[^a-zA-Z\s]', ' ', text).lower()
        return {t for t in clean.split() if len(t) > 3}

    def _queue_key_from_title(self, title: str) -> str:
        """Generate queue key from title."""
        key = (title or '').strip().lower()
        if not key:
            return ''
        return 'title:' + hashlib.sha1(key.encode('utf-8')).hexdigest()
    
    def scan_directory(self, pdf_dir: Path) -> Generator[PDFMetadata, None, None]:
        """
        Scan directory and yield metadata for each PDF.
        Does not store to database.
        """
        pdf_dir = Path(pdf_dir)
        
        for pdf_path in pdf_dir.glob("*.pdf"):
            try:
                metadata = self.filename_parser.parse(pdf_path.name)
                metadata.filepath = pdf_path
                metadata.file_size = pdf_path.stat().st_size
                metadata.sha256 = self._compute_hash(pdf_path)
                yield metadata
            except Exception as e:
                logger.warning(f"Error scanning {pdf_path.name}: {e}")


def catalog_pdfs(pdf_dir: Path, database=None, resolver=None, **kwargs) -> Dict[str, Any]:
    """Convenience function to catalog PDFs."""
    cataloger = PDFCataloger(database=database, doi_resolver=resolver)
    return cataloger.catalog_directory(pdf_dir, **kwargs)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Catalog PDFs in a directory')
    parser.add_argument('directory', type=Path, help='Directory containing PDFs')
    parser.add_argument('--limit', type=int, help='Maximum PDFs to process')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    
    cataloger = PDFCataloger()
    
    print(f"Scanning {args.directory}...")
    
    for metadata in cataloger.scan_directory(args.directory):
        print(f"\n{'='*60}")
        print(f"File: {metadata.filename}")
        print(f"Size: {metadata.file_size / 1024:.1f} KB")
        print(f"Authors: {metadata.authors}")
        print(f"Title: {metadata.title}")
        print(f"Year: {metadata.year}")
        print(f"DOI: {metadata.doi}")
        print(f"Confidence: {metadata.confidence:.2f}")
        
        if args.limit:
            args.limit -= 1
            if args.limit <= 0:
                break
