# Version: 3.2.4
"""
PDF watcher for inbox-style ingestion.

Scans a watched folder for PDFs, ingests them, optionally copies into
Article Finder storage, and archives processed files.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
import shutil
import time

from ingest.pdf_cataloger import PDFCataloger

logger = logging.getLogger(__name__)


class PDFWatcherService:
    """Process PDFs dropped into a watched folder."""

    def __init__(
        self,
        watch_dir: Path,
        database,
        resolver=None,
        storage_dir: Optional[Path] = None,
        archive_dir: Optional[Path] = None,
        source_name: str = "pdf_inbox",
        copy_to_storage: bool = True,
        extract_doi_from_text: bool = True,
        resolve_dois: bool = True,
        search_crossref: bool = True
    ):
        self.watch_dir = Path(watch_dir)
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self.source_name = source_name
        self.resolve_dois = resolve_dois
        self.search_crossref = search_crossref

        self.cataloger = PDFCataloger(
            database=database,
            doi_resolver=resolver,
            pdf_storage_dir=storage_dir,
            copy_to_storage=copy_to_storage,
            extract_doi_from_text=extract_doi_from_text
        )

    def process_once(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Process the current contents of the watch folder."""
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        pdfs = self._list_pdfs()

        if limit:
            pdfs = pdfs[:limit]

        self.cataloger.reset_stats()
        stats = self.cataloger.stats
        stats['total_pdfs'] = len(pdfs)
        stats['archived'] = 0
        stats['archive_failures'] = 0
        stats['source_dir'] = str(self.watch_dir)

        for pdf_path in pdfs:
            paper = self.cataloger.catalog_file(
                pdf_path,
                source_name=self.source_name,
                resolve_dois=self.resolve_dois,
                search_crossref=self.search_crossref
            )

            if paper and self.archive_dir and self._should_archive(pdf_path):
                if self._archive_pdf(pdf_path):
                    stats['archived'] += 1
                else:
                    stats['archive_failures'] += 1

        return stats

    def watch(self, interval_seconds: int = 30) -> None:
        """Continuously poll the watch folder."""
        while True:
            stats = self.process_once()
            processed = stats.get('processed', 0)
            if processed:
                logger.info(f"Processed {processed} PDFs from inbox")
            time.sleep(interval_seconds)

    def _list_pdfs(self) -> List[Path]:
        return sorted(self.watch_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime)

    def _should_archive(self, pdf_path: Path) -> bool:
        if not self.archive_dir:
            return False

        storage_dir = self.cataloger.pdf_storage_dir
        if storage_dir:
            try:
                pdf_path.resolve().relative_to(storage_dir.resolve())
                return False
            except Exception:
                pass

        return True

    def _archive_pdf(self, pdf_path: Path) -> bool:
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            dest = self.archive_dir / f"{timestamp}_{pdf_path.name}"
            if dest.exists():
                suffix = 1
                while dest.exists():
                    dest = self.archive_dir / f"{timestamp}_{pdf_path.stem}_{suffix}.pdf"
                    suffix += 1
            shutil.move(str(pdf_path), str(dest))
            return True
        except Exception as exc:
            logger.warning(f"Failed to archive {pdf_path.name}: {exc}")
            return False
