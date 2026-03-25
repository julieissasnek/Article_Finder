# Version: 3.2.2
"""
Article Finder v3.2 - DOI Resolver
Resolves DOIs to full metadata using CrossRef and OpenAlex APIs.
Includes title/author search when DOI is not available.
"""

import time
import json
import hashlib
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)

API_METRICS_PATH = Path('data/api_metrics.json')


def _load_api_metrics() -> dict:
    if API_METRICS_PATH.exists():
        try:
            return json.loads(API_METRICS_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _update_api_metrics(service: str, duration_ms: float, ok: bool) -> None:
    try:
        data = _load_api_metrics()
        stats = data.get(service, {'requests': 0, 'errors': 0, 'avg_ms': 0.0})
        stats['requests'] += 1
        if not ok:
            stats['errors'] += 1
        prev_avg = stats.get('avg_ms', 0.0)
        if stats['requests'] == 1:
            stats['avg_ms'] = duration_ms
        else:
            stats['avg_ms'] = ((prev_avg * (stats['requests'] - 1)) + duration_ms) / stats['requests']
        data[service] = stats
        API_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        API_METRICS_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception:
        pass


class RateLimiter:
    """Simple rate limiter with exponential backoff."""
    
    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self.last_request = 0.0
        self.backoff = 1.0
        self.max_backoff = 60.0
    
    def wait(self):
        """Wait if necessary to respect rate limit."""
        elapsed = time.time() - self.last_request
        wait_time = max(0, self.min_interval * self.backoff - elapsed)
        if wait_time > 0:
            time.sleep(wait_time)
        self.last_request = time.time()
    
    def success(self):
        """Called after successful request."""
        self.backoff = max(1.0, self.backoff * 0.9)
    
    def failure(self):
        """Called after failed request."""
        self.backoff = min(self.max_backoff, self.backoff * 2)


class APICache:
    """Simple file-based cache for API responses."""
    
    def __init__(self, cache_dir: Path, ttl_days: int = 7):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_days * 24 * 3600
    
    def _key_to_path(self, key: str) -> Path:
        hash_val = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_val}.json"
    
    def get(self, key: str) -> Optional[Dict]:
        """Get cached value if not expired."""
        path = self._key_to_path(key)
        if not path.exists():
            return None
        
        try:
            with open(path) as f:
                cached = json.load(f)
            
            cached_at = cached.get('_cached_at', 0)
            if time.time() - cached_at > self.ttl_seconds:
                return None
            
            return cached.get('data')
        except (json.JSONDecodeError, IOError):
            return None
    
    def set(self, key: str, data: Any):
        """Cache a value."""
        path = self._key_to_path(key)
        try:
            with open(path, 'w') as f:
                json.dump({
                    '_cached_at': time.time(),
                    'data': data
                }, f)
        except IOError as e:
            logger.debug(f"Cache write failed: {e}")


class CrossRefClient:
    """Client for CrossRef API."""
    
    BASE_URL = "https://api.crossref.org"
    
    def __init__(self, email: Optional[str] = None, cache_dir: Optional[Path] = None):
        self.email = email
        self.rate_limiter = RateLimiter(requests_per_second=50 if email else 10)
        self.cache = APICache(cache_dir or Path('data/cache/crossref'))
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request to CrossRef API."""
        url = f"{self.BASE_URL}/{endpoint}"
        
        if params:
            query = urlencode(params)
            url = f"{url}?{query}"
        
        # Check cache
        cached = self.cache.get(url)
        if cached is not None:
            return cached
        
        # Rate limit
        self.rate_limiter.wait()
        
        # Build request
        headers = {
            'User-Agent': f'ArticleFinder/3.2 (mailto:{self.email})' if self.email 
                          else 'ArticleFinder/3.2'
        }
        
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                self.rate_limiter.success()
                _update_api_metrics('crossref', (time.monotonic() - start) * 1000, True)
                
                # Cache successful response
                self.cache.set(url, data)
                return data
                
        except urllib.error.HTTPError as e:
            self.rate_limiter.failure()
            _update_api_metrics('crossref', (time.monotonic() - start) * 1000, False)
            if e.code == 404:
                return None
            logger.warning(f"CrossRef API error {e.code}: {e.reason}")
            raise
        except Exception as e:
            self.rate_limiter.failure()
            _update_api_metrics('crossref', (time.monotonic() - start) * 1000, False)
            logger.warning(f"CrossRef request failed: {e}")
            raise
    
    def get_work(self, doi: str) -> Optional[Dict]:
        """Get work metadata by DOI."""
        try:
            data = self._request(f"works/{quote(doi, safe='')}")
            if data and data.get('status') == 'ok':
                return self._normalize_work(data.get('message', {}))
        except Exception as e:
            logger.debug(f"CrossRef work lookup failed for {doi}: {e}")
        return None
    
    def search_works(
        self,
        query: str,
        limit: int = 5,
        filter_type: Optional[str] = None
    ) -> List[Dict]:
        """Search for works by query string."""
        params = {
            'query': query,
            'rows': limit
        }
        
        if filter_type:
            params['filter'] = f'type:{filter_type}'
        
        try:
            data = self._request('works', params)
            if data and data.get('status') == 'ok':
                items = data.get('message', {}).get('items', [])
                return [self._normalize_work(item) for item in items]
        except Exception as e:
            logger.debug(f"CrossRef search failed: {e}")
        
        return []
    
    def search_by_title_author(
        self,
        title: Optional[str] = None,
        author: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 5
    ) -> List[Dict]:
        """Search by bibliographic fields."""
        params = {'rows': limit}
        
        # Build query
        query_parts = []
        
        if title:
            # Use bibliographic query for title
            params['query.bibliographic'] = title[:200]
        
        if author:
            params['query.author'] = author
        
        if year:
            params['filter'] = f'from-pub-date:{year},until-pub-date:{year}'
        
        try:
            data = self._request('works', params)
            if data and data.get('status') == 'ok':
                items = data.get('message', {}).get('items', [])
                return [self._normalize_work(item) for item in items]
        except Exception as e:
            logger.debug(f"CrossRef search failed: {e}")
        
        return []
    
    def _normalize_work(self, item: Dict) -> Dict:
        """Normalize CrossRef work to standard format."""
        # Extract title
        title = None
        titles = item.get('title', [])
        if titles:
            title = titles[0] if isinstance(titles, list) else titles
        
        # Extract authors
        authors = []
        for author in item.get('author', []):
            if author.get('family'):
                name = author.get('family')
                if author.get('given'):
                    name = f"{name}, {author.get('given')}"
                authors.append(name)
            elif author.get('name'):
                authors.append(author.get('name'))
        
        # Extract year
        year = None
        published = item.get('published-print') or item.get('published-online') or item.get('created')
        if published:
            date_parts = published.get('date-parts', [[]])[0]
            if date_parts:
                year = date_parts[0]
        
        # Extract venue
        venue = None
        container = item.get('container-title', [])
        if container:
            venue = container[0] if isinstance(container, list) else container
        
        return {
            'doi': item.get('DOI'),
            'title': title,
            'authors': authors,
            'year': year,
            'venue': venue,
            'publisher': item.get('publisher'),
            'abstract': item.get('abstract'),
            'url': item.get('URL'),
            'type': item.get('type'),
            'issn': item.get('ISSN'),
            'reference_count': item.get('reference-count'),
            'is_referenced_by_count': item.get('is-referenced-by-count'),
            'source': 'crossref'
        }


class OpenAlexClient:
    """Client for OpenAlex API."""
    
    BASE_URL = "https://api.openalex.org"
    
    def __init__(
        self,
        email: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
    ):
        self.email = email
        self.api_key = api_key
        self.rate_limiter = RateLimiter(requests_per_second=10 if email else 5)
        self.cache = APICache(cache_dir or Path('data/cache/openalex'))
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request to OpenAlex API."""
        url = f"{self.BASE_URL}/{endpoint}"
        
        def _build_url(include_key: bool) -> str:
            local_params = dict(params or {})
            if self.email:
                local_params['mailto'] = self.email
            if include_key and self.api_key:
                local_params['api_key'] = self.api_key
            if local_params:
                return f"{url}?{urlencode(local_params)}"
            return url

        for include_key in (True, False):
            if include_key and not self.api_key:
                continue

            request_url = _build_url(include_key)
            cached = self.cache.get(request_url)
            if cached is not None:
                return cached

            self.rate_limiter.wait()
            start = time.monotonic()
            try:
                req = urllib.request.Request(request_url, headers={'User-Agent': 'ArticleFinder/3.2'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    self.rate_limiter.success()
                    _update_api_metrics('openalex', (time.monotonic() - start) * 1000, True)
                    self.cache.set(request_url, data)
                    return data
            except urllib.error.HTTPError as e:
                self.rate_limiter.failure()
                _update_api_metrics('openalex', (time.monotonic() - start) * 1000, False)
                if e.code == 404:
                    return None
                if e.code == 401 and include_key and self.api_key:
                    logger.warning("OpenAlex API key rejected; retrying without key")
                    self.api_key = None
                    continue
                logger.warning(f"OpenAlex API error {e.code}")
                raise
            except Exception as e:
                self.rate_limiter.failure()
                _update_api_metrics('openalex', (time.monotonic() - start) * 1000, False)
                logger.warning(f"OpenAlex request failed: {e}")
                raise
        return None
    
    def get_work_by_doi(self, doi: str) -> Optional[Dict]:
        """Get work by DOI."""
        try:
            data = self._request(f"works/https://doi.org/{doi}")
            if data:
                return self._normalize_work(data)
        except Exception:
            pass
        return None
    
    def get_work_by_id(self, openalex_id: str) -> Optional[Dict]:
        """Get work by OpenAlex ID."""
        try:
            # Handle full URLs or just IDs
            if openalex_id.startswith('https://'):
                endpoint = openalex_id.replace('https://openalex.org/', '')
            else:
                endpoint = f"works/{openalex_id}"
            
            data = self._request(endpoint)
            if data:
                return self._normalize_work(data)
        except Exception:
            pass
        return None
    
    def search_works(self, query: str, limit: int = 10) -> List[Dict]:
        """Search works by query."""
        try:
            data = self._request('works', {
                'search': query,
                'per_page': limit
            })
            if data and data.get('results'):
                return [self._normalize_work(w) for w in data['results']]
        except Exception:
            pass
        return []
    
    def get_references(self, doi: str) -> List[str]:
        """Get papers referenced by this paper."""
        work = self.get_work_by_doi(doi)
        if work:
            return work.get('referenced_works', [])
        return []
    
    def get_citations(self, doi: str, limit: int = 100) -> List[Dict]:
        """Get papers that cite this paper."""
        try:
            work = self.get_work_by_doi(doi)
            if not work or not work.get('url'):
                return []
            openalex_id = work['url'].replace('https://openalex.org/', '')
            data = self._request('works', {
                'filter': f'cites:{openalex_id}',
                'per_page': limit
            })
            if data and data.get('results'):
                return [self._normalize_work(w) for w in data['results']]
        except Exception:
            pass
        return []
    
    def _normalize_work(self, item: Dict) -> Dict:
        """Normalize OpenAlex work to standard format."""
        abstract = self._reconstruct_abstract(item.get('abstract_inverted_index'))
        # Extract authors
        authors = []
        for authorship in item.get('authorships', []):
            author = authorship.get('author', {})
            name = author.get('display_name')
            if name:
                authors.append(name)
        
        # Extract venue
        venue = None
        locations = item.get('locations', [])
        for loc in locations:
            source = loc.get('source', {})
            if source:
                venue = source.get('display_name')
                if venue:
                    break
        
        return {
            'doi': item.get('doi', '').replace('https://doi.org/', '') if item.get('doi') else None,
            'title': item.get('title'),
            'authors': authors,
            'year': item.get('publication_year'),
            'venue': venue,
            'abstract': abstract,
            'url': item.get('id'),
            'type': item.get('type'),
            'open_access': item.get('open_access', {}).get('is_oa'),
            'oa_url': item.get('open_access', {}).get('oa_url'),
            'cited_by_count': item.get('cited_by_count'),
            'referenced_works': item.get('referenced_works', []),
            'source': 'openalex'
        }

    def _reconstruct_abstract(self, inverted_index: Optional[Dict]) -> Optional[str]:
        """Reconstruct abstract text from OpenAlex inverted index."""
        if not inverted_index:
            return None
        try:
            positions: Dict[int, str] = {}
            for word, indices in inverted_index.items():
                for idx in indices:
                    positions[int(idx)] = word
            if not positions:
                return None
            max_pos = max(positions)
            words = [positions.get(i, '') for i in range(max_pos + 1)]
            text = ' '.join(word for word in words if word)
            return text.strip() or None
        except Exception:
            return None


class DOIResolver:
    """
    Unified DOI resolver using multiple APIs.
    """
    
    def __init__(
        self,
        email: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        prefer_openalex: bool = True
    ):
        """
        Args:
            email: Email for API polite pools
            cache_dir: Directory for caching responses
            prefer_openalex: If True, try OpenAlex first (faster, includes OA links)
        """
        cache_dir = Path(cache_dir or 'data/cache')
        
        self.crossref = CrossRefClient(email, cache_dir / 'crossref')
        from config.loader import get

        openalex_api_key = get('apis.openalex.api_key')
        self.openalex = OpenAlexClient(email, cache_dir / 'openalex', api_key=openalex_api_key)
        self.prefer_openalex = prefer_openalex
    
    def resolve(self, doi: str) -> Optional[Dict]:
        """
        Resolve a DOI to full metadata.
        Tries multiple sources and merges results.
        """
        doi = self._normalize_doi(doi)
        if not doi:
            return None
        
        result = None
        
        if self.prefer_openalex:
            result = self.openalex.get_work_by_doi(doi)
            if not result or not result.get('title'):
                cr_result = self.crossref.get_work(doi)
                if cr_result:
                    result = self._merge_results(result, cr_result)
        else:
            result = self.crossref.get_work(doi)
            oa_result = self.openalex.get_work_by_doi(doi)
            if oa_result:
                result = self._merge_results(result, oa_result)
        
        if result:
            result['paper_id'] = f"doi:{doi}"
            result['doi'] = doi
        
        return result
    
    def search_crossref(
        self,
        query: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search CrossRef by query string.
        Returns list of matching papers.
        """
        return self.crossref.search_works(query, limit)
    
    def search_by_bibliographic(
        self,
        title: Optional[str] = None,
        author: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search by bibliographic fields.
        Useful when DOI is not available.
        """
        # Try CrossRef first (better bibliographic search)
        results = self.crossref.search_by_title_author(title, author, year, limit)
        
        # Also try OpenAlex
        if not results or len(results) < limit:
            query_parts = []
            if title:
                query_parts.append(title)
            if author:
                query_parts.append(author)
            
            if query_parts:
                oa_results = self.openalex.search_works(' '.join(query_parts), limit)
                results.extend(oa_results)
        
        # Deduplicate by DOI
        seen_dois = set()
        unique = []
        for r in results:
            doi = r.get('doi')
            if doi:
                if doi not in seen_dois:
                    seen_dois.add(doi)
                    unique.append(r)
            else:
                unique.append(r)
        
        return unique[:limit]
    
    def get_citations(self, doi: str) -> List[Dict]:
        """Get papers that cite this paper."""
        return self.openalex.get_citations(doi)
    
    def get_references(self, doi: str) -> List[str]:
        """Get papers referenced by this paper."""
        return self.openalex.get_references(doi)
    
    def _normalize_doi(self, doi: str) -> Optional[str]:
        """Normalize a DOI string."""
        if not doi:
            return None
        
        doi = str(doi).strip().lower()
        
        # Remove URL prefix
        for prefix in ['https://doi.org/', 'http://doi.org/', 'http://dx.doi.org/', 'doi:']:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        
        # Validate format
        if not doi.startswith('10.'):
            return None
        
        return doi
    
    def _merge_results(self, primary: Optional[Dict], secondary: Dict) -> Dict:
        """Merge two result dicts, preferring primary values."""
        if not primary:
            return secondary
        
        merged = dict(secondary)
        for key, value in primary.items():
            if value:
                merged[key] = value
        
        return merged


# Convenience function
def resolve_doi(doi: str, email: Optional[str] = None) -> Optional[Dict]:
    """Quick DOI resolution."""
    resolver = DOIResolver(email=email)
    return resolver.resolve(doi)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Resolve DOIs')
    parser.add_argument('doi', help='DOI to resolve')
    parser.add_argument('--email', help='Email for API polite pool')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    
    resolver = DOIResolver(email=args.email)
    result = resolver.resolve(args.doi)
    
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Could not resolve DOI: {args.doi}")
