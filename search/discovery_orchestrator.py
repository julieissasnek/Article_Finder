# Version: 3.2.5
"""
Article Finder v3.2.5 - Discovery Orchestrator
Automated corpus expansion and acquisition pipeline with AE-driven search.

This is the master controller that runs the discovery loop:
1. Import seeds → 2. Classify → 3. Expand → 4. Acquire PDFs → 5. Send to AE
6. NEW: Process AE feedback → 7. NEW: Gap analysis → 8. NEW: Targeted search → 9. Repeat

v3.2.5 additions:
- AE feedback processing (ingest claims/rules, identify new gaps)
- Gap analysis phase (find under-covered cells, theories, mechanisms)
- Bibliographer integration (theory, neural, mechanism cell types)
- Closed-loop search: AE tells us what's missing, we search for it

It tracks progress, handles errors gracefully, and provides detailed reporting.
"""

import logging
import time
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class DiscoveryPhase(Enum):
    """Phases of the discovery pipeline."""
    IDLE = "idle"
    IMPORTING = "importing"
    CLASSIFYING = "classifying"
    EXPANDING = "expanding"
    ACQUIRING = "acquiring"
    BUILDING_JOBS = "building_jobs"
    # v3.2.5: New phases for AE-driven search
    AE_FEEDBACK = "ae_feedback"       # Process AE outputs
    GAP_ANALYSIS = "gap_analysis"     # Find knowledge gaps
    TARGETED_SEARCH = "targeted_search"  # Search for theories, neural, mechanisms
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PhaseStats:
    """Statistics for a single phase."""
    phase: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    items_processed: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'phase': self.phase,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'duration_seconds': self.duration_seconds,
            'items_processed': self.items_processed,
            'items_succeeded': self.items_succeeded,
            'items_failed': self.items_failed,
            'details': self.details
        }


@dataclass
class DiscoveryRun:
    """Complete discovery run with all phase statistics."""
    run_id: str
    started_at: str
    completed_at: Optional[str] = None
    status: str = "running"
    phases: List[PhaseStats] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Aggregate stats
    total_papers_discovered: int = 0
    total_papers_queued: int = 0
    total_pdfs_acquired: int = 0
    total_jobs_created: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'run_id': self.run_id,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'status': self.status,
            'phases': [p.to_dict() for p in self.phases],
            'config': self.config,
            'total_papers_discovered': self.total_papers_discovered,
            'total_papers_queued': self.total_papers_queued,
            'total_pdfs_acquired': self.total_pdfs_acquired,
            'total_jobs_created': self.total_jobs_created
        }


class DiscoveryOrchestrator:
    """
    Master controller for the corpus discovery pipeline.
    
    Coordinates:
    - Import: Load initial corpus from files
    - Classification: Score papers against taxonomy
    - Expansion: Discover related papers via citations
    - Acquisition: Download available PDFs
    - Job Creation: Prepare bundles for Article Eater
    """
    
    def __init__(
        self,
        database,
        email: str,
        relevance_threshold: float = 0.35,
        max_expansion_depth: int = 2,
        pdf_directory: Optional[Path] = None,
        job_output_directory: Optional[Path] = None,
        progress_callback: Optional[Callable] = None
    ):
        """
        Args:
            database: Database instance
            email: Email for API access
            relevance_threshold: Minimum taxonomy score for expansion (0-1)
            max_expansion_depth: Maximum citation hops
            pdf_directory: Where to store downloaded PDFs
            job_output_directory: Where to write job bundles
            progress_callback: Optional callback(phase, message, stats)
        """
        self.db = database
        self.email = email
        self.threshold = relevance_threshold
        self.max_depth = max_expansion_depth
        self.pdf_dir = pdf_directory or Path('data/pdfs')
        self.job_dir = job_output_directory or Path('data/job_bundles')
        self.progress_callback = progress_callback
        
        # Current state
        self.current_phase = DiscoveryPhase.IDLE
        self.current_run: Optional[DiscoveryRun] = None
        
        # Lazy-loaded components
        self._expander = None
        self._downloader = None
        self._scorer = None
        self._bibliographer = None
        self._gap_analyzer = None
        self._ae_feedback = None
    
    def _report_progress(self, message: str, stats: Optional[Dict] = None):
        """Report progress to callback if registered."""
        if self.progress_callback:
            self.progress_callback(self.current_phase.value, message, stats or {})
        logger.info(f"[{self.current_phase.value}] {message}")
    
    def _start_phase(self, phase: DiscoveryPhase) -> PhaseStats:
        """Start a new phase."""
        self.current_phase = phase
        stats = PhaseStats(
            phase=phase.value,
            started_at=datetime.utcnow().isoformat()
        )
        self._report_progress(f"Starting {phase.value}")
        return stats
    
    def _end_phase(self, stats: PhaseStats):
        """End current phase."""
        stats.completed_at = datetime.utcnow().isoformat()
        start = datetime.fromisoformat(stats.started_at)
        end = datetime.fromisoformat(stats.completed_at)
        stats.duration_seconds = (end - start).total_seconds()
        
        if self.current_run:
            self.current_run.phases.append(stats)
        
        self._report_progress(
            f"Completed {stats.phase}: {stats.items_succeeded}/{stats.items_processed} succeeded",
            stats.to_dict()
        )
    
    def run_discovery(
        self,
        import_file: Optional[Path] = None,
        expansion_limit: int = 50,
        pdf_limit: int = 100,
        max_iterations: int = 3,
        stop_on_saturation: bool = True,
        # v3.2.5: New options for AE-driven search
        run_ae_feedback: bool = True,
        run_gap_analysis: bool = True,
        run_targeted_search: bool = True,
        targeted_search_limit: int = 30
    ) -> DiscoveryRun:
        """
        Run a complete discovery cycle.

        Args:
            import_file: Optional file to import first
            expansion_limit: Max papers to expand per iteration
            pdf_limit: Max PDFs to download
            max_iterations: Max expansion iterations
            stop_on_saturation: Stop if expansion yields few new papers
            run_ae_feedback: Process AE outputs to find new gaps (v3.2.5)
            run_gap_analysis: Analyze taxonomy coverage gaps (v3.2.5)
            run_targeted_search: Search for theories, neural, mechanisms (v3.2.5)
            targeted_search_limit: Papers per targeted search cell (v3.2.5)

        Returns:
            DiscoveryRun with complete statistics
        """
        # Initialize run
        run_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.current_run = DiscoveryRun(
            run_id=run_id,
            started_at=datetime.utcnow().isoformat(),
            config={
                'relevance_threshold': self.threshold,
                'max_expansion_depth': self.max_depth,
                'expansion_limit': expansion_limit,
                'pdf_limit': pdf_limit,
                'max_iterations': max_iterations,
                'run_ae_feedback': run_ae_feedback,
                'run_gap_analysis': run_gap_analysis,
                'run_targeted_search': run_targeted_search
            }
        )

        try:
            # Phase 1: Import (optional)
            if import_file:
                self._run_import_phase(import_file)

            # Phase 2: Classification
            self._run_classification_phase()

            # Phase 3: Expansion (iterative)
            for iteration in range(max_iterations):
                queued = self._run_expansion_phase(expansion_limit, iteration + 1)

                # Check for saturation
                if stop_on_saturation and queued < 5:
                    self._report_progress(f"Saturation reached at iteration {iteration + 1}")
                    break

                # Process expansion queue
                self._run_queue_processing_phase()

            # Phase 4: PDF Acquisition
            self._run_acquisition_phase(pdf_limit)

            # Phase 5: Job Bundle Creation
            self._run_job_creation_phase()

            # =========================================================
            # v3.2.5: AE-Driven Search Phases
            # =========================================================

            # Phase 6: Process AE feedback (if enabled)
            if run_ae_feedback:
                self._run_ae_feedback_phase()

            # Phase 7: Gap analysis (if enabled)
            if run_gap_analysis:
                self._run_gap_analysis_phase()

            # Phase 8: Targeted search for theories, neural, mechanisms (if enabled)
            if run_targeted_search:
                self._run_targeted_search_phase(targeted_search_limit)

            self.current_run.status = "complete"
            self.current_run.completed_at = datetime.utcnow().isoformat()
            self.current_phase = DiscoveryPhase.COMPLETE

        except Exception as e:
            logger.error(f"Discovery run failed: {e}")
            self.current_run.status = "error"
            self.current_run.completed_at = datetime.utcnow().isoformat()
            self.current_phase = DiscoveryPhase.ERROR
            raise

        return self.current_run
    
    def _run_import_phase(self, import_file: Path):
        """Run the import phase."""
        stats = self._start_phase(DiscoveryPhase.IMPORTING)
        
        try:
            from ingest.smart_importer import SmartImporter
            from ingest.citation_parser import CitationParser
            
            importer = SmartImporter(
                database=self.db,
                citation_parser=CitationParser()
            )
            
            result = importer.import_file(
                import_file,
                source_name=import_file.stem,
                resolve_dois=True,
                parse_citations=True
            )
            
            stats.items_processed = result.get('total_rows', 0)
            stats.items_succeeded = result.get('papers_created', 0)
            stats.items_failed = len(result.get('errors', []))
            stats.details = result
            
        except Exception as e:
            stats.items_failed += 1
            stats.details['error'] = str(e)
            logger.error(f"Import failed: {e}")
        
        self._end_phase(stats)
    
    def _run_classification_phase(self):
        """Run the classification phase."""
        stats = self._start_phase(DiscoveryPhase.CLASSIFYING)
        
        try:
            from triage.scorer import TaxonomyScorer
            from triage.taxonomy_loader import TaxonomyLoader
            
            # Load taxonomy
            taxonomy_path = Path(__file__).parent.parent / 'config' / 'taxonomy.yaml'
            loader = TaxonomyLoader(self.db, taxonomy_path)
            loader.load_and_store()
            
            # Score unscored papers
            scorer = TaxonomyScorer(self.db)
            scorer.build_centroids()
            
            papers = self.db.search_papers(limit=10000)
            unscored = [p for p in papers if not p.get('taxonomy_scores')]
            
            stats.items_processed = len(unscored)
            
            for paper in unscored:
                try:
                    scorer.score_and_store(paper)
                    stats.items_succeeded += 1
                except Exception as e:
                    stats.items_failed += 1
                    logger.warning(f"Failed to score {paper.get('paper_id')}: {e}")
            
        except Exception as e:
            stats.details['error'] = str(e)
            logger.error(f"Classification failed: {e}")
        
        self._end_phase(stats)
    
    def _run_expansion_phase(self, limit: int, iteration: int) -> int:
        """Run one expansion iteration. Returns papers queued."""
        stats = self._start_phase(DiscoveryPhase.EXPANDING)
        stats.details['iteration'] = iteration
        
        queued = 0
        
        try:
            from search.bounded_expander import BoundedExpander
            
            if self._expander is None:
                self._expander = BoundedExpander(
                    database=self.db,
                    email=self.email,
                    relevance_threshold=self.threshold,
                    max_depth=self.max_depth
                )
            
            result = self._expander.expand_corpus(
                limit=limit,
                papers_with_status='send_to_eater'
            )
            
            stats.items_processed = result.scored
            stats.items_succeeded = result.queued
            stats.items_failed = result.rejected
            stats.details.update(result.to_dict())
            
            queued = result.queued
            self.current_run.total_papers_discovered += result.citations_discovered + result.references_discovered
            self.current_run.total_papers_queued += result.queued
            
        except Exception as e:
            stats.details['error'] = str(e)
            logger.error(f"Expansion failed: {e}")
        
        self._end_phase(stats)
        return queued
    
    def _run_queue_processing_phase(self):
        """Process expansion queue - add queued papers to corpus."""
        stats = self._start_phase(DiscoveryPhase.IMPORTING)
        stats.details['source'] = 'expansion_queue'
        
        try:
            queue = self.db.get_expansion_queue(status='pending', limit=500)
            stats.items_processed = len(queue)
            
            for item in queue:
                try:
                    # Create paper record from queue item
                    paper = {
                        'paper_id': f"doi:{item['doi']}" if item.get('doi') else f"title:{item.get('title', 'unknown')[:50]}",
                        'doi': item.get('doi'),
                        'title': item.get('title'),
                        'authors': item.get('authors', []),
                        'year': item.get('year'),
                        'abstract': item.get('abstract'),
                        'source': 'expansion',
                        'triage_decision': 'needs_review',
                        'discovery_metadata': {
                            'discovered_from': item.get('discovered_from'),
                            'discovery_type': item.get('discovery_type'),
                            'relevance_score': item.get('relevance_score')
                        }
                    }
                    
                    self.db.add_paper(paper)
                    
                    # Update queue status
                    self.db.update_expansion_queue_status(item.get('doi'), 'processed')
                    
                    stats.items_succeeded += 1
                    
                except Exception as e:
                    stats.items_failed += 1
                    logger.warning(f"Failed to process queue item: {e}")
            
        except Exception as e:
            stats.details['error'] = str(e)
            logger.error(f"Queue processing failed: {e}")
        
        self._end_phase(stats)
    
    def _run_acquisition_phase(self, limit: int):
        """Run PDF acquisition phase."""
        stats = self._start_phase(DiscoveryPhase.ACQUIRING)
        
        try:
            from ingest.pdf_downloader import PDFDownloader
            
            downloader = PDFDownloader(
                database=self.db,
                email=self.email,
                output_dir=self.pdf_dir
            )
            
            result = downloader.download_all(limit=limit)
            
            stats.items_processed = result.get('attempted', 0)
            stats.items_succeeded = result.get('downloaded', 0)
            stats.items_failed = result.get('not_available', 0)
            stats.details = result
            
            self.current_run.total_pdfs_acquired += stats.items_succeeded
            
        except Exception as e:
            stats.details['error'] = str(e)
            logger.error(f"PDF acquisition failed: {e}")
        
        self._end_phase(stats)
    
    def _run_job_creation_phase(self):
        """Create Article Eater job bundles."""
        stats = self._start_phase(DiscoveryPhase.BUILDING_JOBS)
        
        try:
            from eater_interface.handoff_contract import BatchBundleBuilder

            builder = BatchBundleBuilder(self.job_dir)
            
            # Get papers ready for AE
            papers = self.db.get_papers_by_status('send_to_eater', limit=100)
            papers_with_pdf = [p for p in papers if p.get('pdf_path')]
            
            stats.items_processed = len(papers_with_pdf)
            
            for paper in papers_with_pdf:
                try:
                    bundle_path = builder.add_paper(paper, Path(paper['pdf_path']))
                    if bundle_path:
                        stats.items_succeeded += 1
                        self.current_run.total_jobs_created += 1
                except Exception as e:
                    stats.items_failed += 1
                    logger.warning(f"Failed to create bundle: {e}")
            
        except Exception as e:
            stats.details['error'] = str(e)
            logger.error(f"Job creation failed: {e}")
        
        self._end_phase(stats)

    # =========================================================================
    # v3.2.5: AE-Driven Search Phases
    # =========================================================================

    def _run_ae_feedback_phase(self):
        """Process Article Eater outputs to identify new gaps."""
        stats = self._start_phase(DiscoveryPhase.AE_FEEDBACK)

        try:
            from search.ae_feedback import AEFeedbackLoop

            if self._ae_feedback is None:
                self._ae_feedback = AEFeedbackLoop(
                    database=self.db,
                    output_dir=Path('data/ae_outputs')
                )

            result = self._ae_feedback.process_all_outputs()

            stats.items_processed = result.get('bundles_found', 0)
            stats.items_succeeded = result.get('bundles_processed', 0)
            stats.details = {
                'claims_ingested': result.get('claims_ingested', 0),
                'rules_ingested': result.get('rules_ingested', 0),
                'followup_queries': result.get('followup_queries', 0)
            }

        except ImportError as e:
            logger.warning(f"AE feedback module not available: {e}")
            stats.details['error'] = str(e)
        except Exception as e:
            stats.items_failed += 1
            stats.details['error'] = str(e)
            logger.error(f"AE feedback processing failed: {e}")

        self._end_phase(stats)

    def _run_gap_analysis_phase(self):
        """Analyze knowledge gaps in taxonomy coverage."""
        stats = self._start_phase(DiscoveryPhase.GAP_ANALYSIS)

        try:
            from search.gap_analyzer import GapAnalyzer

            if self._gap_analyzer is None:
                self._gap_analyzer = GapAnalyzer(database=self.db)

            # Get coverage summary
            summary = self._gap_analyzer.get_coverage_summary()
            stats.details['coverage_summary'] = summary

            # Get all gaps
            gaps = self._gap_analyzer.get_all_gaps(limit=100)
            stats.items_processed = len(gaps)

            # Count gaps by type
            gap_types = {}
            for gap in gaps:
                gap_type = gap.gap_type.value
                gap_types[gap_type] = gap_types.get(gap_type, 0) + 1

            stats.details['gaps_by_type'] = gap_types
            stats.details['total_gaps'] = len(gaps)
            stats.items_succeeded = len(gaps)

            # Generate priority queries
            priority_queries = self._gap_analyzer.get_priority_queries(limit=50)
            stats.details['priority_queries'] = len(priority_queries)

        except ImportError as e:
            logger.warning(f"Gap analyzer module not available: {e}")
            stats.details['error'] = str(e)
        except Exception as e:
            stats.items_failed += 1
            stats.details['error'] = str(e)
            logger.error(f"Gap analysis failed: {e}")

        self._end_phase(stats)

    def _run_targeted_search_phase(self, limit_per_cell: int = 30):
        """Run targeted search for theories, neural outcomes, and mechanisms."""
        stats = self._start_phase(DiscoveryPhase.TARGETED_SEARCH)

        try:
            from search.bibliographer import Bibliographer

            if self._bibliographer is None:
                self._bibliographer = Bibliographer(
                    database=self.db,
                    email=self.email,
                    relevance_threshold=self.threshold
                )

            # Initialize all cell types (including theory, neural, mechanism)
            self._bibliographer.initialize_all_cells()

            # If we have gaps, also initialize gap-driven cells
            if self._gap_analyzer:
                self._bibliographer.initialize_from_gaps(self._gap_analyzer)

            # If we have AE feedback, add follow-up cells
            if self._ae_feedback:
                self._ae_feedback.feed_to_bibliographer(self._bibliographer, limit=20)

            # Count cells by type
            cell_counts = {}
            for cell in self._bibliographer.state.cells.values():
                cell_type = cell.cell_type
                cell_counts[cell_type] = cell_counts.get(cell_type, 0) + 1

            stats.details['cells_by_type'] = cell_counts
            stats.details['total_cells'] = len(self._bibliographer.state.cells)

            # Run targeted searches for theory cells
            theory_result = self._bibliographer.run(
                cell_type_filter='theory',
                limit_per_api=limit_per_cell,
                skip_complete=True
            )
            stats.details['theory_search'] = theory_result

            # Run targeted searches for neural cells
            neural_result = self._bibliographer.run(
                cell_type_filter='neural',
                limit_per_api=limit_per_cell,
                skip_complete=True
            )
            stats.details['neural_search'] = neural_result

            # Run targeted searches for mechanism cells
            mechanism_result = self._bibliographer.run(
                cell_type_filter='mechanism',
                limit_per_api=limit_per_cell,
                skip_complete=True
            )
            stats.details['mechanism_search'] = mechanism_result

            # Aggregate stats
            total_found = (
                theory_result.get('papers_found', 0) +
                neural_result.get('papers_found', 0) +
                mechanism_result.get('papers_found', 0)
            )
            total_imported = (
                theory_result.get('papers_imported', 0) +
                neural_result.get('papers_imported', 0) +
                mechanism_result.get('papers_imported', 0)
            )

            stats.items_processed = total_found
            stats.items_succeeded = total_imported
            stats.items_failed = total_found - total_imported

            self.current_run.total_papers_discovered += total_found
            self.current_run.total_papers_queued += total_imported

        except ImportError as e:
            logger.warning(f"Bibliographer module not available: {e}")
            stats.details['error'] = str(e)
        except Exception as e:
            stats.items_failed += 1
            stats.details['error'] = str(e)
            logger.error(f"Targeted search failed: {e}")

        self._end_phase(stats)

    def get_corpus_stats(self) -> Dict[str, Any]:
        """Get current corpus statistics."""
        return self.db.get_stats()
    
    def get_run_history(self, limit: int = 10) -> List[Dict]:
        """Get history of discovery runs."""
        # Would need to persist runs to DB - placeholder
        return []


def run_discovery_pipeline(
    database,
    email: str,
    import_file: Optional[Path] = None,
    **kwargs
) -> DiscoveryRun:
    """Convenience function to run discovery pipeline."""
    orchestrator = DiscoveryOrchestrator(database, email, **kwargs)
    return orchestrator.run_discovery(import_file=import_file, **kwargs)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run discovery pipeline')
    parser.add_argument('--import-file', type=Path, help='File to import')
    parser.add_argument('--email', required=True, help='Email for API access')
    parser.add_argument('--threshold', type=float, default=0.35, help='Relevance threshold')
    parser.add_argument('--iterations', type=int, default=3, help='Max expansion iterations')
    parser.add_argument('--expansion-limit', type=int, default=50, help='Papers per expansion')
    parser.add_argument('--pdf-limit', type=int, default=100, help='Max PDFs to download')
    # v3.2.5: New AE-driven search options
    parser.add_argument('--no-ae-feedback', action='store_true', help='Skip AE feedback processing')
    parser.add_argument('--no-gap-analysis', action='store_true', help='Skip gap analysis')
    parser.add_argument('--no-targeted-search', action='store_true', help='Skip targeted search')
    parser.add_argument('--targeted-limit', type=int, default=30, help='Papers per targeted cell')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    from core.database import Database
    from config.loader import get

    db = Database(Path(get('paths.database', 'data/article_finder.db')))

    def progress(phase, message, stats):
        print(f"[{phase}] {message}")

    orchestrator = DiscoveryOrchestrator(
        database=db,
        email=args.email,
        relevance_threshold=args.threshold,
        progress_callback=progress
    )

    run = orchestrator.run_discovery(
        import_file=args.import_file,
        expansion_limit=args.expansion_limit,
        pdf_limit=args.pdf_limit,
        max_iterations=args.iterations,
        run_ae_feedback=not args.no_ae_feedback,
        run_gap_analysis=not args.no_gap_analysis,
        run_targeted_search=not args.no_targeted_search,
        targeted_search_limit=args.targeted_limit
    )

    print("\n=== Discovery Run Complete ===")
    print(f"Status: {run.status}")
    print(f"Duration: {sum(p.duration_seconds for p in run.phases):.1f}s")
    print(f"Papers discovered: {run.total_papers_discovered}")
    print(f"Papers queued: {run.total_papers_queued}")
    print(f"PDFs acquired: {run.total_pdfs_acquired}")
    print(f"Jobs created: {run.total_jobs_created}")

    # v3.2.5: Show targeted search results
    for phase in run.phases:
        if phase.phase in ['ae_feedback', 'gap_analysis', 'targeted_search']:
            print(f"\n{phase.phase}:")
            for key, value in phase.details.items():
                print(f"  {key}: {value}")
