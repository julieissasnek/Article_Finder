# Version: 3.2.2
"""
Article Finder v3 - Integration Orchestrator
Main pipeline coordination between Article Finder and Article Eater
"""

import yaml
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
import logging

from core.database import Database, get_database
from triage.classifier import HierarchicalClassifier, TriageFilter
from eater_interface.job_bundle import JobBundleBuilder, BatchBundleBuilder
from eater_interface.invoker import EaterInvoker, BatchInvoker, EaterJobQueue, EaterProfile, HITLMode
from eater_interface.output_parser import OutputImporter

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the AF-AE pipeline."""
    
    # Paths
    data_dir: Path
    taxonomy_path: Path
    job_bundles_dir: Path
    eater_outputs_dir: Path
    pdf_storage_dir: Path
    
    # Article Eater settings
    eater_executable: str = "article_eater"
    eater_profile: str = "standard"
    eater_hitl: str = "auto"
    eater_timeout: int = 600
    
    # Triage settings
    domain_threshold_accept: float = 0.5
    domain_threshold_reject: float = 0.3
    auto_queue_threshold: float = 0.7
    
    # Processing settings
    batch_size: int = 10
    max_parallel_workers: int = 1
    
    @classmethod
    def from_yaml(cls, path: Path) -> 'PipelineConfig':
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        
        # Convert string paths to Path objects
        for key in ['data_dir', 'taxonomy_path', 'job_bundles_dir', 
                    'eater_outputs_dir', 'pdf_storage_dir']:
            if key in data:
                data[key] = Path(data[key])
        
        return cls(**data)
    
    def to_yaml(self, path: Path) -> None:
        """Save config to YAML file."""
        data = asdict(self)
        # Convert Path objects to strings
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)
        
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)


class ArticleFinderPipeline:
    """
    Main orchestrator for the Article Finder → Article Eater pipeline.
    
    Pipeline stages:
    1. INGEST: Import papers from various sources
    2. TRIAGE: Classify papers and filter by relevance
    3. ACQUIRE: Download PDFs for accepted papers
    4. BUNDLE: Create job bundles for Article Eater
    5. PROCESS: Invoke Article Eater
    6. IMPORT: Parse and store Article Eater outputs
    7. EXPAND: Add cited papers to corpus
    """
    
    def __init__(self, config: PipelineConfig):
        """
        Initialize the pipeline.
        
        Args:
            config: PipelineConfig instance
        """
        self.config = config
        
        # Ensure directories exist
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.job_bundles_dir.mkdir(parents=True, exist_ok=True)
        config.eater_outputs_dir.mkdir(parents=True, exist_ok=True)
        config.pdf_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self.db = get_database(config.data_dir / "article_finder.db")
        
        # Initialize classifier (taxonomy loaded separately)
        self.classifier = HierarchicalClassifier()
        self.triage_filter = TriageFilter(self.classifier, self.db)
        
        # Initialize Article Eater components
        self.bundle_builder = JobBundleBuilder(config.job_bundles_dir)
        self.eater_invoker = EaterInvoker(
            eater_executable=config.eater_executable,
            output_base_dir=config.eater_outputs_dir,
            default_profile=EaterProfile(config.eater_profile),
            default_hitl=HITLMode(config.eater_hitl),
            timeout=config.eater_timeout
        )
        self.job_queue = EaterJobQueue(self.db, self.eater_invoker)
        
        # Load taxonomy if exists
        if config.taxonomy_path.exists():
            self.load_taxonomy(config.taxonomy_path)
    
    def load_taxonomy(self, path: Path) -> None:
        """Load taxonomy from YAML file and initialize classifier."""
        logger.info(f"Loading taxonomy from {path}")
        
        with open(path) as f:
            taxonomy_data = yaml.safe_load(f)
        
        # Load into database
        self.db.load_taxonomy(taxonomy_data)
        
        # Load into classifier
        self.classifier.load_taxonomy(taxonomy_data)
        
        # Check for precomputed centroids
        centroids_path = path.parent / "centroids.json"
        if centroids_path.exists():
            logger.info(f"Loading precomputed centroids from {centroids_path}")
            self.classifier.load_centroids(centroids_path)
        else:
            logger.info("No precomputed centroids found. Run build_centroids() to compute.")
    
    def build_centroids(
        self,
        paper_abstracts: Optional[Dict[str, str]] = None,
        node_exemplars: Optional[Dict[str, List[str]]] = None,
        save_path: Optional[Path] = None
    ) -> None:
        """
        Build centroid embeddings for taxonomy nodes.
        
        Args:
            paper_abstracts: Dict of paper_id -> abstract text
            node_exemplars: Dict of node_id -> list of paper_ids
            save_path: Path to save computed centroids
        """
        # If no abstracts provided, get from database
        if paper_abstracts is None:
            papers = self.db.search_papers(limit=10000)
            paper_abstracts = {
                p['paper_id']: p.get('abstract', '')
                for p in papers
                if p.get('abstract')
            }
        
        logger.info(f"Building centroids with {len(paper_abstracts)} paper abstracts")
        self.classifier.build_centroids(paper_abstracts, node_exemplars)
        
        if save_path:
            self.classifier.save_centroids(save_path)
            logger.info(f"Saved centroids to {save_path}")
    
    # ================================================================
    # STAGE 1: INGEST
    # ================================================================
    
    def ingest_papers(self, papers: List[Dict[str, Any]], source: str = 'manual') -> Dict[str, Any]:
        """
        Ingest papers into the corpus.
        
        Args:
            papers: List of paper dicts with at least 'title'
            source: Source identifier
            
        Returns:
            Summary of ingestion
        """
        added = 0
        duplicates = 0
        errors = []
        
        for paper in papers:
            try:
                # Check for duplicates by DOI
                if paper.get('doi'):
                    existing = self.db.get_paper_by_doi(paper['doi'])
                    if existing:
                        duplicates += 1
                        continue
                
                paper['source'] = source
                paper['retrieved_at'] = datetime.utcnow().isoformat()
                
                self.db.add_paper(paper)
                added += 1
                
            except Exception as e:
                errors.append({'paper': paper.get('title', 'unknown'), 'error': str(e)})
        
        return {
            'added': added,
            'duplicates': duplicates,
            'errors': errors
        }
    
    # ================================================================
    # STAGE 2: TRIAGE
    # ================================================================
    
    def triage_candidates(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Triage all candidate papers.
        
        Args:
            limit: Maximum papers to process
            
        Returns:
            Triage summary
        """
        candidates = self.db.get_papers_by_status('candidate')
        
        if limit:
            candidates = candidates[:limit]
        
        if not candidates:
            return {'processed': 0, 'message': 'No candidates to triage'}
        
        logger.info(f"Triaging {len(candidates)} candidate papers")
        
        decisions = self.triage_filter.triage_batch(candidates, store_results=True)
        
        # Auto-queue high-confidence papers
        auto_queued = 0
        for paper_id in decisions['send_to_eater']:
            paper = self.db.get_paper(paper_id)
            if paper and paper.get('triage_score', 0) >= self.config.auto_queue_threshold:
                if paper.get('pdf_path') and Path(paper['pdf_path']).exists():
                    self.job_queue.queue_paper(paper_id)
                    auto_queued += 1
        
        return {
            'processed': len(candidates),
            'send_to_eater': len(decisions['send_to_eater']),
            'review': len(decisions['review']),
            'reject': len(decisions['reject']),
            'auto_queued': auto_queued
        }
    
    # ================================================================
    # STAGE 3: ACQUIRE (stub - implement PDF downloading)
    # ================================================================
    
    def acquire_pdfs(self, paper_ids: List[str]) -> Dict[str, Any]:
        """
        Download PDFs for papers.
        
        Note: This is a stub - implement with actual PDF sources
        (Unpaywall, institutional access, etc.)
        """
        # TODO: Implement PDF acquisition
        logger.warning("PDF acquisition not yet implemented")
        return {'acquired': 0, 'failed': len(paper_ids)}
    
    # ================================================================
    # STAGE 4: BUNDLE
    # ================================================================
    
    def create_job_bundles(
        self,
        paper_ids: Optional[List[str]] = None,
        status_filter: str = 'downloaded',
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create job bundles for papers ready to process.
        
        Args:
            paper_ids: Specific papers to bundle (optional)
            status_filter: Status to filter by if paper_ids not provided
            
        Returns:
            Bundle creation summary
        """
        if paper_ids:
            papers = [self.db.get_paper(pid) for pid in paper_ids]
            papers = [p for p in papers if p]
        else:
            papers = self.db.get_papers_by_status(status_filter)
        
        if limit:
            papers = papers[:limit]

        if not papers:
            return {'bundles_created': 0, 'message': 'No papers to bundle'}
        
        batch_builder = BatchBundleBuilder(self.config.job_bundles_dir)
        
        for paper in papers:
            if not paper.get('pdf_path'):
                continue
            
            pdf_path = Path(paper['pdf_path'])
            if not pdf_path.exists():
                continue
            
            # Get citations if available
            citations = self.db.get_citations_from(paper['paper_id'])
            
            batch_builder.add_paper(
                paper,
                pdf_path,
                include_abstract=True,
                include_citations=bool(citations),
                citations=citations if citations else None
            )
        
        summary = batch_builder.get_summary()
        summary['bundles_created'] = summary.get('valid', 0)
        
        # Queue valid bundles
        for bundle_path in batch_builder.get_valid_bundles():
            # Extract paper_id from bundle
            paper_json = bundle_path / "paper.json"
            if paper_json.exists():
                with open(paper_json) as f:
                    paper_id = json.load(f).get('paper_id')
                if paper_id:
                    self.job_queue.queue_paper(paper_id)
        
        return summary
    
    # ================================================================
    # STAGE 5: PROCESS
    # ================================================================
    
    def process_queue(
        self,
        limit: Optional[int] = None,
        profile: Optional[str] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Process papers queued for Article Eater.
        
        Args:
            limit: Maximum papers to process
            profile: Override processing profile
            progress_callback: Callback for progress updates
            
        Returns:
            Processing summary
        """
        eater_profile = EaterProfile(profile) if profile else None
        
        return self.job_queue.process_queue(
            job_bundle_dir=self.config.job_bundles_dir,
            profile=eater_profile or EaterProfile(self.config.eater_profile),
            hitl=HITLMode(self.config.eater_hitl),
            limit=limit,
            progress_callback=progress_callback
        )
    
    def run_eater_batch(
        self,
        status_filter: str = 'send_to_eater',
        max_papers: Optional[int] = None,
        time_budget_seconds: Optional[int] = None,
        profile: Optional[str] = None,
        progress_callback=None,
        continuous: bool = False,
        idle_sleep_seconds: int = 30,
        stop_event=None
    ) -> Dict[str, Any]:
        """
        Run Article Eater in a time- or count-limited batch loop.

        This builds bundles, queues papers, processes them one at a time,
        and imports outputs via the invoker.
        """
        start = time.monotonic()
        processed = 0
        summaries = []

        while True:
            if stop_event is not None and getattr(stop_event, 'is_set', lambda: False)():
                break
            if max_papers is not None and processed >= max_papers:
                break
            if time_budget_seconds is not None and (time.monotonic() - start) >= time_budget_seconds:
                break

            queued = self.job_queue.get_queued_papers()
            if not queued:
                remaining = None
                if max_papers is not None:
                    remaining = max_papers - processed
                    if remaining <= 0:
                        break

                bundle_summary = self.create_job_bundles(
                    status_filter=status_filter,
                    limit=remaining
                )
                if bundle_summary.get('bundles_created', 0) == 0:
                    if continuous:
                        if progress_callback:
                            elapsed = time.monotonic() - start
                            remaining_sec = None
                            if time_budget_seconds is not None:
                                remaining_sec = max(0, time_budget_seconds - elapsed)
                            progress_callback(
                                {
                                    'processed': processed,
                                    'elapsed_seconds': elapsed,
                                    'remaining_seconds': remaining_sec,
                                    'state': 'idle',
                                    'last_summary': bundle_summary
                                }
                            )
                        time.sleep(max(1, idle_sleep_seconds))
                        continue
                    break

            summary = self.process_queue(limit=1, profile=profile)
            summaries.append(summary)
            processed += summary.get('total', 0)

            if progress_callback:
                elapsed = time.monotonic() - start
                remaining_sec = None
                if time_budget_seconds is not None:
                    remaining_sec = max(0, time_budget_seconds - elapsed)
                progress_callback(
                    {
                        'processed': processed,
                        'elapsed_seconds': elapsed,
                        'remaining_seconds': remaining_sec,
                        'state': 'running',
                        'last_summary': summary
                    }
                )

        return {
            'processed': processed,
            'elapsed_seconds': time.monotonic() - start,
            'summaries': summaries
        }

    # ================================================================
    # STAGE 6: IMPORT
    # ================================================================
    
    def import_eater_outputs(self, output_dirs: Optional[List[Path]] = None) -> Dict[str, Any]:
        """
        Import Article Eater outputs into database.
        
        Args:
            output_dirs: Specific output directories to import
                        (if None, finds unimported outputs)
            
        Returns:
            Import summary
        """
        if output_dirs is None:
            # Find all output directories
            output_dirs = [
                d for d in self.config.eater_outputs_dir.iterdir()
                if d.is_dir() and (d / "result.json").exists()
            ]
        
        importer = OutputImporter(self.db)
        results = []
        
        for output_dir in output_dirs:
            try:
                result = importer.import_bundle(output_dir)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to import {output_dir}: {e}")
                results.append({
                    'output_dir': str(output_dir),
                    'error': str(e)
                })
        
        return {
            'imported': sum(1 for r in results if 'claims_imported' in r),
            'failed': sum(1 for r in results if 'error' in r),
            'total_claims': sum(r.get('claims_imported', 0) for r in results),
            'total_rules': sum(r.get('rules_imported', 0) for r in results),
            'results': results
        }
    
    # ================================================================
    # STAGE 7: EXPAND
    # ================================================================
    
    def expand_from_citations(
        self,
        max_additions: int = 100,
        min_citation_count: int = 2
    ) -> Dict[str, Any]:
        """
        Add highly-cited papers from references to expansion queue.
        
        Args:
            max_additions: Maximum papers to add
            min_citation_count: Minimum times a paper must be cited
            
        Returns:
            Expansion summary
        """
        # Get all citations
        with self.db.connection() as conn:
            rows = conn.execute("""
                SELECT cited_doi, cited_title, COUNT(*) as cite_count
                FROM citations
                WHERE cited_doi IS NOT NULL
                  AND cited_paper_id IS NULL
                GROUP BY cited_doi
                HAVING COUNT(*) >= ?
                ORDER BY cite_count DESC
                LIMIT ?
            """, (min_citation_count, max_additions)).fetchall()
        
        added = 0
        for row in rows:
            self.db.add_to_expansion_queue(
                doi=row['cited_doi'],
                title=row['cited_title'],
                priority_score=min(1.0, row['cite_count'] / 10.0)  # Normalize
            )
            added += 1
        
        return {
            'added_to_queue': added,
            'min_citations': min_citation_count
        }
    
    # ================================================================
    # FULL PIPELINE
    # ================================================================
    
    def run_full_pipeline(
        self,
        triage_limit: Optional[int] = None,
        process_limit: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Run the complete pipeline from triage to import.
        
        Args:
            triage_limit: Max papers to triage
            process_limit: Max papers to process
            progress_callback: Progress callback
            
        Returns:
            Complete pipeline summary
        """
        results = {}
        
        # Stage 2: Triage
        logger.info("Stage 2: Triaging candidates...")
        results['triage'] = self.triage_candidates(limit=triage_limit)
        
        # Stage 4: Bundle (for papers that already have PDFs)
        logger.info("Stage 4: Creating job bundles...")
        results['bundle'] = self.create_job_bundles()
        
        # Stage 5: Process
        logger.info("Stage 5: Processing with Article Eater...")
        results['process'] = self.process_queue(
            limit=process_limit,
            progress_callback=progress_callback
        )
        
        # Stage 6: Import
        logger.info("Stage 6: Importing Article Eater outputs...")
        results['import'] = self.import_eater_outputs()
        
        # Stage 7: Expand
        logger.info("Stage 7: Expanding from citations...")
        results['expand'] = self.expand_from_citations()
        
        return results
    
    # ================================================================
    # STATUS & STATS
    # ================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status."""
        stats = self.db.get_corpus_stats()
        
        # Add classifier stats
        stats['taxonomy'] = self.classifier.get_node_stats()
        
        # Add queue status
        stats['queue'] = {
            'pending': len(self.job_queue.get_queued_papers())
        }
        
        # Check Article Eater availability
        stats['article_eater'] = self.eater_invoker.check_availability()
        
        return stats


def create_default_config(base_dir: Path) -> PipelineConfig:
    """Create a default configuration."""
    return PipelineConfig(
        data_dir=base_dir / "data",
        taxonomy_path=base_dir / "config" / "taxonomy.yaml",
        job_bundles_dir=base_dir / "job_bundles",
        eater_outputs_dir=base_dir / "eater_outputs",
        pdf_storage_dir=base_dir / "pdfs"
    )
