# Version: 3.2.2
"""
Article Finder v3.2 - Smart Citation Parser
Extracts author, title, year, venue from messy citation strings.

Handles:
- APA style: Author, A. A., & Author, B. B. (Year). Title. Journal, Volume(Issue), Pages.
- MLA style: Author. "Title." Journal Volume.Issue (Year): Pages.
- Chicago: Author. "Title." Journal Volume, no. Issue (Year): Pages.
- Vancouver: Author(s). Title. Journal. Year;Volume(Issue):Pages.
- Informal/incomplete citations
"""

import re
import logging
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParsedCitation:
    """Result of parsing a citation string."""
    authors: List[str] = field(default_factory=list)
    title: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    publisher: Optional[str] = None
    confidence: float = 0.0  # 0-1, how confident we are in the parse
    raw_text: str = ""
    parse_method: str = "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'authors': self.authors,
            'title': self.title,
            'year': self.year,
            'venue': self.venue,
            'volume': self.volume,
            'issue': self.issue,
            'pages': self.pages,
            'doi': self.doi,
            'publisher': self.publisher,
            'confidence': self.confidence,
            'raw_text': self.raw_text,
            'parse_method': self.parse_method
        }
    
    @property
    def first_author_surname(self) -> Optional[str]:
        """Get the first author's surname for matching."""
        if self.authors:
            # Handle "Smith, John" or "John Smith" formats
            first = self.authors[0]
            if ',' in first:
                return first.split(',')[0].strip()
            else:
                parts = first.split()
                return parts[-1] if parts else None
        return None
    
    @property
    def is_usable(self) -> bool:
        """Check if we have enough info to search for this paper."""
        return bool(self.title) or (bool(self.authors) and self.year)


class CitationParser:
    """
    Parse citation strings into structured data.
    
    Uses multiple strategies and returns the best parse.
    """
    
    # DOI patterns
    DOI_PATTERNS = [
        re.compile(r'(?:doi[:\s]*)?(?:https?://(?:dx\.)?doi\.org/)?'
                   r'(10\.\d{4,}/[^\s\]>"\']+)', re.IGNORECASE),
    ]
    
    # Year patterns
    YEAR_PATTERNS = [
        re.compile(r'\((\d{4})\)'),  # (2020)
        re.compile(r',\s*(\d{4})[,.\s]'),  # , 2020.
        re.compile(r'\b(19\d{2}|20[0-2]\d)\b'),  # Any 4-digit year 1900-2029
    ]
    
    # Author patterns (various formats)
    AUTHOR_PATTERNS = [
        # "Smith, J., & Jones, K."
        re.compile(r'^([A-Z][a-z]+(?:[-\s][A-Z][a-z]+)*),\s*([A-Z]\.(?:\s*[A-Z]\.)*)'
                   r'(?:,?\s*&?\s*([A-Z][a-z]+),\s*([A-Z]\.(?:\s*[A-Z]\.)*))*'),
        # "Smith J, Jones K"
        re.compile(r'^([A-Z][a-z]+)\s+([A-Z])(?:,\s*([A-Z][a-z]+)\s+([A-Z]))*'),
        # "J. Smith"
        re.compile(r'^([A-Z]\.(?:\s*[A-Z]\.)*)\s+([A-Z][a-z]+(?:[-\s][A-Z][a-z]+)*)'),
    ]
    
    # Page patterns
    PAGE_PATTERNS = [
        re.compile(r'(?:pp?\.)?\s*(\d+)\s*[-–—]\s*(\d+)'),  # pp. 100-200 or 100-200
        re.compile(r'(?:pages?:?\s*)(\d+)\s*[-–—]\s*(\d+)', re.IGNORECASE),
    ]
    
    # Volume/issue patterns
    VOLUME_ISSUE_PATTERNS = [
        re.compile(r'(\d+)\s*\((\d+)\)'),  # 45(3)
        re.compile(r'[Vv]ol\.?\s*(\d+)'),  # Vol. 45
        re.compile(r'[Nn]o\.?\s*(\d+)'),  # No. 3
    ]
    
    def __init__(self):
        self.strategies = [
            self._parse_mdpi,       # Try MDPI first (user's data format)
            self._parse_apa,
            self._parse_mla,
            self._parse_chicago,
            self._parse_vancouver,
            self._parse_informal,
            self._parse_fallback,
        ]
    
    def parse(self, citation: str) -> ParsedCitation:
        """
        Parse a citation string using multiple strategies.
        Returns the best parse result.
        """
        if not citation or not citation.strip():
            return ParsedCitation(raw_text=citation or "", confidence=0.0)
        
        citation = self._normalize(citation)
        
        # Try to extract DOI first (most reliable)
        doi = self._extract_doi(citation)
        
        # Try each strategy
        best_result = None
        best_confidence = 0.0
        
        for strategy in self.strategies:
            try:
                result = strategy(citation)
                if result and result.confidence > best_confidence:
                    best_result = result
                    best_confidence = result.confidence
                    
                    # If we get a high-confidence parse, stop
                    if best_confidence >= 0.8:
                        break
            except Exception as e:
                logger.debug(f"Strategy {strategy.__name__} failed: {e}")
                continue
        
        if best_result is None:
            best_result = ParsedCitation(raw_text=citation, confidence=0.0)
        
        # Add DOI if found
        if doi:
            best_result.doi = doi
            best_result.confidence = min(1.0, best_result.confidence + 0.2)
        
        best_result.raw_text = citation
        return best_result
    
    def _normalize(self, text: str) -> str:
        """Normalize whitespace and encoding issues."""
        # Replace various dashes with standard hyphen
        text = re.sub(r'[–—−]', '-', text)
        # Normalize quotes
        text = re.sub(r'[""„]', '"', text)
        text = re.sub(r"[''`]", "'", text)
        # Normalize whitespace
        text = ' '.join(text.split())
        return text.strip()
    
    def _extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from citation text."""
        for pattern in self.DOI_PATTERNS:
            match = pattern.search(text)
            if match:
                doi = match.group(1)
                # Clean trailing punctuation
                doi = doi.rstrip('.,;:')
                return doi.lower()
        return None
    
    def _extract_year(self, text: str) -> Optional[int]:
        """Extract publication year from text."""
        for pattern in self.YEAR_PATTERNS:
            match = pattern.search(text)
            if match:
                year = int(match.group(1))
                if 1800 <= year <= 2030:
                    return year
        return None
    
    def _extract_pages(self, text: str) -> Optional[str]:
        """Extract page range from text."""
        for pattern in self.PAGE_PATTERNS:
            match = pattern.search(text)
            if match:
                return f"{match.group(1)}-{match.group(2)}"
        return None
    
    def _parse_apa(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse APA-style citation:
        Author, A. A., & Author, B. B. (Year). Title of article. Journal Name, Volume(Issue), Pages.
        """
        result = ParsedCitation(parse_method='apa')
        
        # Look for year in parentheses
        year_match = re.search(r'\((\d{4})\)', citation)
        if not year_match:
            return None
        
        result.year = int(year_match.group(1))
        year_pos = year_match.start()
        
        # Authors are before the year
        author_part = citation[:year_pos].strip().rstrip(',').rstrip('.')
        result.authors = self._parse_authors_apa(author_part)
        
        # Title is after year, before next period or journal
        after_year = citation[year_match.end():].strip()
        if after_year.startswith('.'):
            after_year = after_year[1:].strip()
        
        # Title typically ends at period followed by Journal Name (italicized or capitalized)
        title_match = re.match(r'^([^.]+(?:\.[^.]+)*?)\.?\s+([A-Z][^,]+)', after_year)
        if title_match:
            result.title = title_match.group(1).strip()
            venue_and_rest = title_match.group(2) + after_year[title_match.end():]
            
            # Extract venue and volume
            venue_match = re.match(r'^([^,\d]+)', venue_and_rest)
            if venue_match:
                result.venue = venue_match.group(1).strip()
        else:
            # Just take everything as title
            parts = after_year.split('.')
            if parts:
                result.title = parts[0].strip()
        
        # Extract pages
        result.pages = self._extract_pages(citation)
        
        # Calculate confidence
        confidence = 0.3  # Base for finding year
        if result.authors:
            confidence += 0.3
        if result.title and len(result.title) > 10:
            confidence += 0.3
        if result.venue:
            confidence += 0.1
        
        result.confidence = confidence
        return result
    
    def _parse_authors_apa(self, text: str) -> List[str]:
        """Parse APA-style author list."""
        authors = []
        
        # Split by & or 'and'
        text = re.sub(r'\s+&\s+', ', ', text)
        text = re.sub(r'\s+and\s+', ', ', text, flags=re.IGNORECASE)
        
        # Handle "et al."
        text = re.sub(r',?\s*et\.?\s*al\.?', '', text, flags=re.IGNORECASE)
        
        # Split by comma (but not comma within a single author name)
        parts = re.split(r',\s*(?=[A-Z])', text)
        
        for part in parts:
            part = part.strip()
            if part and len(part) > 1:
                # Clean up initials
                part = re.sub(r'\.([A-Z])', r'. \1', part)
                authors.append(part)
        
        return authors
    
    def _parse_mla(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse MLA-style citation:
        Author. "Title of Article." Journal Name, vol. X, no. Y, Year, pp. Z-Z.
        """
        result = ParsedCitation(parse_method='mla')
        
        # Look for quoted title
        title_match = re.search(r'"([^"]+)"', citation)
        if not title_match:
            return None
        
        result.title = title_match.group(1)
        
        # Author is before the title
        author_part = citation[:title_match.start()].strip().rstrip('.')
        if author_part:
            result.authors = [a.strip() for a in author_part.split(' and ')]
        
        # Year and venue after title
        after_title = citation[title_match.end():]
        result.year = self._extract_year(after_title)
        
        # Venue is typically the first part after the title
        venue_match = re.match(r'[.\s]*([^,\d]+)', after_title)
        if venue_match:
            result.venue = venue_match.group(1).strip()
        
        result.pages = self._extract_pages(citation)
        
        # Calculate confidence
        confidence = 0.4  # Base for finding quoted title
        if result.authors:
            confidence += 0.2
        if result.year:
            confidence += 0.2
        if result.venue:
            confidence += 0.1
        
        result.confidence = confidence
        return result
    
    def _parse_chicago(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse Chicago-style citation.
        """
        result = ParsedCitation(parse_method='chicago')
        
        # Similar to APA but may have different punctuation
        # Look for period-separated parts
        parts = [p.strip() for p in citation.split('.') if p.strip()]
        
        if len(parts) < 2:
            return None
        
        # First part is usually authors
        result.authors = self._parse_authors_apa(parts[0])
        
        # Second part is often title
        if len(parts) > 1:
            result.title = parts[1].strip('"').strip()
        
        # Look for year
        result.year = self._extract_year(citation)
        
        # Look for venue (often in third part or after title)
        if len(parts) > 2:
            venue_part = parts[2]
            # Remove volume/issue info
            venue_part = re.sub(r'\d+.*', '', venue_part).strip()
            if venue_part:
                result.venue = venue_part
        
        result.pages = self._extract_pages(citation)
        
        # Calculate confidence
        confidence = 0.2
        if result.authors:
            confidence += 0.3
        if result.title and len(result.title) > 10:
            confidence += 0.3
        if result.year:
            confidence += 0.2
        
        result.confidence = confidence
        return result
    
    def _parse_vancouver(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse Vancouver-style citation (common in medical literature).
        Also handles MDPI format: Author(s). Title. Journal Year, Volume, Pages.
        """
        result = ParsedCitation(parse_method='vancouver')
        
        # Look for year;volume pattern (traditional Vancouver)
        match = re.search(r'(\d{4})\s*;\s*(\d+)', citation)
        if match:
            result.year = int(match.group(1))
            result.volume = match.group(2)
        else:
            result.year = self._extract_year(citation)
        
        # Split by periods
        parts = [p.strip() for p in citation.split('.') if p.strip()]
        
        if len(parts) >= 2:
            result.authors = self._parse_vancouver_authors(parts[0])
            result.title = parts[1]
        
        if len(parts) >= 3:
            result.venue = re.sub(r'\d{4}.*', '', parts[2]).strip()
        
        result.pages = self._extract_pages(citation)
        
        # Calculate confidence
        confidence = 0.2
        if result.authors:
            confidence += 0.3
        if result.title and len(result.title) > 10:
            confidence += 0.3
        if result.year:
            confidence += 0.2
        
        result.confidence = confidence
        return result
    
    def _parse_mdpi(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse MDPI-style citation.
        Format: LastName, I.; LastName2, I.J. Title of Paper. Journal Abbrev. Year, Vol, Pages.
        
        Examples:
        - Ledoux, J.E. Cognitive-Emotional Interactions in the Brain. Cogn. Emot. 2008, 3, 267-289.
        - Glass, D.C.; Singer, J.E. Urban Stress. Academic Press: New York, 1972.
        """
        result = ParsedCitation(parse_method='mdpi')
        
        # MDPI uses semicolons between authors
        # Look for the pattern: Authors. Title. Venue Year, ...
        
        # Find where authors end (look for pattern: initial. followed by non-initial text)
        # Authors typically end with initials like "J.E." or "M.A." followed by a space and capital letter
        author_end_match = re.search(r'([A-Z]\.[A-Z]?\.?)\s+([A-Z][a-z])', citation)
        
        if author_end_match:
            author_part = citation[:author_end_match.end(1)].strip()
            rest = citation[author_end_match.start(2):].strip()
            
            # Parse authors (semicolon-separated in MDPI)
            result.authors = self._parse_mdpi_authors(author_part)
            
            # Rest should be: Title. Venue Year, Volume, Pages.
            # Find the year to help locate venue
            year_match = re.search(r'\b(19\d{2}|20[0-2]\d)\b', rest)
            if year_match:
                result.year = int(year_match.group(1))
                year_pos = year_match.start()
                
                # Title is everything up to the venue (which precedes the year)
                # Venue is typically an abbreviation like "J. Environ. Psychol." or "Cogn. Emot."
                # Look backwards from year for the venue start
                before_year = rest[:year_pos].strip().rstrip('.')
                
                # Split into title and venue
                # Venue is usually the last abbreviated journal name
                # Look for pattern: Word. Word. or Word. Word. Word. at the end
                venue_match = re.search(r'([A-Z][a-z]*\.(?:\s+[A-Z][a-z]*\.)+)\s*$', before_year)
                if venue_match:
                    result.venue = venue_match.group(1).strip()
                    title_part = before_year[:venue_match.start()].strip()
                else:
                    # Try simpler pattern - last sentence before year
                    parts = before_year.rsplit('.', 1)
                    if len(parts) == 2 and len(parts[1].strip()) < 50:
                        title_part = parts[0].strip()
                        result.venue = parts[1].strip()
                    else:
                        title_part = before_year
                
                result.title = title_part.rstrip('.')
            else:
                # No year found, try simpler split
                parts = rest.split('.', 1)
                if parts:
                    result.title = parts[0].strip()
        else:
            # Fall back to period-based splitting
            parts = [p.strip() for p in citation.split('.') if p.strip()]
            if len(parts) >= 2:
                result.authors = self._parse_mdpi_authors(parts[0])
                # Title is likely the longest remaining part
                remaining = parts[1:]
                if remaining:
                    # Find the part that looks most like a title (longer, before year)
                    for i, part in enumerate(remaining):
                        if re.search(r'\b(19|20)\d{2}\b', part):
                            # This part has a year, so previous parts are title
                            if i > 0:
                                result.title = '. '.join(remaining[:i])
                            break
                    else:
                        result.title = remaining[0] if remaining else None
            
            result.year = self._extract_year(citation)
        
        result.pages = self._extract_pages(citation)
        
        # Calculate confidence
        confidence = 0.3  # Base for MDPI detection
        if result.authors and len(result.authors) > 0:
            confidence += 0.25
        if result.title and len(result.title) > 15:
            confidence += 0.25
        if result.year:
            confidence += 0.2
        
        result.confidence = confidence
        return result
    
    def _parse_mdpi_authors(self, text: str) -> List[str]:
        """Parse MDPI-style author list: LastName, I.; LastName2, I.J."""
        authors = []
        
        # Split by semicolons
        parts = text.split(';')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Each part is "LastName, Initials"
            if ',' in part:
                name_parts = part.split(',', 1)
                surname = name_parts[0].strip()
                if surname and len(surname) > 1:
                    authors.append(surname)
            elif part and len(part) > 1:
                authors.append(part)
        
        return authors[:10]  # Limit to 10 authors
    
    def _parse_vancouver_authors(self, text: str) -> List[str]:
        """Parse Vancouver-style author list (Surname AB, Surname CD)."""
        authors = []
        # Split by comma
        parts = text.split(',')
        for part in parts:
            part = part.strip()
            if part and len(part) > 2:
                authors.append(part)
        return authors
    
    def _parse_informal(self, citation: str) -> Optional[ParsedCitation]:
        """
        Parse informal/incomplete citations.
        Tries to extract whatever information is available.
        """
        result = ParsedCitation(parse_method='informal')
        
        # Extract year
        result.year = self._extract_year(citation)
        
        # Extract DOI
        result.doi = self._extract_doi(citation)
        
        # Try to find title - often the longest part
        # Look for text in quotes first
        title_match = re.search(r'"([^"]+)"', citation)
        if title_match:
            result.title = title_match.group(1)
        else:
            # Look for period-separated parts
            parts = [p.strip() for p in re.split(r'\.\s+', citation) if p.strip()]
            if parts:
                # Filter out very short parts (likely authors/initials)
                long_parts = [p for p in parts if len(p) > 20]
                if long_parts:
                    result.title = long_parts[0]
                elif len(parts) > 1:
                    result.title = parts[1] if len(parts[1]) > len(parts[0]) else parts[0]
        
        # Try to extract author from beginning
        if citation:
            # Take text before first year or period
            author_end = len(citation)
            
            year_match = re.search(r'[(\[]?\d{4}[)\]]?', citation)
            if year_match:
                author_end = min(author_end, year_match.start())
            
            first_period = citation.find('.')
            if first_period > 0:
                author_end = min(author_end, first_period)
            
            author_part = citation[:author_end].strip()
            if author_part and len(author_part) < 100:
                result.authors = [author_part]
        
        # Calculate confidence (lower for informal)
        confidence = 0.1
        if result.doi:
            confidence += 0.4
        if result.title and len(result.title) > 15:
            confidence += 0.2
        if result.year:
            confidence += 0.15
        if result.authors:
            confidence += 0.15
        
        result.confidence = confidence
        return result
    
    def _parse_fallback(self, citation: str) -> ParsedCitation:
        """
        Last resort: extract whatever we can.
        """
        result = ParsedCitation(parse_method='fallback')
        
        result.year = self._extract_year(citation)
        result.doi = self._extract_doi(citation)
        result.pages = self._extract_pages(citation)
        
        # Use first part as potential author, rest as title
        parts = citation.split('.', 1)
        if len(parts) >= 2:
            first_part = parts[0].strip()
            rest = parts[1].strip()
            
            # If first part looks like an author (short, has comma or initials)
            if len(first_part) < 50 and (
                ',' in first_part or 
                re.search(r'\b[A-Z]\.\s*[A-Z]\.', first_part) or
                re.search(r'\b[A-Z][a-z]+\s+[A-Z]\.', first_part)
            ):
                result.authors = [first_part]
                result.title = rest.split('.')[0] if '.' in rest else rest
            else:
                # First part might be the title
                result.title = first_part
        else:
            result.title = citation[:200]  # Truncate if too long
        
        result.confidence = 0.1
        return result


class BatchCitationParser:
    """Parse multiple citations and provide statistics."""
    
    def __init__(self):
        self.parser = CitationParser()
    
    def parse_all(self, citations: List[str]) -> Tuple[List[ParsedCitation], Dict[str, Any]]:
        """
        Parse a list of citations.
        Returns (results, statistics).
        """
        results = []
        stats = {
            'total': len(citations),
            'with_doi': 0,
            'with_title': 0,
            'with_year': 0,
            'with_authors': 0,
            'high_confidence': 0,  # >= 0.7
            'medium_confidence': 0,  # 0.4-0.7
            'low_confidence': 0,  # < 0.4
            'by_method': {}
        }
        
        for citation in citations:
            result = self.parser.parse(citation)
            results.append(result)
            
            if result.doi:
                stats['with_doi'] += 1
            if result.title:
                stats['with_title'] += 1
            if result.year:
                stats['with_year'] += 1
            if result.authors:
                stats['with_authors'] += 1
            
            if result.confidence >= 0.7:
                stats['high_confidence'] += 1
            elif result.confidence >= 0.4:
                stats['medium_confidence'] += 1
            else:
                stats['low_confidence'] += 1
            
            method = result.parse_method
            stats['by_method'][method] = stats['by_method'].get(method, 0) + 1
        
        return results, stats


# Convenience function
def parse_citation(text: str) -> ParsedCitation:
    """Parse a single citation string."""
    return CitationParser().parse(text)


if __name__ == '__main__':
    # Test with various citation formats
    test_citations = [
        # APA
        "Smith, J. A., & Jones, B. C. (2020). The effects of daylight on cognitive performance. Journal of Environmental Psychology, 45(3), 234-256.",
        # MLA
        'Ulrich, Roger S. "View through a Window May Influence Recovery from Surgery." Science, vol. 224, no. 4647, 1984, pp. 420-421.',
        # Chicago
        "Kaplan, Rachel. The Nature of the View from Home. Environment and Behavior 33, no. 4 (2001): 507-542.",
        # Informal
        "Williams Goldhagen, S. Welcome to Your World: How the Built Environment Shapes our Lives; HarperCollins: New York, NY, USA, 2017.",
        # With DOI
        "Ledoux, J.E. Cognitive-Emotional Interactions in the Brain. Cogn. Emot. 2008, 3, 267-289. https://doi.org/10.1080/02699930802132356",
        # Very informal
        "Glass & Singer 1972 Urban Stress experiments",
    ]
    
    parser = CitationParser()
    for citation in test_citations:
        result = parser.parse(citation)
        print(f"\n{'='*60}")
        print(f"Input: {citation[:80]}...")
        print(f"Method: {result.parse_method}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Authors: {result.authors}")
        print(f"Title: {result.title}")
        print(f"Year: {result.year}")
        print(f"Venue: {result.venue}")
        print(f"DOI: {result.doi}")
