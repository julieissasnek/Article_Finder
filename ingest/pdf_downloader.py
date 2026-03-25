# Version: 3.2.2
"""
Article Finder v3 - PDF Downloader
Downloads PDFs using Unpaywall for open access papers.
"""

import time
import json
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from config.loader import get


class UnpaywallClient:
    """Client for Unpaywall API."""
    
    def __init__(self, email: str):
        self.email = email
        self.base_url = "https://api.unpaywall.org/v2"
        self.last_request = 0.0
        self.min_interval = 0.1  # 10 requests per second max
    
    def _rate_limit(self):
        """Respect rate limits."""
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()
    
    def get_paper(self, doi: str) -> Optional[Dict]:
        """Get paper info from Unpaywall."""
        self._rate_limit()
        
        url = f"{self.base_url}/{doi}?email={self.email}"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ArticleFinder/3.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        except Exception:
            return None
    
    def get_pdf_url(self, doi: str) -> Optional[str]:
        """Get best available PDF URL for a DOI."""
        data = self.get_paper(doi)
        if not data:
            return None
        
        # Check best OA location
        if data.get('best_oa_location'):
            pdf_url = data['best_oa_location'].get('url_for_pdf')
            if pdf_url:
                return pdf_url
        
        # Check all OA locations
        for location in data.get('oa_locations', []):
            pdf_url = location.get('url_for_pdf')
            if pdf_url:
                return pdf_url
        
        return None


class PDFDownloader:
    """Download PDFs for papers."""
    
    def __init__(
        self,
        database: Database,
        email: Optional[str] = None,
        output_dir: Optional[Path] = None
    ):
        self.db = database
        self.email = email or get('apis.unpaywall.email', 'test@example.com')
        self.unpaywall = UnpaywallClient(self.email)
        self.pdf_dir = output_dir or Path(get('paths.pdfs', 'data/pdfs'))
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
    
    def download_pdf(self, paper_id: str) -> Dict[str, Any]:
        """
        Download PDF for a single paper.
        
        Returns dict with status and path.
        """
        paper = self.db.get_paper(paper_id)
        if not paper:
            return {'success': False, 'error': 'Paper not found'}
        
        doi = paper.get('doi')
        if not doi:
            return {'success': False, 'error': 'No DOI'}
        
        # Check if already downloaded
        if paper.get('pdf_path'):
            pdf_path = Path(paper['pdf_path'])
            if pdf_path.exists():
                return {'success': True, 'path': str(pdf_path), 'cached': True}
        
        # Get PDF URL from Unpaywall
        pdf_url = self.unpaywall.get_pdf_url(doi)
        if not pdf_url:
            return {'success': False, 'error': 'No open access PDF found'}
        
        # Download PDF
        try:
            safe_doi = doi.replace('/', '_').replace(':', '_')
            pdf_path = self.pdf_dir / f"{safe_doi}.pdf"
            
            req = urllib.request.Request(pdf_url, headers={
                'User-Agent': 'ArticleFinder/3.0',
                'Accept': 'application/pdf'
            })
            
            with urllib.request.urlopen(req, timeout=60) as response:
                pdf_data = response.read()
            
            # Verify it's a PDF
            if not pdf_data.startswith(b'%PDF'):
                return {'success': False, 'error': 'Downloaded file is not a PDF'}
            
            # Save PDF
            with open(pdf_path, 'wb') as f:
                f.write(pdf_data)
            
            # Compute hash
            pdf_sha256 = hashlib.sha256(pdf_data).hexdigest()
            
            # Update paper record
            paper['pdf_path'] = str(pdf_path)
            paper['pdf_sha256'] = pdf_sha256
            paper['pdf_bytes'] = len(pdf_data)
            paper['updated_at'] = datetime.utcnow().isoformat()
            self.db.add_paper(paper)
            
            return {
                'success': True,
                'path': str(pdf_path),
                'size': len(pdf_data),
                'sha256': pdf_sha256
            }
            
        except urllib.error.HTTPError as e:
            return {'success': False, 'error': f'HTTP {e.code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def download_all(
        self,
        status_filter: Optional[str] = None,
        limit: Optional[int] = None,
        skip_existing: bool = True,
        progress_callback=None
    ) -> Dict[str, Any]:
        """Download PDFs for all papers."""
        
        # Get papers
        if status_filter:
            papers = self.db.get_papers_by_status(status_filter)
        else:
            papers = self.db.search_papers(limit=10000)
        
        # Filter to papers with DOIs
        papers = [p for p in papers if p.get('doi')]
        
        # Skip papers with existing PDFs
        if skip_existing:
            papers = [p for p in papers if not p.get('pdf_path') or not Path(p['pdf_path']).exists()]
        
        if limit:
            papers = papers[:limit]
        
        stats = {
            'total': len(papers),
            'downloaded': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        print(f"Downloading PDFs for {len(papers)} papers...")
        
        for i, paper in enumerate(papers):
            if progress_callback:
                progress_callback(i + 1, len(papers))
            
            result = self.download_pdf(paper['paper_id'])
            
            if result.get('success'):
                if result.get('cached'):
                    stats['skipped'] += 1
                else:
                    stats['downloaded'] += 1
                    print(f"  Downloaded: {paper.get('title', 'Unknown')[:50]}...")
            else:
                stats['failed'] += 1
                if len(stats['errors']) < 20:
                    stats['errors'].append(f"{paper['paper_id']}: {result.get('error')}")
            
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(papers)} ({stats['downloaded']} downloaded)")
        
        return stats
    
    def get_download_stats(self) -> Dict[str, Any]:
        """Get PDF download statistics."""
        papers = self.db.search_papers(limit=10000)
        
        with_doi = [p for p in papers if p.get('doi')]
        with_pdf = [p for p in papers if p.get('pdf_path') and Path(p['pdf_path']).exists()]
        
        total_size = sum(p.get('pdf_bytes', 0) for p in with_pdf)
        
        return {
            'total_papers': len(papers),
            'papers_with_doi': len(with_doi),
            'papers_with_pdf': len(with_pdf),
            'download_rate': len(with_pdf) / len(with_doi) if with_doi else 0,
            'total_pdf_size_mb': total_size / (1024 * 1024)
        }


# CLI
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Download PDFs for papers')
    parser.add_argument('--db', type=Path, default='data/article_finder.db')
    parser.add_argument('--email', required=True, help='Email for Unpaywall API')
    parser.add_argument('--download-all', action='store_true', help='Download all available PDFs')
    parser.add_argument('--paper', help='Download PDF for specific paper ID')
    parser.add_argument('--status', help='Only download for papers with this status')
    parser.add_argument('--limit', type=int, help='Maximum PDFs to download')
    parser.add_argument('--stats', action='store_true', help='Show download statistics')
    
    args = parser.parse_args()
    
    db = Database(args.db)
    downloader = PDFDownloader(db, email=args.email)
    
    if args.stats:
        stats = downloader.get_download_stats()
        print("\nPDF Download Statistics:")
        for key, value in stats.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")
    
    elif args.paper:
        result = downloader.download_pdf(args.paper)
        if result['success']:
            print(f"Downloaded: {result['path']}")
        else:
            print(f"Failed: {result['error']}")
    
    elif args.download_all:
        stats = downloader.download_all(
            status_filter=args.status,
            limit=args.limit
        )
        print(f"\nDownload complete:")
        print(f"  Downloaded: {stats['downloaded']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Skipped: {stats['skipped']}")
    
    else:
        parser.print_help()
