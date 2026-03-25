# Version: 3.2.2
"""
Article Finder v3.2 - Deduplicator
Robust duplicate detection and paper matching.

This module handles:
1. DOI-based exact matching
2. Title similarity matching (fuzzy)
3. Author overlap detection
4. PDF-to-paper matching
5. Merge logic for combining duplicate records
"""

import re
import logging
from typing import Optional, Dict, List, Any, Tuple, Set
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of a duplicate check."""
    is_duplicate: bool
    matched_paper_id: Optional[str] = None
    match_type: str = "none"  # doi, title, author_title, fuzzy
    confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_duplicate': self.is_duplicate,
            'matched_paper_id': self.matched_paper_id,
            'match_type': self.match_type,
            'confidence': self.confidence,
            'details': self.details
        }


class TitleNormalizer:
    """Normalizes titles for comparison."""
    
    # Words to strip
    STOP_WORDS = {'a', 'an', 'the', 'of', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'with', 'by'}
    
    @classmethod
    def normalize(cls, title: str) -> str:
        """
        Normalize a title for comparison.
        
        Steps:
        1. Lowercase
        2. Remove punctuation
        3. Remove stop words
        4. Collapse whitespace
        5. Sort words (order-independent matching)
        """
        if not title:
            return ""
        
        # Lowercase
        normalized = title.lower()
        
        # Remove punctuation
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        
        # Split into words
        words = normalized.split()
        
        # Remove stop words and short words
        words = [w for w in words if w not in cls.STOP_WORDS and len(w) > 2]
        
        # Sort for order-independent comparison
        words.sort()
        
        return ' '.join(words)
    
    @classmethod
    def extract_key_terms(cls, title: str, n: int = 5) -> Set[str]:
        """Extract key terms from title (longer words, likely unique)."""
        if not title:
            return set()
        
        normalized = title.lower()
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        words = normalized.split()
        
        # Filter and sort by length
        words = [w for w in words if w not in cls.STOP_WORDS and len(w) > 3]
        words.sort(key=len, reverse=True)
        
        return set(words[:n])


class AuthorNormalizer:
    """Normalizes author names for comparison."""
    
    @classmethod
    def normalize(cls, author: str) -> str:
        """Normalize a single author name to surname."""
        if not author:
            return ""
        
        # Strip and lowercase
        normalized = author.strip().lower()
        
        # Extract surname based on format
        if ',' in normalized:
            # Format: "Smith, John" or "Smith, J." - surname is before comma
            surname = normalized.split(',')[0].strip()
        else:
            # Format: "John Smith" or "J. Smith" - surname is last word
            # Remove punctuation for splitting
            clean = re.sub(r'[^\w\s-]', ' ', normalized)
            parts = clean.split()
            # Remove initials (single letters) and get last real word
            words = [p for p in parts if len(p) > 1]
            surname = words[-1] if words else (parts[-1] if parts else "")
        
        # Clean surname of any remaining punctuation
        surname = re.sub(r'[^\w-]', '', surname)
        
        return surname
    
    @classmethod
    def normalize_list(cls, authors: List[str]) -> Set[str]:
        """Normalize a list of authors to set of surnames."""
        surnames = set()
        for a in authors:
            if a:
                surname = cls.normalize(a)
                if surname and len(surname) > 1:
                    surnames.add(surname)
        return surnames


class Deduplicator:
    """
    Main deduplication engine.
    
    Checks for duplicates using multiple strategies:
    1. Exact DOI match (definitive)
    2. High title similarity (>0.9)
    3. Moderate title similarity + author overlap
    """
    
    # Thresholds
    TITLE_EXACT_THRESHOLD = 0.95
    TITLE_HIGH_THRESHOLD = 0.85
    TITLE_MODERATE_THRESHOLD = 0.70
    AUTHOR_OVERLAP_THRESHOLD = 0.5
    
    def __init__(self, database):
        """
        Args:
            database: Database instance
        """
        self.db = database
        
        # Caches for faster lookup
        self._doi_index: Dict[str, str] = {}  # doi -> paper_id
        self._title_index: Dict[str, str] = {}  # normalized_title -> paper_id
        self._author_index: Dict[str, Set[str]] = {}  # surname -> set of paper_ids
        self._loaded = False
    
    def load_index(self):
        """Load existing papers into index for fast lookup."""
        if self._loaded:
            return
        
        papers = self.db.search_papers(limit=100000)
        
        for paper in papers:
            paper_id = paper.get('paper_id')
            if not paper_id:
                continue
            
            # Index by DOI
            doi = paper.get('doi')
            if doi:
                self._doi_index[doi.lower()] = paper_id
            
            # Index by normalized title
            title = paper.get('title')
            if title:
                norm_title = TitleNormalizer.normalize(title)
                if norm_title:
                    self._title_index[norm_title] = paper_id
            
            # Index by author surnames
            authors = paper.get('authors', [])
            if authors:
                for surname in AuthorNormalizer.normalize_list(authors):
                    if surname not in self._author_index:
                        self._author_index[surname] = set()
                    self._author_index[surname].add(paper_id)
        
        self._loaded = True
        logger.info(f"Loaded dedup index: {len(self._doi_index)} DOIs, "
                   f"{len(self._title_index)} titles, {len(self._author_index)} author surnames")
    
    def check_duplicate(
        self,
        doi: Optional[str] = None,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        year: Optional[int] = None
    ) -> MatchResult:
        """
        Check if a paper is a duplicate of an existing record.
        
        Args:
            doi: Paper DOI
            title: Paper title
            authors: List of author names
            year: Publication year
            
        Returns:
            MatchResult with duplicate status and match details
        """
        self.load_index()
        
        # Strategy 1: Exact DOI match
        if doi:
            doi_lower = doi.lower()
            if doi_lower in self._doi_index:
                return MatchResult(
                    is_duplicate=True,
                    matched_paper_id=self._doi_index[doi_lower],
                    match_type='doi',
                    confidence=1.0,
                    details={'doi': doi}
                )
        
        # Strategy 2: Title-based matching
        if title:
            norm_title = TitleNormalizer.normalize(title)
            
            # Exact normalized title match
            if norm_title in self._title_index:
                return MatchResult(
                    is_duplicate=True,
                    matched_paper_id=self._title_index[norm_title],
                    match_type='title_exact',
                    confidence=0.95,
                    details={'normalized_title': norm_title}
                )
            
            # Fuzzy title matching
            best_match = self._fuzzy_title_match(title, authors)
            if best_match:
                return best_match
        
        # Strategy 3: Author + partial title (for short/common titles)
        if authors and title and len(title) < 50:
            author_match = self._author_title_match(title, authors)
            if author_match:
                return author_match
        
        return MatchResult(is_duplicate=False)
    
    def _fuzzy_title_match(
        self,
        title: str,
        authors: Optional[List[str]] = None
    ) -> Optional[MatchResult]:
        """Find fuzzy title matches."""
        key_terms = TitleNormalizer.extract_key_terms(title)
        if not key_terms:
            return None
        
        # Find candidate papers with matching key terms
        candidates = set()
        for norm_title, paper_id in self._title_index.items():
            title_terms = set(norm_title.split())
            overlap = len(key_terms & title_terms)
            if overlap >= min(2, len(key_terms)):
                candidates.add(paper_id)
        
        if not candidates:
            return None
        
        # Score candidates
        best_score = 0.0
        best_match = None
        
        norm_query = TitleNormalizer.normalize(title)
        author_surnames = AuthorNormalizer.normalize_list(authors or [])
        
        for paper_id in list(candidates)[:50]:  # Limit candidates
            paper = self.db.get_paper(paper_id)
            if not paper:
                continue
            
            paper_title = paper.get('title', '')
            paper_norm = TitleNormalizer.normalize(paper_title)
            
            # Title similarity
            title_sim = SequenceMatcher(None, norm_query, paper_norm).ratio()
            
            # Author overlap bonus
            author_bonus = 0.0
            if author_surnames:
                paper_authors = paper.get('authors', [])
                paper_surnames = AuthorNormalizer.normalize_list(paper_authors)
                if paper_surnames:
                    overlap = len(author_surnames & paper_surnames)
                    author_bonus = 0.1 * min(overlap, 3)
            
            score = title_sim + author_bonus
            
            if score > best_score:
                best_score = score
                best_match = paper_id
        
        # Apply thresholds
        if best_score >= self.TITLE_EXACT_THRESHOLD:
            return MatchResult(
                is_duplicate=True,
                matched_paper_id=best_match,
                match_type='title_fuzzy',
                confidence=best_score,
                details={'title_similarity': best_score}
            )
        elif best_score >= self.TITLE_HIGH_THRESHOLD:
            return MatchResult(
                is_duplicate=True,
                matched_paper_id=best_match,
                match_type='title_fuzzy',
                confidence=best_score * 0.9,
                details={'title_similarity': best_score, 'note': 'high_similarity'}
            )
        
        return None
    
    def _author_title_match(
        self,
        title: str,
        authors: List[str]
    ) -> Optional[MatchResult]:
        """Match by author overlap + partial title match."""
        author_surnames = AuthorNormalizer.normalize_list(authors)
        if not author_surnames:
            return None
        
        # Find papers by these authors
        candidate_ids = set()
        for surname in author_surnames:
            if surname in self._author_index:
                candidate_ids.update(self._author_index[surname])
        
        if not candidate_ids:
            return None
        
        # Check title overlap
        title_terms = TitleNormalizer.extract_key_terms(title)
        
        for paper_id in list(candidate_ids)[:100]:
            paper = self.db.get_paper(paper_id)
            if not paper:
                continue
            
            paper_title = paper.get('title', '')
            paper_terms = TitleNormalizer.extract_key_terms(paper_title)
            
            # Check author overlap
            paper_surnames = AuthorNormalizer.normalize_list(paper.get('authors', []))
            author_overlap = len(author_surnames & paper_surnames) / max(len(author_surnames), 1)
            
            # Check title term overlap
            if title_terms and paper_terms:
                term_overlap = len(title_terms & paper_terms) / max(len(title_terms), 1)
            else:
                term_overlap = 0
            
            # Require both author and title overlap
            if author_overlap >= self.AUTHOR_OVERLAP_THRESHOLD and term_overlap >= 0.4:
                return MatchResult(
                    is_duplicate=True,
                    matched_paper_id=paper_id,
                    match_type='author_title',
                    confidence=0.7 * (author_overlap + term_overlap) / 2,
                    details={
                        'author_overlap': author_overlap,
                        'title_term_overlap': term_overlap
                    }
                )
        
        return None
    
    def add_to_index(self, paper: Dict[str, Any]):
        """Add a paper to the dedup index."""
        paper_id = paper.get('paper_id')
        if not paper_id:
            return
        
        doi = paper.get('doi')
        if doi:
            self._doi_index[doi.lower()] = paper_id
        
        title = paper.get('title')
        if title:
            norm_title = TitleNormalizer.normalize(title)
            if norm_title:
                self._title_index[norm_title] = paper_id
        
        authors = paper.get('authors', [])
        for surname in AuthorNormalizer.normalize_list(authors):
            if surname not in self._author_index:
                self._author_index[surname] = set()
            self._author_index[surname].add(paper_id)


class PaperMerger:
    """Merges duplicate paper records."""
    
    @staticmethod
    def merge(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge a new paper into an existing record.
        
        Strategy: prefer non-null values, prefer longer text, combine lists.
        """
        merged = dict(existing)
        
        # Simple fields - prefer new if existing is empty
        for field in ['doi', 'year', 'venue', 'publisher', 'url']:
            if new.get(field) and not existing.get(field):
                merged[field] = new[field]
        
        # Title - prefer longer
        new_title = new.get('title') or ''
        existing_title = existing.get('title') or ''
        if len(new_title) > len(existing_title):
            merged['title'] = new['title']
        
        # Abstract - prefer longer
        new_abstract = new.get('abstract') or ''
        existing_abstract = existing.get('abstract') or ''
        if len(new_abstract) > len(existing_abstract):
            merged['abstract'] = new['abstract']
        
        # Authors - union
        existing_authors = set(existing.get('authors') or [])
        new_authors = set(new.get('authors') or [])
        if new_authors - existing_authors:
            merged['authors'] = list(existing_authors | new_authors)
        
        # Sources - combine
        existing_sources = existing.get('sources') or [existing.get('source')]
        existing_sources = [s for s in existing_sources if s]  # Filter None
        new_source = new.get('source')
        if new_source and new_source not in existing_sources:
            merged['sources'] = existing_sources + [new_source]
        
        # PDF path - prefer new if exists
        if new.get('pdf_path'):
            merged['pdf_path'] = new['pdf_path']
        
        return merged


class PDFMatcher:
    """Matches PDF files to paper records."""
    
    def __init__(self, database, deduplicator: Optional[Deduplicator] = None):
        self.db = database
        self.dedup = deduplicator or Deduplicator(database)
    
    def match_pdf(
        self,
        pdf_path: Path,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Match a PDF file to an existing paper record.
        
        Args:
            pdf_path: Path to PDF file
            metadata: Optional metadata extracted from filename
            
        Returns:
            paper_id if matched, None otherwise
        """
        from ingest.pdf_cataloger import FilenameParser
        
        # Extract metadata from filename if not provided
        if metadata is None:
            parser = FilenameParser()
            parsed = parser.parse(pdf_path.name)
            metadata = {
                'title': parsed.title,
                'authors': parsed.authors,
                'year': parsed.year,
                'doi': parsed.doi
            }
        
        # Try to find matching paper
        result = self.dedup.check_duplicate(
            doi=metadata.get('doi'),
            title=metadata.get('title'),
            authors=metadata.get('authors'),
            year=metadata.get('year')
        )
        
        if result.is_duplicate:
            return result.matched_paper_id
        
        return None
    
    def match_directory(
        self,
        pdf_dir: Path,
        update_records: bool = True
    ) -> Dict[str, Any]:
        """
        Match all PDFs in a directory to paper records.
        
        Returns:
            Stats dict with matched/unmatched counts
        """
        stats = {
            'total': 0,
            'matched': 0,
            'unmatched': 0,
            'matches': [],
            'unmatched_files': []
        }
        
        for pdf_path in pdf_dir.glob('*.pdf'):
            stats['total'] += 1
            
            paper_id = self.match_pdf(pdf_path)
            
            if paper_id:
                stats['matched'] += 1
                stats['matches'].append({
                    'pdf': pdf_path.name,
                    'paper_id': paper_id
                })
                
                if update_records:
                    paper = self.db.get_paper(paper_id)
                    if paper and not paper.get('pdf_path'):
                        paper['pdf_path'] = str(pdf_path)
                        self.db.add_paper(paper)
            else:
                stats['unmatched'] += 1
                stats['unmatched_files'].append(pdf_path.name)
        
        return stats


# Convenience functions
def check_duplicate(database, **kwargs) -> MatchResult:
    """Quick duplicate check."""
    dedup = Deduplicator(database)
    return dedup.check_duplicate(**kwargs)


def match_pdfs_to_papers(database, pdf_dir: Path) -> Dict[str, Any]:
    """Match PDFs in directory to paper records."""
    matcher = PDFMatcher(database)
    return matcher.match_directory(pdf_dir)
