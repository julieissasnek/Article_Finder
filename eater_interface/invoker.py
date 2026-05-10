# Version: 3.2.2
"""
Article Finder v3 - Article Eater Invoker
Manages invocation of Article Eater CLI and job processing
"""

import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import threading
import queue
import time

from .handoff_contract import OutputImporter, OutputParser, map_eater_status_to_finder


class EaterProfile(Enum):
    """Article Eater processing profiles."""
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class HITLMode(Enum):
    """Human-in-the-loop modes."""
    OFF = "off"
    AUTO = "auto"
    REQUIRED = "required"


@dataclass
class InvocationResult:
    """Result of an Article Eater invocation."""
    success: bool
    paper_id: str
    status: Optional[str]  # SUCCESS | PARTIAL_SUCCESS | FAIL
    output_path: Optional[Path]
    error_message: Optional[str]
    exit_code: int
    duration_seconds: float


class EaterInvoker:
    """
    Invokes Article Eater CLI for processing papers.
    
    Canonical CLI:
        article_eater eat --in /path/to/job_bundle --out /path/to/output_bundle --profile deep --hitl auto
    """
    
    DEFAULT_TIMEOUT = 600  # 10 minutes per paper
    
    def __init__(
        self,
        eater_executable: str = "article_eater",
        output_base_dir: Optional[Path] = None,
        default_profile: EaterProfile = EaterProfile.STANDARD,
        default_hitl: HITLMode = HITLMode.AUTO,
        timeout: int = DEFAULT_TIMEOUT
    ):
        """
        Initialize the Article Eater invoker.
        
        Args:
            eater_executable: Path to article_eater command or just 'article_eater' if on PATH
            output_base_dir: Base directory for output bundles
            default_profile: Default processing profile
            default_hitl: Default HITL mode
            timeout: Timeout in seconds for each invocation
        """
        self.eater_executable = eater_executable
        self.output_base_dir = output_base_dir or Path.home() / "article_eater_outputs"
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.default_profile = default_profile
        self.default_hitl = default_hitl
        self.timeout = timeout
    
    def check_availability(self) -> Dict[str, Any]:
        """
        Check if Article Eater is available and working.
        
        Returns:
            Dict with 'available' bool and 'version' or 'error'
        """
        try:
            # Prefer --version, but fall back to a subcommand help check if needed.
            result = subprocess.run(
                [self.eater_executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            used_fallback = False
            if result.returncode != 0:
                used_fallback = True
                result = subprocess.run(
                    [self.eater_executable, "eat", "--help"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

            if result.returncode == 0:
                version = (result.stdout.strip() or "unknown")
                if used_fallback:
                    version = "unknown (help available)"
                return {
                    'available': True,
                    'version': version,
                    'executable': self.eater_executable
                }
            else:
                return {
                    'available': False,
                    'error': result.stderr.strip() or "Unknown error"
                }
                
        except FileNotFoundError:
            return {
                'available': False,
                'error': f"Executable not found: {self.eater_executable}"
            }
        except subprocess.TimeoutExpired:
            return {
                'available': False,
                'error': "Timeout checking Article Eater availability"
            }
        except Exception as e:
            return {
                'available': False,
                'error': str(e)
            }
    
    def invoke(
        self,
        job_bundle_path: Path,
        profile: Optional[EaterProfile] = None,
        hitl: Optional[HITLMode] = None,
        output_dir: Optional[Path] = None
    ) -> InvocationResult:
        """
        Invoke Article Eater on a single job bundle.
        
        Args:
            job_bundle_path: Path to the job bundle directory
            profile: Processing profile (fast/standard/deep)
            hitl: HITL mode (off/auto/required)
            output_dir: Custom output directory
            
        Returns:
            InvocationResult with status and paths
        """
        job_bundle_path = Path(job_bundle_path)
        
        # Validate job bundle
        paper_json = job_bundle_path / "paper.json"
        if not paper_json.exists():
            return InvocationResult(
                success=False,
                paper_id="unknown",
                status=None,
                output_path=None,
                error_message=f"Invalid job bundle: {job_bundle_path}",
                exit_code=-1,
                duration_seconds=0.0
            )
        
        # Read paper_id
        with open(paper_json) as f:
            paper_meta = json.load(f)
        paper_id = paper_meta.get('paper_id', 'unknown')
        
        # Create output directory
        if output_dir is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            safe_id = paper_id.replace(':', '_').replace('/', '_')[:50]
            output_dir = self.output_base_dir / f"output_{safe_id}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        profile = profile or self.default_profile
        hitl = hitl or self.default_hitl
        
        cmd = [
            self.eater_executable,
            "eat",
            "--in", str(job_bundle_path),
            "--out", str(output_dir),
            "--profile", profile.value,
            "--hitl", hitl.value
        ]
        
        # Execute
        start_time = time.time()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            duration = time.time() - start_time
            
            # Check for result.json
            result_json = output_dir / "result.json"
            
            if result_json.exists():
                with open(result_json) as f:
                    result_data = json.load(f)
                
                return InvocationResult(
                    success=result.returncode == 0,
                    paper_id=paper_id,
                    status=result_data.get('status'),
                    output_path=output_dir,
                    error_message=None if result.returncode == 0 else result.stderr,
                    exit_code=result.returncode,
                    duration_seconds=duration
                )
            else:
                return InvocationResult(
                    success=False,
                    paper_id=paper_id,
                    status="FAIL",
                    output_path=output_dir,
                    error_message=result.stderr or "No result.json produced",
                    exit_code=result.returncode,
                    duration_seconds=duration
                )
                
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return InvocationResult(
                success=False,
                paper_id=paper_id,
                status="FAIL",
                output_path=output_dir,
                error_message=f"Timeout after {self.timeout} seconds",
                exit_code=-1,
                duration_seconds=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            return InvocationResult(
                success=False,
                paper_id=paper_id,
                status="FAIL",
                output_path=output_dir,
                error_message=str(e),
                exit_code=-1,
                duration_seconds=duration
            )


class BatchInvoker:
    """
    Process multiple job bundles with Article Eater.
    Supports parallel processing and progress tracking.
    """
    
    def __init__(
        self,
        invoker: EaterInvoker,
        max_workers: int = 1,  # Default to sequential for stability
        database = None
    ):
        """
        Initialize batch invoker.
        
        Args:
            invoker: EaterInvoker instance
            max_workers: Maximum parallel workers (1 = sequential)
            database: Optional Database instance for status updates
        """
        self.invoker = invoker
        self.max_workers = max_workers
        self.database = database
        self.results: List[InvocationResult] = []
        self._progress_callback = None
    
    def set_progress_callback(self, callback):
        """Set a callback function(current, total, result) for progress updates."""
        self._progress_callback = callback
    
    def process_bundles(
        self,
        bundle_paths: List[Path],
        profile: Optional[EaterProfile] = None,
        hitl: Optional[HITLMode] = None
    ) -> Dict[str, Any]:
        """
        Process multiple job bundles.
        
        Args:
            bundle_paths: List of job bundle paths
            profile: Processing profile
            hitl: HITL mode
            
        Returns:
            Summary dict with results
        """
        self.results = []
        total = len(bundle_paths)
        
        if self.max_workers == 1:
            # Sequential processing
            for i, bundle_path in enumerate(bundle_paths):
                result = self._process_single(bundle_path, profile, hitl)
                self.results.append(result)
                
                if self._progress_callback:
                    self._progress_callback(i + 1, total, result)
        else:
            # Parallel processing with thread pool
            self._process_parallel(bundle_paths, profile, hitl)
        
        return self._make_summary()
    
    def _process_single(
        self,
        bundle_path: Path,
        profile: Optional[EaterProfile],
        hitl: Optional[HITLMode]
    ) -> InvocationResult:
        """Process a single bundle and update database."""
        
        # Update status to eater_running if we have database
        if self.database:
            paper_json = bundle_path / "paper.json"
            if paper_json.exists():
                with open(paper_json) as f:
                    paper_id = json.load(f).get('paper_id')
                if paper_id:
                    try:
                        self.database.update_paper_status(paper_id, 'eater_running')
                    except ValueError:
                        pass  # Status transition not valid
        
        # Invoke Article Eater
        result = self.invoker.invoke(bundle_path, profile, hitl)
        
        # Update database with result
        if self.database and result.output_path:
            try:
                importer = OutputImporter(self.database)
                importer.import_bundle(result.output_path)
            except Exception as e:
                print(f"Warning: Failed to import results for {result.paper_id}: {e}")
        
        return result
    
    def _process_parallel(
        self,
        bundle_paths: List[Path],
        profile: Optional[EaterProfile],
        hitl: Optional[HITLMode]
    ):
        """Process bundles in parallel using threads."""
        work_queue = queue.Queue()
        result_queue = queue.Queue()
        
        # Fill work queue
        for path in bundle_paths:
            work_queue.put(path)
        
        def worker():
            while True:
                try:
                    bundle_path = work_queue.get_nowait()
                except queue.Empty:
                    break
                
                result = self._process_single(bundle_path, profile, hitl)
                result_queue.put(result)
                work_queue.task_done()
        
        # Start workers
        threads = []
        for _ in range(min(self.max_workers, len(bundle_paths))):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        
        # Collect results with progress updates
        total = len(bundle_paths)
        collected = 0
        
        while collected < total:
            try:
                result = result_queue.get(timeout=1)
                self.results.append(result)
                collected += 1
                
                if self._progress_callback:
                    self._progress_callback(collected, total, result)
            except queue.Empty:
                continue
        
        # Wait for threads to finish
        for t in threads:
            t.join()
    
    def _make_summary(self) -> Dict[str, Any]:
        """Create summary of batch processing."""
        success_count = sum(1 for r in self.results if r.success)
        partial_count = sum(1 for r in self.results if r.status == 'PARTIAL_SUCCESS')
        fail_count = sum(1 for r in self.results if r.status == 'FAIL' or not r.success)
        
        total_duration = sum(r.duration_seconds for r in self.results)
        avg_duration = total_duration / len(self.results) if self.results else 0
        
        return {
            'total': len(self.results),
            'success': success_count,
            'partial_success': partial_count,
            'failed': fail_count,
            'total_duration_seconds': total_duration,
            'avg_duration_seconds': avg_duration,
            'results': [
                {
                    'paper_id': r.paper_id,
                    'success': r.success,
                    'status': r.status,
                    'output_path': str(r.output_path) if r.output_path else None,
                    'duration_seconds': r.duration_seconds,
                    'error': r.error_message
                }
                for r in self.results
            ]
        }


class EaterJobQueue:
    """
    Manages a queue of papers to be processed by Article Eater.
    Integrates with database status tracking.
    """
    
    def __init__(self, database, invoker: EaterInvoker):
        """
        Initialize job queue.
        
        Args:
            database: Database instance
            invoker: EaterInvoker instance
        """
        self.db = database
        self.invoker = invoker
        self.batch_invoker = BatchInvoker(invoker, database=database)
    
    def queue_paper(self, paper_id: str) -> bool:
        """
        Add a paper to the Article Eater queue.
        
        Args:
            paper_id: Paper ID to queue
            
        Returns:
            True if successfully queued
        """
        try:
            self.db.update_paper_status(paper_id, 'queued_for_eater')
            return True
        except ValueError as e:
            print(f"Cannot queue paper {paper_id}: {e}")
            return False
    
    def get_queued_papers(self) -> List[Dict]:
        """Get all papers queued for Article Eater."""
        return self.db.get_papers_by_status('queued_for_eater')
    
    def process_queue(
        self,
        job_bundle_dir: Path,
        profile: EaterProfile = EaterProfile.STANDARD,
        hitl: HITLMode = HITLMode.AUTO,
        limit: Optional[int] = None,
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        Process all queued papers.
        
        Args:
            job_bundle_dir: Directory containing job bundles
            profile: Processing profile
            hitl: HITL mode
            limit: Maximum papers to process
            progress_callback: Progress callback function
            
        Returns:
            Processing summary
        """
        queued = self.get_queued_papers()
        
        if limit:
            queued = queued[:limit]
        
        if not queued:
            return {'total': 0, 'message': 'No papers in queue'}
        
        # Find job bundles for queued papers
        bundle_paths = []
        for paper in queued:
            # Look for matching bundle
            paper_id = paper['paper_id']
            safe_id = paper_id.replace(':', '_').replace('/', '_')[:50]
            
            # Find bundle by pattern
            bundles = list(job_bundle_dir.glob(f"job_{safe_id}*"))
            if bundles:
                bundle_paths.append(bundles[0])
                # Update status to sent
                try:
                    self.db.update_paper_status(paper_id, 'sent_to_eater')
                except ValueError:
                    pass
        
        if not bundle_paths:
            return {'total': 0, 'message': 'No job bundles found for queued papers'}
        
        # Process bundles
        if progress_callback:
            self.batch_invoker.set_progress_callback(progress_callback)
        
        return self.batch_invoker.process_bundles(bundle_paths, profile, hitl)
