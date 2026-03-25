#!/usr/bin/env python3
"""
Zotero Connector for Article Finder v3

Reads metadata and PDF paths directly from local Zotero database.
Tracks sync state to detect new additions.

Usage:
    from ingest.zotero_connector import ZoteroConnector

    zotero = ZoteroConnector()
    papers = zotero.get_all_papers()
    new_papers = zotero.get_new_papers_since_last_sync()
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# Default Zotero paths on macOS
DEFAULT_ZOTERO_DIR = Path.home() / "Zotero"
DEFAULT_DB_PATH = DEFAULT_ZOTERO_DIR / "zotero.sqlite"
DEFAULT_STORAGE_PATH = DEFAULT_ZOTERO_DIR / "storage"

# State file to track sync
SYNC_STATE_FILE = Path(__file__).parent.parent / "data" / "zotero_sync_state.json"


class ZoteroConnector:
    """
    Connect to local Zotero database and extract paper metadata.
    """

    # Item types we care about (academic papers)
    PAPER_TYPES = (
        'journalArticle',
        'conferencePaper',
        'book',
        'bookSection',
        'thesis',
        'report',
        'preprint',
    )

    def __init__(
        self,
        zotero_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        storage_path: Optional[Path] = None,
        state_file: Optional[Path] = None
    ):
        """
        Initialize Zotero connector.

        Args:
            zotero_dir: Base Zotero directory (defaults to ~/Zotero)
            db_path: Path to zotero.sqlite (defaults to ~/Zotero/zotero.sqlite)
            storage_path: Path to storage folder (defaults to ~/Zotero/storage)
            state_file: Path to sync state file
        """
        self.zotero_dir = zotero_dir or DEFAULT_ZOTERO_DIR
        self.db_path = db_path or DEFAULT_DB_PATH
        self.storage_path = storage_path or DEFAULT_STORAGE_PATH
        self.state_file = state_file or SYNC_STATE_FILE

        if not self.db_path.exists():
            raise FileNotFoundError(f"Zotero database not found: {self.db_path}")

        if not self.storage_path.exists():
            raise FileNotFoundError(f"Zotero storage not found: {self.storage_path}")

        # Cache for field mappings
        self._field_map: Optional[Dict[int, str]] = None
        self._type_map: Optional[Dict[int, str]] = None
        self._creator_type_map: Optional[Dict[int, str]] = None

    def _connect(self) -> sqlite3.Connection:
        """Get a read-only connection to Zotero database."""
        # Use URI mode for read-only access (won't conflict with Zotero)
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_field_map(self, conn: sqlite3.Connection) -> Dict[int, str]:
        """Load field ID to name mapping."""
        if self._field_map is None:
            rows = conn.execute("SELECT fieldID, fieldName FROM fields").fetchall()
            self._field_map = {row['fieldID']: row['fieldName'] for row in rows}
        return self._field_map

    def _load_type_map(self, conn: sqlite3.Connection) -> Dict[int, str]:
        """Load item type ID to name mapping."""
        if self._type_map is None:
            rows = conn.execute("SELECT itemTypeID, typeName FROM itemTypes").fetchall()
            self._type_map = {row['itemTypeID']: row['typeName'] for row in rows}
        return self._type_map

    def _load_creator_type_map(self, conn: sqlite3.Connection) -> Dict[int, str]:
        """Load creator type ID to name mapping."""
        if self._creator_type_map is None:
            rows = conn.execute("SELECT creatorTypeID, creatorType FROM creatorTypes").fetchall()
            self._creator_type_map = {row['creatorTypeID']: row['creatorType'] for row in rows}
        return self._creator_type_map

    def _get_item_metadata(self, conn: sqlite3.Connection, item_id: int) -> Dict[str, Any]:
        """Get all metadata fields for an item."""
        field_map = self._load_field_map(conn)

        rows = conn.execute("""
            SELECT id.fieldID, idv.value
            FROM itemData id
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE id.itemID = ?
        """, (item_id,)).fetchall()

        metadata = {}
        for row in rows:
            field_name = field_map.get(row['fieldID'], f"field_{row['fieldID']}")
            metadata[field_name] = row['value']

        return metadata

    def _get_item_creators(self, conn: sqlite3.Connection, item_id: int) -> List[Dict[str, str]]:
        """Get all creators (authors) for an item."""
        creator_type_map = self._load_creator_type_map(conn)

        rows = conn.execute("""
            SELECT c.firstName, c.lastName, ic.creatorTypeID, ic.orderIndex
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """, (item_id,)).fetchall()

        creators = []
        for row in rows:
            creators.append({
                'firstName': row['firstName'] or '',
                'lastName': row['lastName'] or '',
                'creatorType': creator_type_map.get(row['creatorTypeID'], 'author')
            })

        return creators

    def _get_pdf_attachment(self, conn: sqlite3.Connection, item_id: int) -> Optional[Dict[str, Any]]:
        """Get PDF attachment info for an item."""
        row = conn.execute("""
            SELECT ia.itemID, ia.path, i.key as attachmentKey
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ?
              AND ia.contentType = 'application/pdf'
              AND ia.path IS NOT NULL
            LIMIT 1
        """, (item_id,)).fetchone()

        if not row:
            return None

        # Parse storage path
        # Format is "storage:filename.pdf" -> ~/Zotero/storage/{key}/filename.pdf
        path_str = row['path']
        if path_str.startswith('storage:'):
            filename = path_str[8:]  # Remove "storage:" prefix
            full_path = self.storage_path / row['attachmentKey'] / filename

            return {
                'attachment_id': row['itemID'],
                'attachment_key': row['attachmentKey'],
                'filename': filename,
                'path': str(full_path),
                'exists': full_path.exists()
            }

        return None

    def _format_authors(self, creators: List[Dict[str, str]]) -> List[str]:
        """
        Format creators list as a list of author name strings.

        Returns list of strings like ["LastName, FirstName", ...].
        This format matches the AF database standard used by bibliographer
        and pdf_catalog.
        """
        authors = [c for c in creators if c['creatorType'] == 'author']
        if not authors:
            authors = creators  # Fall back to all creators

        result = []
        for a in authors:
            if a['lastName'] and a['firstName']:
                name = f"{a['lastName']}, {a['firstName']}"
            elif a['lastName']:
                name = a['lastName']
            elif a['firstName']:
                name = a['firstName']
            else:
                continue

            result.append(name)

        return result

    def _parse_year(self, date_str: Optional[str]) -> Optional[int]:
        """Extract year from Zotero date string."""
        if not date_str:
            return None

        # Try to find 4-digit year
        import re
        match = re.search(r'\b(19|20)\d{2}\b', date_str)
        if match:
            return int(match.group())

        return None

    def get_paper(self, item_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single paper by Zotero item ID.

        Returns dict with Article Finder compatible fields.
        """
        with self._connect() as conn:
            type_map = self._load_type_map(conn)

            # Get item
            row = conn.execute("""
                SELECT itemID, itemTypeID, dateAdded, dateModified, key
                FROM items
                WHERE itemID = ?
                  AND itemID NOT IN (SELECT itemID FROM deletedItems)
            """, (item_id,)).fetchone()

            if not row:
                return None

            item_type = type_map.get(row['itemTypeID'], 'unknown')
            if item_type not in self.PAPER_TYPES:
                return None

            # Get metadata
            metadata = self._get_item_metadata(conn, item_id)
            creators = self._get_item_creators(conn, item_id)
            pdf = self._get_pdf_attachment(conn, item_id)

            return self._build_paper_dict(row, item_type, metadata, creators, pdf)

    def _build_paper_dict(
        self,
        row: sqlite3.Row,
        item_type: str,
        metadata: Dict[str, Any],
        creators: List[Dict[str, str]],
        pdf: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build Article Finder compatible paper dict."""
        paper = {
            'zotero_item_id': row['itemID'],
            'zotero_key': row['key'],
            'zotero_type': item_type,
            'zotero_added': row['dateAdded'],
            'zotero_modified': row['dateModified'],

            # Standard Article Finder fields
            'title': metadata.get('title', ''),
            'abstract': metadata.get('abstractNote', ''),
            'doi': metadata.get('DOI'),
            'url': metadata.get('url'),
            'year': self._parse_year(metadata.get('date')),
            'venue': metadata.get('publicationTitle') or metadata.get('conferenceName') or metadata.get('publisher'),
            'authors': self._format_authors(creators),

            # Additional metadata
            'volume': metadata.get('volume'),
            'issue': metadata.get('issue'),
            'pages': metadata.get('pages'),
            'issn': metadata.get('ISSN'),
            'language': metadata.get('language'),

            # Source tracking
            'source': 'zotero',
            'ingest_method': 'zotero_connector',
        }

        # Add PDF info if available
        if pdf:
            paper['pdf_path'] = pdf['path']
            paper['pdf_exists'] = pdf['exists']
            paper['zotero_attachment_key'] = pdf['attachment_key']

        return paper

    def get_all_papers(
        self,
        item_types: Optional[tuple] = None,
        with_pdf_only: bool = False,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all papers from Zotero library.

        Args:
            item_types: Tuple of item types to include (defaults to PAPER_TYPES)
            with_pdf_only: Only return papers that have PDF attachments
            limit: Maximum number of papers to return

        Returns:
            List of paper dicts
        """
        item_types = item_types or self.PAPER_TYPES

        with self._connect() as conn:
            type_map = self._load_type_map(conn)

            # Get type IDs for our paper types
            type_ids = [tid for tid, name in type_map.items() if name in item_types]

            if not type_ids:
                return []

            placeholders = ','.join('?' * len(type_ids))
            query = f"""
                SELECT itemID, itemTypeID, dateAdded, dateModified, key
                FROM items
                WHERE itemTypeID IN ({placeholders})
                  AND itemID NOT IN (SELECT itemID FROM deletedItems)
                ORDER BY dateAdded DESC
            """

            if limit:
                query += f" LIMIT {limit}"

            rows = conn.execute(query, type_ids).fetchall()

            papers = []
            for row in rows:
                item_type = type_map.get(row['itemTypeID'], 'unknown')
                metadata = self._get_item_metadata(conn, row['itemID'])
                creators = self._get_item_creators(conn, row['itemID'])
                pdf = self._get_pdf_attachment(conn, row['itemID'])

                if with_pdf_only and not pdf:
                    continue

                paper = self._build_paper_dict(row, item_type, metadata, creators, pdf)
                papers.append(paper)

            return papers

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the Zotero library."""
        with self._connect() as conn:
            type_map = self._load_type_map(conn)

            # Count by type
            rows = conn.execute("""
                SELECT itemTypeID, COUNT(*) as count
                FROM items
                WHERE itemID NOT IN (SELECT itemID FROM deletedItems)
                GROUP BY itemTypeID
            """).fetchall()

            by_type = {}
            total_papers = 0
            for row in rows:
                type_name = type_map.get(row['itemTypeID'], 'unknown')
                by_type[type_name] = row['count']
                if type_name in self.PAPER_TYPES:
                    total_papers += row['count']

            # Count PDFs
            pdf_count = conn.execute("""
                SELECT COUNT(*) FROM itemAttachments
                WHERE contentType = 'application/pdf'
                  AND path IS NOT NULL
            """).fetchone()[0]

            # Recent additions
            recent = conn.execute("""
                SELECT COUNT(*) FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE it.typeName IN (?, ?, ?, ?, ?, ?, ?)
                  AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
                  AND i.dateAdded >= date('now', '-7 days')
            """, self.PAPER_TYPES).fetchone()[0]

            return {
                'total_papers': total_papers,
                'pdf_attachments': pdf_count,
                'by_type': by_type,
                'added_last_7_days': recent,
                'database_path': str(self.db_path),
                'storage_path': str(self.storage_path)
            }

    # =========================================================================
    # Sync tracking - detect new papers
    # =========================================================================

    def _load_sync_state(self) -> Dict[str, Any]:
        """Load sync state from file."""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {'last_sync': None, 'last_item_id': 0}

    def _save_sync_state(self, state: Dict[str, Any]) -> None:
        """Save sync state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def get_new_papers_since_last_sync(self) -> List[Dict[str, Any]]:
        """
        Get papers added since the last sync.

        This tracks the last sync time and returns only new additions.
        Call mark_synced() after processing to update the sync marker.
        """
        state = self._load_sync_state()
        last_sync = state.get('last_sync')

        with self._connect() as conn:
            type_map = self._load_type_map(conn)
            type_ids = [tid for tid, name in type_map.items() if name in self.PAPER_TYPES]

            if not type_ids:
                return []

            placeholders = ','.join('?' * len(type_ids))

            if last_sync:
                query = f"""
                    SELECT itemID, itemTypeID, dateAdded, dateModified, key
                    FROM items
                    WHERE itemTypeID IN ({placeholders})
                      AND itemID NOT IN (SELECT itemID FROM deletedItems)
                      AND dateAdded > ?
                    ORDER BY dateAdded ASC
                """
                rows = conn.execute(query, (*type_ids, last_sync)).fetchall()
            else:
                # First sync - get all papers
                query = f"""
                    SELECT itemID, itemTypeID, dateAdded, dateModified, key
                    FROM items
                    WHERE itemTypeID IN ({placeholders})
                      AND itemID NOT IN (SELECT itemID FROM deletedItems)
                    ORDER BY dateAdded ASC
                """
                rows = conn.execute(query, type_ids).fetchall()

            papers = []
            for row in rows:
                item_type = type_map.get(row['itemTypeID'], 'unknown')
                metadata = self._get_item_metadata(conn, row['itemID'])
                creators = self._get_item_creators(conn, row['itemID'])
                pdf = self._get_pdf_attachment(conn, row['itemID'])

                paper = self._build_paper_dict(row, item_type, metadata, creators, pdf)
                papers.append(paper)

            return papers

    def get_papers_added_since(self, since: str) -> List[Dict[str, Any]]:
        """
        Get papers added since a specific datetime.

        Args:
            since: ISO format datetime string (e.g., '2025-01-01' or '2025-01-01 12:00:00')
        """
        with self._connect() as conn:
            type_map = self._load_type_map(conn)
            type_ids = [tid for tid, name in type_map.items() if name in self.PAPER_TYPES]

            if not type_ids:
                return []

            placeholders = ','.join('?' * len(type_ids))
            query = f"""
                SELECT itemID, itemTypeID, dateAdded, dateModified, key
                FROM items
                WHERE itemTypeID IN ({placeholders})
                  AND itemID NOT IN (SELECT itemID FROM deletedItems)
                  AND dateAdded >= ?
                ORDER BY dateAdded DESC
            """

            rows = conn.execute(query, (*type_ids, since)).fetchall()

            papers = []
            for row in rows:
                item_type = type_map.get(row['itemTypeID'], 'unknown')
                metadata = self._get_item_metadata(conn, row['itemID'])
                creators = self._get_item_creators(conn, row['itemID'])
                pdf = self._get_pdf_attachment(conn, row['itemID'])

                paper = self._build_paper_dict(row, item_type, metadata, creators, pdf)
                papers.append(paper)

            return papers

    def mark_synced(self) -> None:
        """Mark current time as last sync point."""
        state = {
            'last_sync': datetime.utcnow().isoformat(),
            'synced_at': datetime.now().isoformat()
        }
        self._save_sync_state(state)
        logger.info(f"Marked Zotero sync at {state['last_sync']}")

    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        state = self._load_sync_state()

        # Count pending
        pending = self.get_new_papers_since_last_sync()

        return {
            'last_sync': state.get('last_sync'),
            'pending_papers': len(pending),
            'state_file': str(self.state_file)
        }


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Zotero Connector for Article Finder')
    parser.add_argument('--stats', action='store_true', help='Show Zotero library statistics')
    parser.add_argument('--list', type=int, metavar='N', help='List N recent papers')
    parser.add_argument('--new', action='store_true', help='Show papers added since last sync')
    parser.add_argument('--since', type=str, help='Show papers added since date (YYYY-MM-DD)')
    parser.add_argument('--sync-status', action='store_true', help='Show sync status')
    parser.add_argument('--mark-synced', action='store_true', help='Mark current time as synced')
    parser.add_argument('--with-pdf', action='store_true', help='Only show papers with PDFs')

    args = parser.parse_args()

    try:
        zotero = ZoteroConnector()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure Zotero is installed and has been run at least once.")
        exit(1)

    if args.stats:
        stats = zotero.get_stats()
        print("\nZotero Library Statistics:")
        print(f"  Total papers: {stats['total_papers']}")
        print(f"  PDF attachments: {stats['pdf_attachments']}")
        print(f"  Added last 7 days: {stats['added_last_7_days']}")
        print(f"\n  Database: {stats['database_path']}")
        print(f"  Storage: {stats['storage_path']}")
        print("\n  By type:")
        for type_name, count in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
            if count > 0:
                print(f"    {type_name}: {count}")

    elif args.list:
        papers = zotero.get_all_papers(limit=args.list, with_pdf_only=args.with_pdf)
        print(f"\n{len(papers)} papers:")
        for p in papers:
            pdf_marker = "📄" if p.get('pdf_exists') else "  "
            year = p.get('year') or '????'
            print(f"  {pdf_marker} [{year}] {p['title'][:60]}...")
            if p.get('doi'):
                print(f"       DOI: {p['doi']}")

    elif args.new:
        papers = zotero.get_new_papers_since_last_sync()
        status = zotero.get_sync_status()
        print(f"\nPapers since last sync ({status['last_sync'] or 'never'}):")
        print(f"  Found: {len(papers)}")
        for p in papers[:10]:
            print(f"  - [{p.get('year') or '????'}] {p['title'][:50]}...")
        if len(papers) > 10:
            print(f"  ... and {len(papers) - 10} more")

    elif args.since:
        papers = zotero.get_papers_added_since(args.since)
        print(f"\nPapers added since {args.since}: {len(papers)}")
        for p in papers[:20]:
            pdf_marker = "📄" if p.get('pdf_exists') else "  "
            print(f"  {pdf_marker} [{p.get('year') or '????'}] {p['title'][:55]}...")

    elif args.sync_status:
        status = zotero.get_sync_status()
        print("\nZotero Sync Status:")
        print(f"  Last sync: {status['last_sync'] or 'Never'}")
        print(f"  Pending papers: {status['pending_papers']}")
        print(f"  State file: {status['state_file']}")

    elif args.mark_synced:
        zotero.mark_synced()
        print("Marked current time as synced.")

    else:
        parser.print_help()
