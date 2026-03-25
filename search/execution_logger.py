# Version: 3.2.5
"""
Article Finder v3.2.5 - Search Execution Logger
Structured logging for search operations across all discovery modules.

Captures:
- Query execution details (API, query text, parameters)
- Results (papers found, scored, accepted, rejected)
- Timing information
- Error tracking
- Context (cell_id, gap_id, discovery phase)

Logs are written in JSON Lines format for easy analysis.

Usage:
    from search.execution_logger import SearchLogger, SearchQuery

    logger = SearchLogger(log_dir=Path('./data/logs'))

    with logger.log_query(
        api='openalex',
        query='attention restoration theory',
        context={'cell_id': 'theory:ART'}
    ) as query:
        papers = openalex.search(query.query_text)
        query.record_results(papers_found=len(papers), papers_accepted=5)

    # Or without context manager:
    query_id = logger.start_query('openalex', 'ceiling height cognition')
    logger.end_query(query_id, papers_found=10, papers_accepted=3)
"""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

module_logger = logging.getLogger(__name__)


class SearchAPI(Enum):
    """Supported search APIs."""
    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    PUBMED = "pubmed"
    CROSSREF = "crossref"


class QueryStatus(Enum):
    """Status of a search query."""
    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


@dataclass
class SearchQueryRecord:
    """Record of a single search query execution."""
    query_id: str
    timestamp: str
    api: str
    query_text: str
    status: str = "started"

    # Timing
    started_at: str = ""
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None

    # Results
    papers_found: int = 0
    papers_scored: int = 0
    papers_accepted: int = 0
    papers_rejected: int = 0
    papers_duplicate: int = 0

    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    cell_id: Optional[str] = None
    gap_id: Optional[str] = None
    discovery_phase: Optional[str] = None

    # Error handling
    error_message: Optional[str] = None
    error_type: Optional[str] = None

    # API-specific metadata
    api_response_code: Optional[int] = None
    api_cursor: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class SessionStats:
    """Aggregate statistics for a search session."""
    session_id: str
    started_at: str
    completed_at: Optional[str] = None

    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0

    total_papers_found: int = 0
    total_papers_accepted: int = 0
    total_papers_rejected: int = 0
    total_papers_duplicate: int = 0

    queries_by_api: Dict[str, int] = field(default_factory=dict)
    papers_by_api: Dict[str, int] = field(default_factory=dict)

    total_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class SearchLogger:
    """
    Structured logger for search execution.

    Captures detailed information about each search query and aggregates
    statistics for analysis and debugging.
    """

    LOG_FILE_PREFIX = "search_execution"
    SESSION_FILE_PREFIX = "search_session"

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
        flush_interval: int = 10,
        enabled: bool = True
    ):
        """
        Args:
            log_dir: Directory to write log files
            session_id: Unique session identifier (auto-generated if None)
            flush_interval: Flush to disk after this many queries
            enabled: Set to False to disable logging (for testing)
        """
        self.log_dir = log_dir or Path('./data/logs')
        self.session_id = session_id or self._generate_session_id()
        self.flush_interval = flush_interval
        self.enabled = enabled

        # Ensure log directory exists
        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        # In-memory tracking
        self._queries: Dict[str, SearchQueryRecord] = {}
        self._query_count = 0

        # Session stats
        self._session_stats = SessionStats(
            session_id=self.session_id,
            started_at=datetime.utcnow().isoformat()
        )

        # File handles
        self._log_file: Optional[Path] = None
        self._buffer: List[str] = []

        module_logger.info(f"SearchLogger initialized: session={self.session_id}")

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        short_uuid = str(uuid.uuid4())[:8]
        return f"{timestamp}_{short_uuid}"

    def _get_log_file_path(self) -> Path:
        """Get path to current log file."""
        date_str = datetime.utcnow().strftime('%Y-%m-%d')
        return self.log_dir / f"{self.LOG_FILE_PREFIX}_{date_str}.jsonl"

    def _write_record(self, record: SearchQueryRecord):
        """Write a query record to the log file."""
        if not self.enabled:
            return

        log_line = json.dumps(record.to_dict()) + "\n"
        self._buffer.append(log_line)

        # Flush periodically
        if len(self._buffer) >= self.flush_interval:
            self._flush()

    def _flush(self):
        """Flush buffer to disk."""
        if not self._buffer or not self.enabled:
            return

        log_path = self._get_log_file_path()

        try:
            with open(log_path, 'a') as f:
                f.writelines(self._buffer)
            self._buffer.clear()
        except Exception as e:
            module_logger.warning(f"Failed to flush search log: {e}")

    def start_query(
        self,
        api: str,
        query_text: str,
        context: Optional[Dict[str, Any]] = None,
        cell_id: Optional[str] = None,
        gap_id: Optional[str] = None,
        discovery_phase: Optional[str] = None
    ) -> str:
        """
        Start logging a new query.

        Args:
            api: API being queried (openalex, semantic_scholar, pubmed)
            query_text: The search query string
            context: Additional context dictionary
            cell_id: Bibliographer cell ID if applicable
            gap_id: Gap analyzer gap ID if applicable
            discovery_phase: Current discovery phase

        Returns:
            query_id: Unique identifier for this query
        """
        query_id = f"{self.session_id}_{self._query_count}"
        self._query_count += 1

        now = datetime.utcnow().isoformat()

        record = SearchQueryRecord(
            query_id=query_id,
            timestamp=now,
            api=api,
            query_text=query_text,
            status=QueryStatus.STARTED.value,
            started_at=now,
            context=context or {},
            cell_id=cell_id,
            gap_id=gap_id,
            discovery_phase=discovery_phase
        )

        self._queries[query_id] = record
        self._session_stats.total_queries += 1
        self._session_stats.queries_by_api[api] = \
            self._session_stats.queries_by_api.get(api, 0) + 1

        module_logger.debug(f"Search query started: {query_id} [{api}] {query_text[:50]}...")

        return query_id

    def end_query(
        self,
        query_id: str,
        papers_found: int = 0,
        papers_scored: int = 0,
        papers_accepted: int = 0,
        papers_rejected: int = 0,
        papers_duplicate: int = 0,
        error: Optional[Exception] = None,
        api_response_code: Optional[int] = None
    ):
        """
        Complete logging for a query.

        Args:
            query_id: Query ID from start_query()
            papers_found: Total papers returned by API
            papers_scored: Papers that were scored
            papers_accepted: Papers that passed relevance filter
            papers_rejected: Papers rejected by filter
            papers_duplicate: Papers skipped as duplicates
            error: Exception if query failed
            api_response_code: HTTP response code if available
        """
        if query_id not in self._queries:
            module_logger.warning(f"Unknown query_id: {query_id}")
            return

        record = self._queries[query_id]

        now = datetime.utcnow().isoformat()
        record.completed_at = now

        # Calculate duration
        start = datetime.fromisoformat(record.started_at)
        end = datetime.fromisoformat(now)
        record.duration_ms = (end - start).total_seconds() * 1000

        # Record results
        record.papers_found = papers_found
        record.papers_scored = papers_scored
        record.papers_accepted = papers_accepted
        record.papers_rejected = papers_rejected
        record.papers_duplicate = papers_duplicate
        record.api_response_code = api_response_code

        if error:
            record.status = QueryStatus.ERROR.value
            record.error_message = str(error)
            record.error_type = type(error).__name__
            self._session_stats.failed_queries += 1
        else:
            record.status = QueryStatus.COMPLETED.value
            self._session_stats.successful_queries += 1

        # Update session stats
        self._session_stats.total_papers_found += papers_found
        self._session_stats.total_papers_accepted += papers_accepted
        self._session_stats.total_papers_rejected += papers_rejected
        self._session_stats.total_papers_duplicate += papers_duplicate
        self._session_stats.total_duration_ms += record.duration_ms

        api = record.api
        self._session_stats.papers_by_api[api] = \
            self._session_stats.papers_by_api.get(api, 0) + papers_found

        # Write to log
        self._write_record(record)

        # Remove from active queries
        del self._queries[query_id]

        module_logger.debug(
            f"Search query completed: {query_id} [{api}] "
            f"found={papers_found} accepted={papers_accepted} "
            f"duration={record.duration_ms:.0f}ms"
        )

    @contextmanager
    def log_query(
        self,
        api: str,
        query_text: str,
        context: Optional[Dict[str, Any]] = None,
        cell_id: Optional[str] = None,
        gap_id: Optional[str] = None,
        discovery_phase: Optional[str] = None
    ):
        """
        Context manager for logging a search query.

        Usage:
            with logger.log_query('openalex', 'query text') as query:
                results = do_search()
                query.record_results(papers_found=len(results))

        Args:
            api: API being queried
            query_text: Search query string
            context: Additional context
            cell_id: Bibliographer cell ID
            gap_id: Gap analyzer gap ID
            discovery_phase: Current discovery phase

        Yields:
            QueryContext object with record_results() and record_error() methods
        """
        query_id = self.start_query(
            api=api,
            query_text=query_text,
            context=context,
            cell_id=cell_id,
            gap_id=gap_id,
            discovery_phase=discovery_phase
        )

        ctx = QueryContext(self, query_id, query_text)

        try:
            yield ctx
        except Exception as e:
            ctx.record_error(e)
            raise
        finally:
            if not ctx._completed:
                ctx.complete()

    def get_session_stats(self) -> SessionStats:
        """Get current session statistics."""
        return self._session_stats

    def finalize_session(self):
        """
        Finalize the session and write summary.

        Call this when the search session is complete.
        """
        self._flush()

        self._session_stats.completed_at = datetime.utcnow().isoformat()

        # Write session summary
        if self.enabled:
            session_path = self.log_dir / f"{self.SESSION_FILE_PREFIX}_{self.session_id}.json"
            try:
                with open(session_path, 'w') as f:
                    json.dump(self._session_stats.to_dict(), f, indent=2)
                module_logger.info(f"Session summary written: {session_path}")
            except Exception as e:
                module_logger.warning(f"Failed to write session summary: {e}")

        return self._session_stats

    def log_rate_limit(self, api: str, retry_after: Optional[int] = None):
        """Log a rate limit event."""
        module_logger.warning(f"Rate limited by {api}, retry_after={retry_after}")

        # Record as a special query
        query_id = self.start_query(api, "__RATE_LIMITED__")
        record = self._queries.get(query_id)
        if record:
            record.status = QueryStatus.RATE_LIMITED.value
            record.context['retry_after'] = retry_after
            self._write_record(record)
            del self._queries[query_id]


class QueryContext:
    """
    Context object for query logging within a context manager.

    Provides methods to record results and errors during query execution.
    """

    def __init__(self, logger: SearchLogger, query_id: str, query_text: str):
        self._logger = logger
        self._query_id = query_id
        self.query_text = query_text
        self._completed = False

        # Accumulated results
        self.papers_found = 0
        self.papers_scored = 0
        self.papers_accepted = 0
        self.papers_rejected = 0
        self.papers_duplicate = 0
        self.api_response_code: Optional[int] = None
        self.error: Optional[Exception] = None

    def record_results(
        self,
        papers_found: int = 0,
        papers_scored: int = 0,
        papers_accepted: int = 0,
        papers_rejected: int = 0,
        papers_duplicate: int = 0,
        api_response_code: Optional[int] = None
    ):
        """Record search results. Can be called multiple times to accumulate."""
        self.papers_found += papers_found
        self.papers_scored += papers_scored
        self.papers_accepted += papers_accepted
        self.papers_rejected += papers_rejected
        self.papers_duplicate += papers_duplicate
        if api_response_code is not None:
            self.api_response_code = api_response_code

    def record_error(self, error: Exception):
        """Record an error that occurred during the query."""
        self.error = error

    def complete(self):
        """Complete the query logging."""
        if self._completed:
            return

        self._logger.end_query(
            query_id=self._query_id,
            papers_found=self.papers_found,
            papers_scored=self.papers_scored,
            papers_accepted=self.papers_accepted,
            papers_rejected=self.papers_rejected,
            papers_duplicate=self.papers_duplicate,
            error=self.error,
            api_response_code=self.api_response_code
        )
        self._completed = True


# Global logger instance (can be imported and used directly)
_global_logger: Optional[SearchLogger] = None


def get_search_logger(log_dir: Optional[Path] = None) -> SearchLogger:
    """Get or create the global search logger instance."""
    global _global_logger

    if _global_logger is None:
        _global_logger = SearchLogger(log_dir=log_dir)

    return _global_logger


def reset_search_logger():
    """Reset the global search logger (for testing)."""
    global _global_logger

    if _global_logger is not None:
        _global_logger.finalize_session()
        _global_logger = None


# ============================================================================
# LOG ANALYSIS UTILITIES
# ============================================================================

def load_execution_logs(log_dir: Path, date: Optional[str] = None) -> List[Dict]:
    """
    Load search execution logs from disk.

    Args:
        log_dir: Directory containing log files
        date: Optional date string (YYYY-MM-DD) to filter by

    Returns:
        List of query records as dictionaries
    """
    records = []

    pattern = f"search_execution_{date}.jsonl" if date else "search_execution_*.jsonl"

    for log_file in sorted(log_dir.glob(pattern)):
        try:
            with open(log_file) as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
        except Exception as e:
            module_logger.warning(f"Failed to read log file {log_file}: {e}")

    return records


def summarize_execution_logs(records: List[Dict]) -> Dict[str, Any]:
    """
    Generate summary statistics from execution logs.

    Args:
        records: List of query records

    Returns:
        Summary statistics dictionary
    """
    if not records:
        return {'total_queries': 0}

    by_api = {}
    by_status = {}
    total_duration = 0.0
    total_found = 0
    total_accepted = 0

    for record in records:
        api = record.get('api', 'unknown')
        status = record.get('status', 'unknown')

        by_api[api] = by_api.get(api, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

        total_duration += record.get('duration_ms', 0) or 0
        total_found += record.get('papers_found', 0)
        total_accepted += record.get('papers_accepted', 0)

    return {
        'total_queries': len(records),
        'by_api': by_api,
        'by_status': by_status,
        'total_duration_ms': total_duration,
        'avg_duration_ms': total_duration / len(records) if records else 0,
        'total_papers_found': total_found,
        'total_papers_accepted': total_accepted,
        'acceptance_rate': total_accepted / total_found if total_found > 0 else 0
    }


if __name__ == '__main__':
    # Demo usage
    import argparse

    parser = argparse.ArgumentParser(description='Search execution logger demo')
    parser.add_argument('--analyze', type=Path, help='Analyze logs in directory')
    parser.add_argument('--date', help='Filter by date (YYYY-MM-DD)')

    args = parser.parse_args()

    if args.analyze:
        records = load_execution_logs(args.analyze, args.date)
        summary = summarize_execution_logs(records)

        print("\n=== Search Execution Summary ===")
        print(f"Total queries: {summary['total_queries']}")
        print(f"Total duration: {summary['total_duration_ms']/1000:.1f}s")
        print(f"Avg duration: {summary['avg_duration_ms']:.0f}ms")
        print(f"Papers found: {summary['total_papers_found']}")
        print(f"Papers accepted: {summary['total_papers_accepted']}")
        print(f"Acceptance rate: {summary['acceptance_rate']*100:.1f}%")

        print("\nBy API:")
        for api, count in summary['by_api'].items():
            print(f"  {api}: {count}")

        print("\nBy Status:")
        for status, count in summary['by_status'].items():
            print(f"  {status}: {count}")
    else:
        # Demo mode
        print("Running demo...")

        logger = SearchLogger(log_dir=Path('./data/logs'))

        # Using context manager
        with logger.log_query('openalex', 'attention restoration theory',
                              context={'cell_id': 'theory:ART'}) as query:
            # Simulate search
            time.sleep(0.1)
            query.record_results(papers_found=25, papers_accepted=8, papers_rejected=17)

        # Using explicit start/end
        qid = logger.start_query('semantic_scholar', 'ceiling height cognition')
        time.sleep(0.1)
        logger.end_query(qid, papers_found=15, papers_accepted=5)

        # With error
        try:
            with logger.log_query('pubmed', 'biophilia hypothesis') as query:
                raise ValueError("Simulated API error")
        except ValueError:
            pass

        stats = logger.finalize_session()

        print("\n=== Session Stats ===")
        print(f"Total queries: {stats.total_queries}")
        print(f"Successful: {stats.successful_queries}")
        print(f"Failed: {stats.failed_queries}")
        print(f"Papers found: {stats.total_papers_found}")
        print(f"Papers accepted: {stats.total_papers_accepted}")
