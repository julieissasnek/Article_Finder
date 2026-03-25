# Version: 3.2.2
"""
Article Finder v3.2.2 - Parallel Processing
Utilities for parallel/async operations to handle large corpora.

Provides:
- Batch embedding with progress tracking
- Checkpoint-based processing
- Incremental re-scoring when taxonomy changes
"""

import logging
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Generator
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)


@dataclass
class ProcessingCheckpoint:
    """Checkpoint for resumable processing."""
    task_name: str
    total_items: int
    processed_items: int
    last_item_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed: bool = False
    error_count: int = 0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_name': self.task_name,
            'total_items': self.total_items,
            'processed_items': self.processed_items,
            'last_item_id': self.last_item_id,
            'started_at': self.started_at,
            'updated_at': self.updated_at,
            'completed': self.completed,
            'error_count': self.error_count,
            'errors': self.errors[-10:]  # Keep last 10 errors
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProcessingCheckpoint':
        return cls(
            task_name=data.get('task_name', ''),
            total_items=data.get('total_items', 0),
            processed_items=data.get('processed_items', 0),
            last_item_id=data.get('last_item_id'),
            started_at=data.get('started_at', datetime.utcnow().isoformat()),
            updated_at=data.get('updated_at', datetime.utcnow().isoformat()),
            completed=data.get('completed', False),
            error_count=data.get('error_count', 0),
            errors=data.get('errors', [])
        )
    
    @property
    def progress_percent(self) -> float:
        if self.total_items == 0:
            return 100.0
        return (self.processed_items / self.total_items) * 100


class CheckpointManager:
    """Manage checkpoints for resumable processing."""
    
    def __init__(self, checkpoint_dir: Optional[Path] = None):
        self.checkpoint_dir = Path(checkpoint_dir or "data/checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def _checkpoint_path(self, task_name: str) -> Path:
        safe_name = task_name.replace('/', '_').replace(' ', '_')
        return self.checkpoint_dir / f"{safe_name}.json"
    
    def save(self, checkpoint: ProcessingCheckpoint):
        """Save checkpoint to disk."""
        checkpoint.updated_at = datetime.utcnow().isoformat()
        path = self._checkpoint_path(checkpoint.task_name)
        
        with open(path, 'w') as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
    
    def load(self, task_name: str) -> Optional[ProcessingCheckpoint]:
        """Load checkpoint from disk."""
        path = self._checkpoint_path(task_name)
        
        if not path.exists():
            return None
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return ProcessingCheckpoint.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None
    
    def delete(self, task_name: str):
        """Delete checkpoint."""
        path = self._checkpoint_path(task_name)
        if path.exists():
            path.unlink()
    
    def list_checkpoints(self) -> List[ProcessingCheckpoint]:
        """List all checkpoints."""
        checkpoints = []
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                checkpoints.append(ProcessingCheckpoint.from_dict(data))
            except Exception:
                pass
        return checkpoints


class BatchProcessor:
    """
    Process items in batches with checkpointing and progress tracking.
    """
    
    def __init__(
        self,
        task_name: str,
        checkpoint_dir: Optional[Path] = None,
        batch_size: int = 50,
        checkpoint_interval: int = 100,
        max_workers: int = 4
    ):
        self.task_name = task_name
        self.batch_size = batch_size
        self.checkpoint_interval = checkpoint_interval
        self.max_workers = max_workers
        
        self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        self.checkpoint: Optional[ProcessingCheckpoint] = None
        
        self._lock = threading.Lock()
        self._stop_requested = False
    
    def process(
        self,
        items: List[Any],
        process_fn: Callable[[Any], Any],
        item_id_fn: Callable[[Any], str] = lambda x: str(x),
        progress_fn: Optional[Callable[[int, int, ProcessingCheckpoint], None]] = None,
        resume: bool = True
    ) -> ProcessingCheckpoint:
        """
        Process items with checkpointing.
        
        Args:
            items: List of items to process
            process_fn: Function to apply to each item
            item_id_fn: Function to get ID from item
            progress_fn: Callback for progress updates
            resume: Whether to resume from checkpoint
            
        Returns:
            Final checkpoint with results
        """
        # Load or create checkpoint
        if resume:
            self.checkpoint = self.checkpoint_manager.load(self.task_name)
        
        if not self.checkpoint or self.checkpoint.completed:
            self.checkpoint = ProcessingCheckpoint(
                task_name=self.task_name,
                total_items=len(items),
                processed_items=0
            )
        
        # Find resume point
        start_idx = 0
        if self.checkpoint.last_item_id:
            for i, item in enumerate(items):
                if item_id_fn(item) == self.checkpoint.last_item_id:
                    start_idx = i + 1
                    break
        
        items_to_process = items[start_idx:]
        
        logger.info(
            f"Processing {len(items_to_process)} items "
            f"(resuming from {start_idx}/{len(items)})"
        )
        
        # Process in batches
        for batch_start in range(0, len(items_to_process), self.batch_size):
            if self._stop_requested:
                break
            
            batch = items_to_process[batch_start:batch_start + self.batch_size]
            
            for item in batch:
                if self._stop_requested:
                    break
                
                item_id = item_id_fn(item)
                
                try:
                    process_fn(item)
                    
                    with self._lock:
                        self.checkpoint.processed_items += 1
                        self.checkpoint.last_item_id = item_id
                    
                except Exception as e:
                    with self._lock:
                        self.checkpoint.error_count += 1
                        self.checkpoint.errors.append(f"{item_id}: {str(e)}")
                    logger.warning(f"Error processing {item_id}: {e}")
            
            # Save checkpoint periodically
            if self.checkpoint.processed_items % self.checkpoint_interval == 0:
                self.checkpoint_manager.save(self.checkpoint)
            
            # Progress callback
            if progress_fn:
                progress_fn(
                    self.checkpoint.processed_items,
                    self.checkpoint.total_items,
                    self.checkpoint
                )
        
        # Final save
        self.checkpoint.completed = not self._stop_requested
        self.checkpoint_manager.save(self.checkpoint)
        
        return self.checkpoint
    
    def process_parallel(
        self,
        items: List[Any],
        process_fn: Callable[[Any], Any],
        item_id_fn: Callable[[Any], str] = lambda x: str(x),
        progress_fn: Optional[Callable[[int, int, ProcessingCheckpoint], None]] = None,
        resume: bool = True
    ) -> ProcessingCheckpoint:
        """
        Process items in parallel with checkpointing.
        
        Note: process_fn must be thread-safe.
        """
        # Load or create checkpoint
        if resume:
            self.checkpoint = self.checkpoint_manager.load(self.task_name)
        
        if not self.checkpoint or self.checkpoint.completed:
            self.checkpoint = ProcessingCheckpoint(
                task_name=self.task_name,
                total_items=len(items),
                processed_items=0
            )
        
        # Find items to process (skip already processed)
        processed_ids = set()
        if self.checkpoint.last_item_id:
            # Mark all items up to and including last_item_id as processed
            for item in items:
                item_id = item_id_fn(item)
                processed_ids.add(item_id)
                if item_id == self.checkpoint.last_item_id:
                    break
        
        items_to_process = [
            item for item in items 
            if item_id_fn(item) not in processed_ids
        ]
        
        logger.info(
            f"Parallel processing {len(items_to_process)} items "
            f"with {self.max_workers} workers"
        )
        
        # Process with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            
            for item in items_to_process:
                if self._stop_requested:
                    break
                
                future = executor.submit(process_fn, item)
                futures[future] = item_id_fn(item)
            
            for future in as_completed(futures):
                if self._stop_requested:
                    break
                
                item_id = futures[future]
                
                try:
                    future.result()
                    
                    with self._lock:
                        self.checkpoint.processed_items += 1
                        self.checkpoint.last_item_id = item_id
                    
                except Exception as e:
                    with self._lock:
                        self.checkpoint.error_count += 1
                        self.checkpoint.errors.append(f"{item_id}: {str(e)}")
                    logger.warning(f"Error processing {item_id}: {e}")
                
                # Save checkpoint periodically
                if self.checkpoint.processed_items % self.checkpoint_interval == 0:
                    self.checkpoint_manager.save(self.checkpoint)
                
                # Progress callback
                if progress_fn:
                    progress_fn(
                        self.checkpoint.processed_items,
                        self.checkpoint.total_items,
                        self.checkpoint
                    )
        
        # Final save
        self.checkpoint.completed = not self._stop_requested
        self.checkpoint_manager.save(self.checkpoint)
        
        return self.checkpoint
    
    def stop(self):
        """Request processing to stop."""
        self._stop_requested = True


class IncrementalScorer:
    """
    Incrementally re-score papers when taxonomy or embeddings change.
    """
    
    def __init__(self, database, embedding_service=None):
        self.db = database
        self._embeddings = embedding_service
    
    @property
    def embeddings(self):
        if self._embeddings is None:
            from triage.embeddings import get_embedding_service
            self._embeddings = get_embedding_service()
        return self._embeddings
    
    def find_papers_needing_rescore(
        self,
        since: Optional[datetime] = None,
        taxonomy_version: Optional[str] = None
    ) -> List[Dict]:
        """
        Find papers that need re-scoring.
        
        Papers need re-scoring if:
        - They've never been scored
        - Taxonomy has been updated since last score
        - Embedding model has changed
        """
        papers = self.db.search_papers(limit=50000)
        
        need_rescore = []
        
        for paper in papers:
            # Never scored
            if not paper.get('triage_score'):
                need_rescore.append(paper)
                continue
            
            # Check if scored before cutoff
            scored_at = paper.get('scored_at')
            if since and scored_at:
                try:
                    scored_dt = datetime.fromisoformat(scored_at)
                    if scored_dt < since:
                        need_rescore.append(paper)
                        continue
                except:
                    pass
            
            # Check taxonomy version
            paper_tax_version = paper.get('taxonomy_version')
            if taxonomy_version and paper_tax_version != taxonomy_version:
                need_rescore.append(paper)
                continue
        
        return need_rescore
    
    def rescore_batch(
        self,
        papers: List[Dict],
        progress_fn: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, int]:
        """
        Re-score a batch of papers.
        
        Returns stats about rescoring.
        """
        from triage.scorer import HierarchicalScorer
        
        scorer = HierarchicalScorer(self.db, self.embeddings)
        
        stats = {
            'processed': 0,
            'updated': 0,
            'errors': 0
        }
        
        for i, paper in enumerate(papers):
            try:
                scorer.score_and_store(paper)
                stats['processed'] += 1
                stats['updated'] += 1
            except Exception as e:
                stats['errors'] += 1
                logger.warning(f"Error scoring {paper.get('paper_id')}: {e}")
            
            if progress_fn and (i + 1) % 10 == 0:
                progress_fn(i + 1, len(papers))
        
        return stats


class EmbeddingBatcher:
    """
    Batch embedding operations for efficiency.
    """
    
    def __init__(self, embedding_service=None, batch_size: int = 32):
        self._embeddings = embedding_service
        self.batch_size = batch_size
    
    @property
    def embeddings(self):
        if self._embeddings is None:
            from triage.embeddings import get_embedding_service
            self._embeddings = get_embedding_service()
        return self._embeddings
    
    def embed_papers(
        self,
        papers: List[Dict],
        progress_fn: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Embed papers in batches.
        
        Returns dict mapping paper_id -> embedding.
        """
        results = {}
        
        # Prepare texts
        texts = []
        paper_ids = []
        
        for paper in papers:
            paper_id = paper.get('paper_id')
            if not paper_id:
                continue
            
            title = paper.get('title', '')
            abstract = paper.get('abstract', '')
            text = f"{title}. {abstract}" if abstract else title
            
            texts.append(text)
            paper_ids.append(paper_id)
        
        # Embed in batches
        for batch_start in range(0, len(texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(texts))
            batch_texts = texts[batch_start:batch_end]
            batch_ids = paper_ids[batch_start:batch_end]
            
            try:
                embeddings = self.embeddings.embed(batch_texts, use_cache=True)
                
                for paper_id, embedding in zip(batch_ids, embeddings):
                    results[paper_id] = embedding
                    
            except Exception as e:
                logger.warning(f"Error embedding batch: {e}")
            
            if progress_fn:
                progress_fn(batch_end, len(texts))
        
        return results
    
    def embed_claims(
        self,
        claims: List[Dict],
        progress_fn: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Embed claims in batches.
        
        Returns dict mapping claim_id -> embedding.
        """
        results = {}
        
        texts = []
        claim_ids = []
        
        for claim in claims:
            claim_id = claim.get('claim_id')
            statement = claim.get('statement', '')
            
            if not claim_id or not statement:
                continue
            
            texts.append(statement)
            claim_ids.append(claim_id)
        
        for batch_start in range(0, len(texts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(texts))
            batch_texts = texts[batch_start:batch_end]
            batch_ids = claim_ids[batch_start:batch_end]
            
            try:
                embeddings = self.embeddings.embed(batch_texts, use_cache=True)
                
                for claim_id, embedding in zip(batch_ids, embeddings):
                    results[claim_id] = embedding
                    
            except Exception as e:
                logger.warning(f"Error embedding batch: {e}")
            
            if progress_fn:
                progress_fn(batch_end, len(texts))
        
        return results
