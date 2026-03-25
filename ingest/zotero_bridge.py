# Version: 3.2.3
"""
Article Finder v3.2.3 - Zotero Bridge
Two-way integration with Zotero for PDF acquisition.

OUTBOUND: Export papers needing PDFs → Zotero format
INBOUND: Import PDFs from local Zotero storage

This leverages Zotero's "Find Available PDF" feature which can use
university library authentication (UCSD SSO) to acquire paywalled papers.
"""

import os
import re
import json
import shutil
import sqlite3
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ZoteroItem:
    """Represents a Zotero library item."""
    key: str
    title: str
    item_type: str
    doi: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    abstract: Optional[str] = None
    pdf_paths: List[Path] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'zotero_key': self.key,
            'title': self.title,
            'item_type': self.item_type,
            'doi': self.doi,
            'authors': self.authors,
            'year': self.year,
            'abstract': self.abstract,
            'pdf_count': len(self.pdf_paths)
        }


@dataclass 
class ImportStats:
    """Statistics from a Zotero import operation."""
    zotero_items_found: int = 0
    zotero_pdfs_found: int = 0
    matched_to_af_papers: int = 0
    pdfs_copied: int = 0
    pdfs_already_present: int = 0
    match_failures: int = 0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'zotero_items_found': self.zotero_items_found,
            'zotero_pdfs_found': self.zotero_pdfs_found,
            'matched_to_af_papers': self.matched_to_af_papers,
            'pdfs_copied': self.pdfs_copied,
            'pdfs_already_present': self.pdfs_already_present,
            'match_failures': self.match_failures,
            'errors': self.errors[:20]  # Limit error list
        }


class ZoteroLocalReader:
    """
    Reads from local Zotero installation.
    
    Zotero stores data in:
    - ~/Zotero/zotero.sqlite (metadata database)
    - ~/Zotero/storage/<KEY>/ (attachment folders with PDFs)
    """
    
    DEFAULT_ZOTERO_DIR = Path.home() / "Zotero"
    
    def __init__(self, zotero_dir: Optional[Path] = None):
        """
        Args:
            zotero_dir: Path to Zotero data directory. 
                        Defaults to ~/Zotero on Mac/Linux, 
                        or checks common Windows locations.
        """
        self.zotero_dir = self._find_zotero_dir(zotero_dir)
        self.db_path = self.zotero_dir / "zotero.sqlite"
        self.storage_dir = self.zotero_dir / "storage"
        
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Zotero database not found at {self.db_path}. "
                f"Is Zotero installed? Is the path correct?"
            )
    
    def _find_zotero_dir(self, zotero_dir: Optional[Path]) -> Path:
        """Find Zotero data directory."""
        if zotero_dir:
            return Path(zotero_dir)
        
        # Check common locations
        candidates = [
            Path.home() / "Zotero",  # Mac/Linux default
            Path.home() / "Documents" / "Zotero",  # Some configs
            Path(os.environ.get("APPDATA", "")) / "Zotero" / "Zotero",  # Windows
        ]
        
        for candidate in candidates:
            if (candidate / "zotero.sqlite").exists():
                return candidate
        
        # Default to standard location
        return self.DEFAULT_ZOTERO_DIR
    
    def get_all_items(self, item_types: Optional[List[str]] = None) -> List[ZoteroItem]:
        """
        Get all items from Zotero library.
        
        Args:
            item_types: Filter by item types (e.g., ['journalArticle', 'book'])
                       If None, gets all document types.
        
        Returns:
            List of ZoteroItem objects
        """
        # Need to copy database because Zotero may have it locked
        temp_db = self.zotero_dir / "zotero_temp_copy.sqlite"
        shutil.copy2(self.db_path, temp_db)
        
        try:
            conn = sqlite3.connect(temp_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get items with their fields
            query = """
                SELECT 
                    i.itemID,
                    i.key,
                    it.typeName as itemType,
                    (SELECT value FROM itemData id 
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'title'
                     LIMIT 1) as title,
                    (SELECT value FROM itemData id 
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'DOI'
                     LIMIT 1) as doi,
                    (SELECT value FROM itemData id 
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'abstractNote'
                     LIMIT 1) as abstract,
                    (SELECT value FROM itemData id 
                     JOIN itemDataValues idv ON id.valueID = idv.valueID
                     JOIN fields f ON id.fieldID = f.fieldID
                     WHERE id.itemID = i.itemID AND f.fieldName = 'date'
                     LIMIT 1) as date
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
                AND it.typeName NOT IN ('attachment', 'note')
            """
            
            if item_types:
                placeholders = ','.join('?' * len(item_types))
                query += f" AND it.typeName IN ({placeholders})"
                cursor.execute(query, item_types)
            else:
                cursor.execute(query)
            
            items = []
            for row in cursor.fetchall():
                item = ZoteroItem(
                    key=row['key'],
                    title=row['title'] or "Untitled",
                    item_type=row['itemType'],
                    doi=self._normalize_doi(row['doi']),
                    abstract=row['abstract'],
                    year=self._extract_year(row['date'])
                )
                
                # Get authors
                item.authors = self._get_authors(cursor, row['itemID'])
                
                # Get PDF attachments
                item.pdf_paths = self._get_pdf_attachments(cursor, row['itemID'])
                
                items.append(item)
            
            conn.close()
            return items
            
        finally:
            # Clean up temp copy
            if temp_db.exists():
                temp_db.unlink()
    
    def _get_authors(self, cursor, item_id: int) -> List[str]:
        """Get author names for an item."""
        cursor.execute("""
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ? AND ct.creatorType = 'author'
            ORDER BY ic.orderIndex
        """, (item_id,))
        
        authors = []
        for row in cursor.fetchall():
            if row['lastName']:
                if row['firstName']:
                    authors.append(f"{row['lastName']}, {row['firstName']}")
                else:
                    authors.append(row['lastName'])
        return authors
    
    def _get_pdf_attachments(self, cursor, item_id: int) -> List[Path]:
        """Get PDF file paths for an item."""
        cursor.execute("""
            SELECT i.key, ia.path
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ?
            AND ia.contentType = 'application/pdf'
        """, (item_id,))
        
        pdfs = []
        for row in cursor.fetchall():
            attachment_key = row['key']
            stored_path = row['path']
            
            if stored_path:
                # Path format is usually "storage:filename.pdf"
                if stored_path.startswith('storage:'):
                    filename = stored_path[8:]  # Remove "storage:" prefix
                    pdf_path = self.storage_dir / attachment_key / filename
                else:
                    # Might be absolute path (linked file)
                    pdf_path = Path(stored_path)
                
                if pdf_path.exists():
                    pdfs.append(pdf_path)
        
        return pdfs
    
    def _normalize_doi(self, doi: Optional[str]) -> Optional[str]:
        """Normalize DOI to standard format."""
        if not doi:
            return None
        
        doi = doi.strip().lower()
        
        # Remove URL prefixes
        for prefix in ['https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'doi:']:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        
        if doi.startswith('10.'):
            return doi
        return None
    
    def _extract_year(self, date_str: Optional[str]) -> Optional[int]:
        """Extract year from date string."""
        if not date_str:
            return None
        
        # Try to find 4-digit year
        match = re.search(r'\b(19|20)\d{2}\b', date_str)
        if match:
            return int(match.group())
        return None
    
    def get_items_with_pdfs(self) -> List[ZoteroItem]:
        """Get only items that have PDF attachments."""
        all_items = self.get_all_items()
        return [item for item in all_items if item.pdf_paths]
    
    def get_items_without_pdfs(self) -> List[ZoteroItem]:
        """Get items that don't have PDF attachments."""
        all_items = self.get_all_items()
        return [item for item in all_items if not item.pdf_paths]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about local Zotero library."""
        items = self.get_all_items()
        
        with_doi = sum(1 for i in items if i.doi)
        with_pdf = sum(1 for i in items if i.pdf_paths)
        total_pdfs = sum(len(i.pdf_paths) for i in items)
        
        type_counts = {}
        for item in items:
            type_counts[item.item_type] = type_counts.get(item.item_type, 0) + 1
        
        return {
            'total_items': len(items),
            'items_with_doi': with_doi,
            'items_with_pdf': with_pdf,
            'total_pdf_files': total_pdfs,
            'items_by_type': type_counts,
            'zotero_dir': str(self.zotero_dir),
            'storage_dir_exists': self.storage_dir.exists()
        }


class ZoteroImporter:
    """
    Imports PDFs from local Zotero into Article Finder.
    
    Matches Zotero items to Article Finder papers by:
    1. DOI (exact match)
    2. Title (fuzzy match)
    3. Authors + Year (backup)
    """
    
    def __init__(
        self,
        database,
        zotero_dir: Optional[Path] = None,
        pdf_output_dir: Optional[Path] = None
    ):
        """
        Args:
            database: Article Finder database instance
            zotero_dir: Path to Zotero data directory
            pdf_output_dir: Where to copy PDFs (default: data/pdfs/)
        """
        self.db = database
        self.reader = ZoteroLocalReader(zotero_dir)
        self.pdf_dir = pdf_output_dir or Path('data/pdfs')
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        
        # Build lookup indices for matching
        self._doi_index: Dict[str, str] = {}  # doi -> paper_id
        self._title_index: Dict[str, str] = {}  # normalized_title -> paper_id
        self._build_indices()
    
    def _build_indices(self):
        """Build indices for fast matching."""
        papers = self.db.search_papers(limit=50000)
        
        for paper in papers:
            paper_id = paper['paper_id']
            
            if paper.get('doi'):
                doi = paper['doi'].lower().strip()
                self._doi_index[doi] = paper_id
            
            if paper.get('title'):
                normalized = self._normalize_title(paper['title'])
                self._title_index[normalized] = paper_id
        
        logger.info(f"Built indices: {len(self._doi_index)} DOIs, {len(self._title_index)} titles")
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for matching."""
        # Lowercase, remove punctuation, collapse whitespace
        normalized = title.lower()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = ' '.join(normalized.split())
        return normalized
    
    def _match_to_paper(self, zotero_item: ZoteroItem) -> Optional[str]:
        """
        Try to match a Zotero item to an Article Finder paper.
        
        Returns paper_id if matched, None otherwise.
        """
        # Try DOI match first (most reliable)
        if zotero_item.doi:
            doi = zotero_item.doi.lower().strip()
            if doi in self._doi_index:
                return self._doi_index[doi]
        
        # Try title match
        if zotero_item.title:
            normalized = self._normalize_title(zotero_item.title)
            if normalized in self._title_index:
                return self._title_index[normalized]
            
            # Try fuzzy title match (80% of words match)
            for indexed_title, paper_id in self._title_index.items():
                if self._titles_similar(normalized, indexed_title):
                    return paper_id
        
        return None
    
    def _titles_similar(self, title1: str, title2: str, threshold: float = 0.85) -> bool:
        """
        Check if two normalized titles are similar enough.

        Fixed 2026-02-11: Now requires bidirectional matching and minimum word count
        to prevent false matches on short/generic titles.
        """
        words1 = set(title1.split())
        words2 = set(title2.split())

        if not words1 or not words2:
            return False

        # Require minimum 5 words in both titles to use fuzzy matching
        if len(words1) < 5 or len(words2) < 5:
            return False

        intersection = len(words1 & words2)

        # Require high match in BOTH directions (Jaccard-like)
        ratio1 = intersection / len(words1)
        ratio2 = intersection / len(words2)

        # Both ratios must exceed threshold
        return ratio1 >= threshold and ratio2 >= threshold
    
    def _safe_filename(self, doi: Optional[str], title: str) -> str:
        """Generate safe filename for PDF."""
        if doi:
            # Use DOI-based name
            safe = doi.replace('/', '_').replace(':', '_')
            return f"{safe}.pdf"
        else:
            # Use title-based name
            safe = re.sub(r'[^\w\s-]', '', title)[:50]
            safe = re.sub(r'\s+', '_', safe)
            return f"{safe}.pdf"

    def _create_paper_from_zotero(self, zotero_item: ZoteroItem, dry_run: bool = False) -> Optional[str]:
        """
        Create a new Article Finder paper from a Zotero item.

        Added 2026-02-11: Enables importing PDFs that don't match existing papers.

        Args:
            zotero_item: The Zotero item to create a paper from
            dry_run: If True, just log what would happen

        Returns:
            The new paper_id if created, None otherwise
        """
        # Generate paper_id from DOI or Zotero key
        if zotero_item.doi:
            paper_id = f"doi:{zotero_item.doi}"
        else:
            paper_id = f"zotero:{zotero_item.key}"

        if dry_run:
            logger.info(f"Would create new paper: {paper_id} - {zotero_item.title[:60]}...")
            return paper_id

        try:
            # Create paper record
            paper = {
                'paper_id': paper_id,
                'doi': zotero_item.doi,
                'title': zotero_item.title,
                'authors': ', '.join(zotero_item.authors) if zotero_item.authors else None,
                'year': zotero_item.year,
                'abstract': zotero_item.abstract,
                'source': 'zotero',
                'ingest_method': 'zotero_import',
                'status': 'candidate',
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat(),
            }

            self.db.add_paper(paper)

            # Add to indices for future matching
            if zotero_item.doi:
                self._doi_index[zotero_item.doi.lower().strip()] = paper_id
            if zotero_item.title:
                self._title_index[self._normalize_title(zotero_item.title)] = paper_id

            logger.info(f"Created new paper: {paper_id}")
            return paper_id

        except Exception as e:
            logger.error(f"Failed to create paper from Zotero item {zotero_item.key}: {e}")
            return None
    
    def _copy_pdf(self, source: Path, paper_id: str, doi: Optional[str], title: str) -> Path:
        """Copy PDF to Article Finder storage."""
        filename = self._safe_filename(doi, title)
        dest = self.pdf_dir / filename
        
        # Handle duplicates
        if dest.exists():
            # Check if same file
            source_hash = hashlib.md5(source.read_bytes()).hexdigest()
            dest_hash = hashlib.md5(dest.read_bytes()).hexdigest()
            if source_hash == dest_hash:
                return dest  # Same file, no need to copy
            
            # Different file, add suffix
            stem = dest.stem
            suffix = 1
            while dest.exists():
                dest = self.pdf_dir / f"{stem}_{suffix}.pdf"
                suffix += 1
        
        shutil.copy2(source, dest)
        return dest
    
    def import_all(self, dry_run: bool = False, create_new: bool = True) -> ImportStats:
        """
        Import all PDFs from Zotero that match Article Finder papers.

        Args:
            dry_run: If True, don't actually copy files, just report what would happen
            create_new: If True, create new AF papers for unmatched Zotero items (default: True)

        Returns:
            ImportStats with results
        """
        stats = ImportStats()

        # Get Zotero items with PDFs
        zotero_items = self.reader.get_items_with_pdfs()
        stats.zotero_items_found = len(self.reader.get_all_items())
        stats.zotero_pdfs_found = len(zotero_items)

        logger.info(f"Found {stats.zotero_pdfs_found} Zotero items with PDFs")

        for zotero_item in zotero_items:
            paper_id = self._match_to_paper(zotero_item)

            if not paper_id:
                if create_new:
                    # Create new paper from Zotero item
                    paper_id = self._create_paper_from_zotero(zotero_item, dry_run)
                    if paper_id:
                        stats.matched_to_af_papers += 1  # Count as matched (newly created)
                    else:
                        stats.match_failures += 1
                        continue
                else:
                    stats.match_failures += 1
                    continue
            
            stats.matched_to_af_papers += 1
            
            # Get the paper record
            paper = self.db.get_paper(paper_id)
            if not paper:
                continue
            
            # Check if paper already has PDF
            if paper.get('pdf_path') and Path(paper['pdf_path']).exists():
                stats.pdfs_already_present += 1
                continue
            
            # Copy the first PDF (usually there's only one)
            source_pdf = zotero_item.pdf_paths[0]
            
            if dry_run:
                logger.info(f"Would copy: {source_pdf.name} → {paper_id}")
                stats.pdfs_copied += 1
            else:
                try:
                    dest_pdf = self._copy_pdf(
                        source_pdf, 
                        paper_id,
                        paper.get('doi'),
                        paper.get('title', 'unknown')
                    )
                    
                    # Update paper record
                    paper['pdf_path'] = str(dest_pdf)
                    paper['pdf_sha256'] = hashlib.sha256(dest_pdf.read_bytes()).hexdigest()
                    paper['pdf_bytes'] = dest_pdf.stat().st_size
                    paper['pdf_source'] = 'zotero_import'
                    paper['updated_at'] = datetime.utcnow().isoformat()
                    self.db.add_paper(paper)
                    
                    stats.pdfs_copied += 1
                    logger.info(f"Copied: {source_pdf.name} → {dest_pdf.name}")
                    
                except Exception as e:
                    stats.errors.append(f"{paper_id}: {str(e)}")
                    logger.error(f"Failed to copy PDF for {paper_id}: {e}")
        
        return stats
    
    def find_unmatched_zotero_items(self) -> List[ZoteroItem]:
        """
        Find Zotero items that don't match any Article Finder paper.
        These could be added to Article Finder as new papers.
        """
        all_items = self.reader.get_all_items()
        unmatched = []
        
        for item in all_items:
            if not self._match_to_paper(item):
                unmatched.append(item)
        
        return unmatched


class ZoteroExporter:
    """
    Exports Article Finder papers to Zotero-importable formats.
    
    This enables the workflow:
    1. Export papers needing PDFs
    2. Import into Zotero
    3. Use "Find Available PDF" with library authentication
    4. Import PDFs back into Article Finder
    """
    
    def __init__(self, database):
        self.db = database
    
    def export_papers_needing_pdfs(
        self,
        output_path: Path,
        format: str = 'csv',
        limit: Optional[int] = None
    ) -> int:
        """
        Export papers that need PDFs to a Zotero-importable format.
        
        Args:
            output_path: Where to save the export
            format: 'csv' or 'ris' (Zotero can import both)
            limit: Max papers to export
            
        Returns:
            Number of papers exported
        """
        # Get papers without PDFs
        all_papers = self.db.search_papers(limit=10000)
        papers_needing_pdf = [
            p for p in all_papers 
            if not p.get('pdf_path') or not Path(p['pdf_path']).exists()
        ]
        
        # Prioritize by relevance score if available
        papers_needing_pdf.sort(
            key=lambda p: p.get('taxonomy_score', 0),
            reverse=True
        )
        
        if limit:
            papers_needing_pdf = papers_needing_pdf[:limit]
        
        if format == 'csv':
            return self._export_csv(papers_needing_pdf, output_path)
        elif format == 'ris':
            return self._export_ris(papers_needing_pdf, output_path)
        else:
            raise ValueError(f"Unknown format: {format}")
    
    def _export_csv(self, papers: List[Dict], output_path: Path) -> int:
        """Export to CSV format (Zotero can import via DOI lookup)."""
        import csv
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['DOI', 'Title', 'Authors', 'Year', 'Journal'])
            
            for paper in papers:
                doi = paper.get('doi', '')
                title = paper.get('title', '')
                authors = '; '.join(paper.get('authors', []))
                year = paper.get('year', '')
                venue = paper.get('venue', '')
                
                writer.writerow([doi, title, authors, year, venue])
        
        return len(papers)
    
    def _export_ris(self, papers: List[Dict], output_path: Path) -> int:
        """Export to RIS format (standard bibliographic format)."""
        with open(output_path, 'w', encoding='utf-8') as f:
            for paper in papers:
                f.write("TY  - JOUR\n")  # Journal article
                
                if paper.get('title'):
                    f.write(f"TI  - {paper['title']}\n")
                
                authors = paper.get('authors') or []
                if isinstance(authors, str):
                    try:
                        authors = json.loads(authors)
                    except Exception:
                        authors = [authors]
                for author in authors:
                    f.write(f"AU  - {author}\n")
                
                if paper.get('year'):
                    f.write(f"PY  - {paper['year']}\n")
                
                if paper.get('doi'):
                    f.write(f"DO  - {paper['doi']}\n")
                
                if paper.get('venue'):
                    f.write(f"JO  - {paper['venue']}\n")
                
                if paper.get('abstract'):
                    f.write(f"AB  - {paper['abstract']}\n")
                
                f.write("ER  - \n\n")
        
        return len(papers)
    
    def get_pdf_acquisition_status(self) -> Dict[str, Any]:
        """Get status of PDF acquisition efforts."""
        all_papers = self.db.search_papers(limit=10000)
        
        with_pdf = [p for p in all_papers if p.get('pdf_path') and Path(p['pdf_path']).exists()]
        without_pdf = [p for p in all_papers if not p.get('pdf_path') or not Path(p['pdf_path']).exists()]
        with_doi = [p for p in without_pdf if p.get('doi')]
        
        return {
            'total_papers': len(all_papers),
            'with_pdf': len(with_pdf),
            'without_pdf': len(without_pdf),
            'without_pdf_but_has_doi': len(with_doi),
            'pdf_coverage_pct': len(with_pdf) / len(all_papers) * 100 if all_papers else 0,
            'acquirable_via_doi': len(with_doi)
        }


# =============================================================================
# CLI Interface
# =============================================================================

def cmd_zotero_stats(args):
    """Show Zotero library statistics."""
    try:
        reader = ZoteroLocalReader(args.zotero_dir)
        stats = reader.get_stats()
        
        print("\n=== Zotero Library Statistics ===")
        print(f"Location: {stats['zotero_dir']}")
        print(f"Total items: {stats['total_items']}")
        print(f"Items with DOI: {stats['items_with_doi']}")
        print(f"Items with PDF: {stats['items_with_pdf']}")
        print(f"Total PDF files: {stats['total_pdf_files']}")
        
        print("\nItems by type:")
        for item_type, count in sorted(stats['items_by_type'].items(), key=lambda x: -x[1]):
            print(f"  {item_type}: {count}")
            
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    
    return 0


def cmd_zotero_import(args):
    """Import PDFs from Zotero."""
    from core.database import Database
    from config.loader import get
    
    db = Database(Path(get('paths.database', 'data/article_finder.db')))
    
    try:
        importer = ZoteroImporter(
            database=db,
            zotero_dir=args.zotero_dir,
            pdf_output_dir=args.pdf_dir
        )
        
        print(f"Scanning Zotero library at {importer.reader.zotero_dir}...")
        
        create_new = getattr(args, 'create_new', True)  # Default to True
        stats = importer.import_all(dry_run=args.dry_run, create_new=create_new)

        print("\n=== Import Results ===")
        print(f"Zotero items found: {stats.zotero_items_found}")
        print(f"Zotero items with PDFs: {stats.zotero_pdfs_found}")
        print(f"Matched/Created in Article Finder: {stats.matched_to_af_papers}")
        print(f"PDFs copied: {stats.pdfs_copied}")
        print(f"Already present: {stats.pdfs_already_present}")
        print(f"No match found: {stats.match_failures}")
        
        if stats.errors:
            print(f"\nErrors ({len(stats.errors)}):")
            for err in stats.errors[:5]:
                print(f"  {err}")
                
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    
    return 0


def cmd_zotero_export(args):
    """Export papers needing PDFs to Zotero format."""
    from core.database import Database
    from config.loader import get
    
    db = Database(Path(get('paths.database', 'data/article_finder.db')))
    exporter = ZoteroExporter(db)
    
    output_path = args.output or Path(f"papers_needing_pdfs.{args.format}")
    
    count = exporter.export_papers_needing_pdfs(
        output_path,
        format=args.format,
        limit=args.limit
    )
    
    print(f"Exported {count} papers to {output_path}")
    
    status = exporter.get_pdf_acquisition_status()
    print(f"\nPDF Status: {status['with_pdf']}/{status['total_papers']} papers have PDFs ({status['pdf_coverage_pct']:.1f}%)")
    print(f"Papers exportable (have DOI): {status['acquirable_via_doi']}")
    
    return 0


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Zotero Bridge for Article Finder')
    parser.add_argument('--zotero-dir', type=Path, help='Path to Zotero data directory')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    subparsers = parser.add_subparsers(dest='command')
    
    # Stats command
    p_stats = subparsers.add_parser('stats', help='Show Zotero library statistics')
    p_stats.set_defaults(func=cmd_zotero_stats)
    
    # Import command
    p_import = subparsers.add_parser('import', help='Import PDFs from Zotero')
    p_import.add_argument('--pdf-dir', type=Path, help='Where to copy PDFs')
    p_import.add_argument('--dry-run', action='store_true', help='Show what would be imported')
    p_import.add_argument('--create-new', action='store_true', default=True,
                          help='Create new AF papers for unmatched Zotero items (default: True)')
    p_import.add_argument('--no-create-new', action='store_false', dest='create_new',
                          help='Only import PDFs for existing AF papers')
    p_import.set_defaults(func=cmd_zotero_import)
    
    # Export command
    p_export = subparsers.add_parser('export', help='Export papers needing PDFs')
    p_export.add_argument('--output', '-o', type=Path, help='Output file path')
    p_export.add_argument('--format', choices=['csv', 'ris'], default='ris', help='Export format')
    p_export.add_argument('--limit', type=int, help='Max papers to export')
    p_export.set_defaults(func=cmd_zotero_export)
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    if not args.command:
        parser.print_help()
    else:
        exit(args.func(args))
