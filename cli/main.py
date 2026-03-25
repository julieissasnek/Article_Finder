#!/usr/bin/env python3
# Version: 3.2.2
"""
Article Finder v3.2 - Command Line Interface
Comprehensive CLI for all Article Finder operations.
"""

import argparse
import os
import sys
import json
import logging
import socket
import shutil
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from config.loader import get, load_config


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )


def get_db() -> Database:
    """Get database instance."""
    db_path = Path(get('paths.database', 'data/article_finder.db'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Database(db_path)


def build_pipeline():
    """Create an ArticleFinderPipeline using config settings."""
    from eater_interface.pipeline import ArticleFinderPipeline, PipelineConfig

    base_dir = Path(__file__).parent.parent
    db_path = Path(get('paths.database', 'data/article_finder.db'))

    config = PipelineConfig(
        data_dir=db_path.parent,
        taxonomy_path=base_dir / 'config' / 'taxonomy.yaml',
        job_bundles_dir=Path(get('paths.job_bundles', 'data/job_bundles')),
        eater_outputs_dir=Path(get('paths.ae_outputs', 'data/ae_outputs')),
        pdf_storage_dir=Path(get('paths.pdfs', 'data/pdfs'))
    )

    config.eater_executable = get('article_eater.executable', 'article_eater')
    config.eater_profile = get('article_eater.default_profile', 'standard')
    config.eater_hitl = get('article_eater.default_hitl', 'auto')
    config.eater_timeout = int(get('article_eater.timeout_seconds', 600))
    config.max_parallel_workers = int(get('article_eater.max_parallel', 1))

    return ArticleFinderPipeline(config)


# ============================================================================
# IMPORT COMMANDS
# ============================================================================

def cmd_import(args):
    """Import references from file."""
    from ingest.smart_importer import SmartImporter
    from ingest.citation_parser import CitationParser
    from ingest.doi_resolver import DOIResolver
    
    db = get_db()
    filepath = Path(args.file)
    
    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return 1
    
    print(f"Importing from {filepath}...")
    
    # Initialize components
    citation_parser = CitationParser()
    doi_resolver = None
    
    if not args.no_resolve:
        email = args.email or get('apis.openalex.email')
        if email and '@' in email:
            doi_resolver = DOIResolver(email=email)
    
    importer = SmartImporter(
        database=db,
        doi_resolver=doi_resolver,
        citation_parser=citation_parser
    )
    
    # Preview first
    if args.preview:
        preview = importer.preview_file(filepath)
        print("\n=== File Preview ===")
        print(f"Columns: {preview['columns']}")
        print(f"Detected mapping: {preview['column_mapping']}")
        print(f"Sample rows: {len(preview['sample_rows'])}")
        
        if preview.get('suggestions'):
            print("\nSuggestions:")
            for sug in preview['suggestions']:
                print(f"  [{sug['type']}] {sug['message']}")
        return 0
    
    # Run import
    def progress(current, total):
        if current % 50 == 0 or current == total:
            print(f"  Progress: {current}/{total}")
    
    stats = importer.import_file(
        filepath,
        source_name=args.source or filepath.stem,
        resolve_dois=not args.no_resolve,
        search_crossref=not args.no_crossref,
        parse_citations=True,
        limit=args.limit,
        progress_callback=progress
    )
    
    print("\n=== Import Results ===")
    print(f"Total rows:      {stats['total_rows']}")
    print(f"Papers created:  {stats['papers_created']}")
    print(f"Papers updated:  {stats['papers_updated']}")
    print(f"DOIs found:      {stats['dois_found']}")
    print(f"DOIs resolved:   {stats.get('dois_resolved', 0)}")
    print(f"Citations parsed: {stats.get('citations_parsed', 0)}")
    print(f"Skipped:         {stats['skipped']}")
    print(f"Errors:          {len(stats['errors'])}")
    
    if stats['errors'] and args.verbose:
        print("\nFirst 5 errors:")
        for err in stats['errors'][:5]:
            print(f"  Row {err.get('row', '?')}: {err.get('error', 'Unknown')}")
    
    return 0


def cmd_import_pdfs(args):
    """Import papers from PDF directory."""
    from ingest.pdf_cataloger import PDFCataloger
    from ingest.doi_resolver import DOIResolver
    
    db = get_db()
    pdf_dir = Path(args.directory)
    
    if not pdf_dir.exists():
        print(f"Error: Directory not found: {pdf_dir}")
        return 1
    
    print(f"Scanning {pdf_dir} for PDFs...")
    
    # Initialize resolver if needed
    resolver = None
    if not args.no_resolve:
        email = args.email or get('apis.openalex.email')
        if email and '@' in email:
            resolver = DOIResolver(email=email)
    
    storage_dir = None
    if args.copy_to_storage:
        storage_dir = args.storage_dir or Path(get('paths.pdfs', 'data/pdfs'))

    cataloger = PDFCataloger(
        database=db,
        doi_resolver=resolver,
        pdf_storage_dir=storage_dir,
        copy_to_storage=args.copy_to_storage,
        extract_doi_from_text=not args.no_text_doi
    )
    
    stats = cataloger.catalog_directory(
        pdf_dir,
        source_name=args.source or 'pdf_import',
        resolve_dois=not args.no_resolve,
        search_crossref=not args.no_crossref,
        limit=args.limit
    )
    
    print("\n=== PDF Import Results ===")
    print(f"Total PDFs:       {stats['total_pdfs']}")
    print(f"Papers created:   {stats['created']}")
    print(f"Papers updated:   {stats['updated']}")
    print(f"CrossRef matches: {stats['matched_crossref']}")
    print(f"Copied to storage: {stats.get('copied', 0)}")
    print(f"Already present:  {stats.get('already_present', 0)}")
    print(f"Errors:           {len(stats['errors'])}")
    
    return 0


def cmd_inbox(args):
    """Process PDFs from inbox folder."""
    from ingest.pdf_watcher import PDFWatcherService
    from ingest.doi_resolver import DOIResolver

    db = get_db()
    inbox_dir = args.directory or Path(get('paths.inbox_pdfs', 'data/inbox_pdfs'))
    storage_dir = args.storage_dir or Path(get('paths.pdfs', 'data/pdfs'))

    archive_dir = None
    if not args.no_archive:
        archive_dir = args.archive_dir or (Path(inbox_dir) / "processed")

    resolver = None
    if not args.no_resolve:
        email = args.email or get('apis.openalex.email')
        if email and '@' in email:
            resolver = DOIResolver(email=email)

    service = PDFWatcherService(
        watch_dir=Path(inbox_dir),
        database=db,
        resolver=resolver,
        storage_dir=storage_dir,
        archive_dir=archive_dir,
        source_name=args.source or "pdf_inbox",
        copy_to_storage=not args.no_copy,
        extract_doi_from_text=not args.no_text_doi,
        resolve_dois=not args.no_resolve,
        search_crossref=not args.no_crossref
    )

    if args.watch:
        service.watch(interval_seconds=args.interval)
        return 0

    stats = service.process_once(limit=args.limit)

    print("\n=== Inbox Processing Results ===")
    print(f"Source folder:     {stats.get('source_dir', '')}")
    print(f"Total PDFs:        {stats.get('total_pdfs', 0)}")
    print(f"Processed:         {stats.get('processed', 0)}")
    print(f"Papers created:    {stats.get('created', 0)}")
    print(f"Papers updated:    {stats.get('updated', 0)}")
    print(f"Copied to storage: {stats.get('copied', 0)}")
    print(f"Already present:   {stats.get('already_present', 0)}")
    print(f"Archived:          {stats.get('archived', 0)}")
    print(f"Archive failures:  {stats.get('archive_failures', 0)}")
    print(f"Errors:            {len(stats.get('errors', []))}")

    return 0


# ============================================================================
# ENRICHMENT COMMANDS
# ============================================================================

def cmd_enrich(args):
    """Enrich papers with metadata from APIs."""
    from ingest.enricher import BatchEnricher
    
    db = get_db()
    
    email = args.email or get('apis.openalex.email')
    if not email or '@' not in email:
        print("Error: Valid email required for API access")
        print("  Set in config/settings.local.yaml or use --email")
        return 1
    
    enricher = BatchEnricher(db, email=email)

    papers = db.search_papers(limit=10000)
    doi_candidates = [p for p in papers if not p.get('abstract') and p.get('doi')]
    title_candidates = [p for p in papers if not p.get('abstract') and not p.get('doi') and p.get('title')]

    doi_limit = args.limit or len(doi_candidates)
    title_limit = args.limit or len(title_candidates)

    print(f"Enriching DOI-backed papers: {min(len(doi_candidates), doi_limit)}")
    doi_stats = enricher.enrich_all(filter_missing='abstract', limit=doi_limit)

    print(f"\nRepairing title-only papers: {min(len(title_candidates), title_limit)}")
    title_stats = enricher.enrich_by_title_search(title_candidates, limit=title_limit)

    print(f"\n=== Enrichment Complete ===")
    print(f"DOI processed:       {doi_stats['processed']}")
    print(f"DOI enriched:        {doi_stats['abstracts_added']}")
    print(f"Title processed:     {title_stats['processed']}")
    print(f"Title matches:       {title_stats['found']}")
    print(f"Title enriched:      {title_stats['enriched']}")
    print(f"Total errors:        {doi_stats['errors'] + title_stats['errors']}")
    
    return 0


def cmd_abstracts(args):
    """Fetch abstracts for queued papers."""
    from ingest.abstract_fetcher import AbstractFetcher

    db = get_db()
    email = args.email or get('apis.openalex.email') or get('apis.crossref.email')
    if not email or '@' not in email:
        print("Error: Valid email required for API access")
        print("  Set in config/settings.local.yaml or use --email")
        return 1

    fetcher = AbstractFetcher(db, email=email)
    if args.retry_not_found:
        reset = fetcher.reset_queue(status='not_found')
        print(f'Reset {reset} queue items to pending')
    stats = fetcher.fetch_from_queue(limit=args.limit or 50)

    print("\n=== Abstract Fetch Results ===")
    print(f"Processed:        {stats['processed']}")
    print(f"Matched:          {stats['matched']}")
    print(f"Abstracts added:  {stats['abstracts_added']}")
    print(f"Not found:        {stats['not_found']}")
    print(f"Errors:           {stats['errors']}")

    return 0


# ============================================================================
# CLASSIFICATION COMMANDS
# ============================================================================

def cmd_classify(args):
    """Run taxonomy classification."""
    db = get_db()
    
    if args.load_taxonomy:
        from triage.taxonomy_loader import TaxonomyLoader
        
        print("Loading taxonomy...")
        loader = TaxonomyLoader(db)
        loader.load_from_yaml()
        print(f"  Loaded {loader.stats['facets']} facets, {loader.stats['nodes']} nodes")
    
    if args.build_centroids:
        from triage.taxonomy_loader import CentroidBuilder
        from triage.embeddings import get_embedding_service
        
        print("Building centroids...")
        embeddings = get_embedding_service()
        builder = CentroidBuilder(db, embeddings)
        builder.build_all_centroids()
        print("  Centroids built")
    
    if args.score_all:
        from triage.scorer import HierarchicalScorer
        
        print("Scoring papers...")
        scorer = HierarchicalScorer(db)
        
        papers = db.search_papers(limit=10000)
        unscored = [p for p in papers if not p.get('triage_score')]
        
        print(f"  {len(unscored)} papers to score")
        
        for i, paper in enumerate(unscored):
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(unscored)}")
            
            try:
                scorer.score_and_store(paper)
            except Exception as e:
                if args.verbose:
                    print(f"  Error scoring {paper.get('paper_id', '?')}: {e}")
        
        print("  Scoring complete")
    
    if args.report:
        papers = db.search_papers(limit=10000)
        
        by_decision = {}
        for p in papers:
            decision = p.get('triage_decision', 'unscored')
            by_decision[decision] = by_decision.get(decision, 0) + 1
        
        print("\n=== Classification Report ===")
        for decision, count in sorted(by_decision.items()):
            print(f"  {decision}: {count}")
    
    return 0


# ============================================================================
# SEMANTIC SEARCH COMMANDS
# ============================================================================

def cmd_search(args):
    """Semantic search over papers."""
    from knowledge.semantic_search import SemanticSearch
    
    db = get_db()
    searcher = SemanticSearch(db)
    
    query = ' '.join(args.query)
    
    if not query:
        print("Error: Query required")
        return 1
    
    print(f"Searching for: \"{query}\"")
    print()
    
    results = searcher.search(
        query,
        limit=args.limit or 20,
        min_score=args.min_score or 0.0,
        year_min=args.year_min,
        year_max=args.year_max,
        require_abstract=args.require_abstract
    )
    
    if not results:
        print("No results found")
        return 0
    
    print(f"=== {len(results)} Results ===\n")
    
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r.score:.3f}] {r.title[:70]}")
        if r.year:
            print(f"   Year: {r.year}", end="")
        if r.doi:
            print(f"  DOI: {r.doi}", end="")
        print()
        if args.verbose and r.abstract:
            print(f"   {r.abstract[:150]}...")
        print()
    
    return 0


def cmd_similar(args):
    """Find papers similar to a given paper."""
    from knowledge.semantic_search import SemanticSearch
    
    db = get_db()
    
    # Find the source paper
    paper = db.get_paper(args.paper_id)
    if not paper:
        # Try by DOI
        paper = db.get_paper_by_doi(args.paper_id)
    
    if not paper:
        print(f"Paper not found: {args.paper_id}")
        return 1
    
    print(f"Finding papers similar to:")
    print(f"  {paper.get('title', 'Untitled')}")
    print()
    
    searcher = SemanticSearch(db)
    results = searcher.find_similar(paper['paper_id'], limit=args.limit or 10)
    
    if not results:
        print("No similar papers found")
        return 0
    
    print(f"=== {len(results)} Similar Papers ===\n")
    
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r.score:.3f}] {r.title[:70]}")
        if r.year:
            print(f"   Year: {r.year}")
        print()
    
    return 0


def cmd_claims(args):
    """Search and analyze claims."""
    from knowledge.claim_embeddings import ClaimEmbeddings
    
    db = get_db()
    ce = ClaimEmbeddings(db)
    
    if args.action == 'search':
        query = ' '.join(args.query) if args.query else ''
        if not query:
            print("Error: Query required for search")
            return 1
        
        print(f"Searching claims for: \"{query}\"")
        print()
        
        results = ce.search(query, limit=args.limit)
        
        if not results:
            print("No matching claims found")
            return 0
        
        print(f"=== {len(results)} Matching Claims ===\n")
        
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r.score:.3f}] {r.statement[:80]}")
            print(f"   Type: {r.claim_type or 'unknown'} | Paper: {r.paper_title[:40] if r.paper_title else 'Unknown'}...")
            print()
        
        return 0
    
    elif args.action == 'duplicates':
        print(f"Finding duplicate claims (threshold: {args.threshold})...")
        print()
        
        duplicates = ce.find_duplicates(threshold=args.threshold)
        
        if not duplicates:
            print("No duplicate claims found")
            return 0
        
        print(f"=== {len(duplicates)} Potential Duplicates ===\n")
        
        for i, d in enumerate(duplicates[:args.limit], 1):
            print(f"{i}. [{d.similarity:.3f}] {d.relationship.upper()}")
            print(f"   Paper 1: {d.paper_id_1[:30]}")
            print(f"   Claim:   {d.statement_1[:70]}...")
            print(f"   Paper 2: {d.paper_id_2[:30]}")
            print(f"   Claim:   {d.statement_2[:70]}...")
            print()
        
        return 0
    
    elif args.action == 'stats':
        stats = ce.get_stats()
        
        print("=== Claim Statistics ===")
        print(f"Total claims indexed: {stats['claims_indexed']}")
        print(f"Embedding dimension:  {stats['embedding_dimension']}")
        print()
        print("By type:")
        for claim_type, count in stats['by_type'].items():
            print(f"  {claim_type}: {count}")
        
        return 0
    
    return 1


def cmd_graph(args):
    """Build and query knowledge graph."""
    from knowledge.claim_graph import ClaimGraph, NodeType
    
    db = get_db()
    graph = ClaimGraph(db)
    
    if args.action == 'build':
        print("Building knowledge graph...")
        stats = graph.build(force_rebuild=args.rebuild)
        
        print("\n=== Knowledge Graph Built ===")
        print(f"Papers:     {stats.get('papers', 0)}")
        print(f"Claims:     {stats.get('claims', 0)}")
        print(f"Constructs: {stats.get('constructs', 0)}")
        print(f"Edges:      {stats.get('total_edges', 0)}")
        
        if 'edges_by_type' in stats:
            print("\nEdges by type:")
            for edge_type, count in stats['edges_by_type'].items():
                print(f"  {edge_type}: {count}")
        
        return 0
    
    elif args.action == 'stats':
        # Load existing graph
        try:
            graph.build(force_rebuild=False)
        except Exception as e:
            print(f"Error loading graph: {e}")
            print("Run 'graph build' first")
            return 1
        
        stats = graph.get_stats()
        
        print("=== Knowledge Graph Statistics ===")
        print(f"Total nodes: {stats['total_nodes']}")
        print(f"  Papers:     {stats['papers']}")
        print(f"  Claims:     {stats['claims']}")
        print(f"  Constructs: {stats['constructs']}")
        print(f"Total edges: {stats['total_edges']}")
        
        if stats.get('edges_by_type'):
            print("\nEdges by type:")
            for edge_type, count in stats['edges_by_type'].items():
                print(f"  {edge_type}: {count}")
        
        return 0
    
    elif args.action == 'what-affects':
        query = ' '.join(args.query) if args.query else ''
        if not query:
            print("Error: Construct ID or search term required")
            return 1
        
        graph.build(force_rebuild=False)
        
        # Find matching constructs
        matches = graph.find_construct(query)
        if not matches:
            print(f"No constructs found matching: {query}")
            return 0
        
        for construct in matches:
            print(f"\n=== What affects {construct.label}? ===")
            results = graph.what_affects(construct.node_id)
            
            if not results:
                print("  No affecting factors found")
                continue
            
            for iv_node, claims in results:
                print(f"\n  {iv_node.label} ({len(claims)} claims)")
                for claim in claims[:3]:  # Show first 3 claims
                    stmt = claim.properties.get('statement', '')[:60]
                    print(f"    - {stmt}...")
        
        return 0
    
    elif args.action == 'affects-what':
        query = ' '.join(args.query) if args.query else ''
        if not query:
            print("Error: Construct ID or search term required")
            return 1
        
        graph.build(force_rebuild=False)
        
        matches = graph.find_construct(query)
        if not matches:
            print(f"No constructs found matching: {query}")
            return 0
        
        for construct in matches:
            print(f"\n=== What does {construct.label} affect? ===")
            results = graph.what_does_affect(construct.node_id)
            
            if not results:
                print("  No outcomes found")
                continue
            
            for dv_node, claims in results:
                print(f"\n  {dv_node.label} ({len(claims)} claims)")
                for claim in claims[:3]:
                    stmt = claim.properties.get('statement', '')[:60]
                    print(f"    - {stmt}...")
        
        return 0
    
    elif args.action == 'paper-claims':
        paper_id = ' '.join(args.query) if args.query else ''
        if not paper_id:
            print("Error: Paper ID required")
            return 1
        
        graph.build(force_rebuild=False)
        
        claims = graph.get_paper_claims(paper_id)
        
        if not claims:
            print(f"No claims found for paper: {paper_id}")
            return 0
        
        print(f"=== {len(claims)} Claims from Paper ===\n")
        
        for i, claim in enumerate(claims, 1):
            print(f"{i}. [{claim.properties.get('claim_type', 'unknown')}]")
            print(f"   {claim.properties.get('statement', '')[:80]}...")
            print()
        
        return 0
    
    return 1


def cmd_query(args):
    """Natural language query over knowledge graph."""
    from knowledge.query_engine import QueryEngine
    
    db = get_db()
    engine = QueryEngine(db)
    
    question = ' '.join(args.question)
    
    print(f"Question: {question}")
    print()
    
    try:
        result = engine.query(question)
    except Exception as e:
        print(f"Error executing query: {e}")
        print("Make sure the knowledge graph is built: python cli/main.py graph build")
        return 1
    
    print(f"Query type: {result.query_type.value}")
    if result.construct:
        print(f"Construct:  {result.construct}")
    print()
    
    if result.summary:
        print(f"=== {result.summary} ===")
        print()
    
    if not result.results:
        print("No results found")
        return 0
    
    # Format results based on query type
    if result.query_type.value in ['what_affects', 'affects_what']:
        for r in result.results[:10]:
            factor = r.get('factor') or r.get('outcome')
            count = r.get('claim_count', 0)
            avg_effect = r.get('avg_effect')
            
            effect_str = f" (avg effect: {avg_effect:.2f})" if avg_effect else ""
            print(f"• {factor}: {count} claims{effect_str}")
            
            if args.verbose and r.get('claims'):
                for claim in r['claims'][:2]:
                    print(f"    - {claim.get('claim', '')[:60]}...")
        
    elif result.query_type.value == 'claims_about':
        for i, claim in enumerate(result.results[:15], 1):
            stmt = claim.get('statement', '')[:70]
            ctype = claim.get('claim_type', 'unknown')
            print(f"{i}. [{ctype}] {stmt}...")
        
    elif result.query_type.value == 'contradictions':
        for i, c in enumerate(result.results[:10], 1):
            print(f"{i}. {c.get('type', 'conflict')}")
            c1 = c.get('claim_1', {})
            c2 = c.get('claim_2', {})
            print(f"   A: {c1.get('statement', '')[:50]}...")
            print(f"   B: {c2.get('statement', '')[:50]}...")
            print()
    
    elif result.query_type.value == 'papers_about':
        for r in result.results[:15]:
            year = r.get('year', '?')
            title = r.get('title', 'Untitled')[:60]
            score = r.get('relevance', 0)
            print(f"• [{score:.2f}] ({year}) {title}")
    
    elif result.query_type.value == 'general_search':
        data = result.results[0] if result.results else {}
        
        if data.get('papers'):
            print("Papers:")
            for p in data['papers'][:5]:
                print(f"  • [{p.get('score', 0):.2f}] {p.get('title', '')[:50]}")
        
        if data.get('claims'):
            print("\nClaims:")
            for c in data['claims'][:5]:
                print(f"  • [{c.get('score', 0):.2f}] {c.get('statement', '')[:50]}...")
    
    else:
        # Default: print as JSON-ish
        for r in result.results[:10]:
            print(f"• {r}")
    
    return 0


def cmd_synthesize(args):
    """Meta-analytic synthesis of claims."""
    from knowledge.synthesis import ClaimSynthesizer
    
    db = get_db()
    synthesizer = ClaimSynthesizer(db)
    
    # Check for IV->DV synthesis
    if args.iv and args.dv:
        print(f"Synthesizing: {args.iv} → {args.dv}")
        print()
        
        result = synthesizer.synthesize_by_iv_dv(args.iv, args.dv)
    else:
        construct = ' '.join(args.construct)
        print(f"Synthesizing: {construct}")
        print()
        
        result = synthesizer.synthesize(construct)
    
    # Print summary
    print(synthesizer.get_summary_text(result))
    
    # Forest plot data
    if args.forest_plot:
        print("\n=== Forest Plot Data ===")
        fp_data = synthesizer.generate_forest_plot_data(result)
        
        for study in fp_data.get('studies', []):
            effect = study.get('effect', 0)
            direction = study.get('direction', '?')
            print(f"  {study['label']}: {effect:.2f} ({direction})")
        
        if fp_data.get('pooled'):
            pooled = fp_data['pooled']
            print(f"\n  Pooled: {pooled['effect']:.2f} [{pooled['ci_lower']:.2f}, {pooled['ci_upper']:.2f}]")
    
    return 0


# ============================================================================
# CITATION COMMANDS
# ============================================================================

def cmd_citations(args):
    """Manage citation network."""
    db = get_db()
    
    if args.fetch:
        from search.citation_network import CitationFetcher
        
        email = args.email or get('apis.openalex.email')
        if not email or '@' not in email:
            print("Error: Valid email required")
            return 1
        
        print("Fetching citations...")
        fetcher = CitationFetcher(db, email=email)
        
        papers = db.search_papers(limit=10000)
        with_doi = [p for p in papers if p.get('doi')][:args.limit or 100]
        
        fetched = 0
        for i, paper in enumerate(with_doi):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(with_doi)}")
            
            try:
                result = fetcher.fetch_citations_for_paper(paper['paper_id'])
                if result.get('references_found', 0) > 0:
                    fetched += 1
            except Exception as e:
                if args.verbose:
                    print(f"  Error: {e}")
        
        print(f"  Fetched citations for {fetched} papers")
    
    if args.show_queue:
        queue = db.get_expansion_queue(limit=args.limit or 20)
        
        print("\n=== Expansion Queue ===")
        for item in queue:
            print(f"  {item.get('doi', 'no-doi')} - {item.get('title', 'Unknown')[:50]}")
    
    return 0


# ============================================================================
# EXPANSION COMMANDS
# ============================================================================

def cmd_expand(args):
    """Expand corpus via citations with taxonomy filtering."""
    from search.bounded_expander import BoundedExpander
    
    db = get_db()
    
    email = args.email or get('apis.openalex.email')
    if not email or '@' not in email:
        print("Error: Valid email required for API access")
        print("  Set in config/settings.local.yaml or use --email")
        return 1
    
    print(f"=== Bounded Corpus Expansion ===")
    print(f"Relevance threshold: {args.threshold}")
    print(f"Max depth:           {args.depth}")
    print(f"Papers to process:   {args.limit}")
    print()
    
    expander = BoundedExpander(
        database=db,
        email=email,
        relevance_threshold=args.threshold,
        max_depth=args.depth
    )
    
    def progress(current, total, stats):
        print(f"  [{current}/{total}] Queued: {stats.queued}, Rejected: {stats.rejected}")
    
    if args.iterate:
        print("Running iterative expansion...")
        all_stats = expander.expand_iteratively(
            max_iterations=args.iterations,
            papers_per_iteration=args.limit,
            min_queue_growth=args.min_growth,
            progress_callback=lambda i, s: print(f"  Iteration {i}: {s.queued} queued")
        )
        
        # Aggregate
        total_queued = sum(s.queued for s in all_stats)
        total_rejected = sum(s.rejected for s in all_stats)
        
        print(f"\n=== Iterative Expansion Complete ===")
        print(f"Iterations:     {len(all_stats)}")
        print(f"Total queued:   {total_queued}")
        print(f"Total rejected: {total_rejected}")
    else:
        stats = expander.expand_corpus(
            limit=args.limit,
            papers_with_status=args.status,
            progress_callback=progress
        )
        
        print(f"\n=== Expansion Results ===")
        print(f"Papers processed:   {stats.papers_processed}")
        print(f"Citations found:    {stats.citations_discovered}")
        print(f"References found:   {stats.references_discovered}")
        print(f"Scored:             {stats.scored}")
        print(f"Queued:             {stats.queued}")
        print(f"Rejected:           {stats.rejected}")
        print(f"Duplicates:         {stats.duplicates_skipped}")
        
        if stats.scored > 0:
            print(f"Acceptance rate:    {stats.queued/stats.scored*100:.1f}%")
        
        if stats.rejected_reasons:
            print(f"\nRejection breakdown:")
            for reason, count in sorted(stats.rejected_reasons.items(), key=lambda x: -x[1]):
                print(f"  {reason}: {count}")
    
    # Show queue status
    queue = db.get_expansion_queue(limit=10)
    print(f"\n=== Top of Queue ({len(queue)} shown) ===")
    for item in queue[:5]:
        score = item.get('relevance_score', 0)
        title = item.get('title', 'Unknown')[:45]
        print(f"  [{score:.2f}] {title}")
    
    return 0


def cmd_match_pdfs(args):
    """Match PDFs to existing paper records."""
    from search.deduplicator import PDFMatcher
    
    db = get_db()
    pdf_dir = Path(args.directory)
    
    if not pdf_dir.exists():
        print(f"Error: Directory not found: {pdf_dir}")
        return 1
    
    pdfs = list(pdf_dir.glob('*.pdf'))
    print(f"Found {len(pdfs)} PDFs in {pdf_dir}")
    
    if not pdfs:
        print("No PDFs to match")
        return 0
    
    matcher = PDFMatcher(db)
    
    print("\nMatching PDFs to paper records...")
    stats = matcher.match_directory(pdf_dir, update_records=not args.dry_run)
    
    print(f"\n=== Matching Results ===")
    print(f"Total PDFs:    {stats['total']}")
    print(f"Matched:       {stats['matched']}")
    print(f"Unmatched:     {stats['unmatched']}")
    
    if stats['matched'] > 0:
        match_rate = stats['matched'] / stats['total'] * 100
        print(f"Match rate:    {match_rate:.1f}%")
    
    if args.verbose and stats['matches']:
        print(f"\nMatched files:")
        for match in stats['matches'][:10]:
            print(f"  {match['pdf'][:40]} -> {match['paper_id'][:30]}")
        if len(stats['matches']) > 10:
            print(f"  ... and {len(stats['matches']) - 10} more")
    
    if args.verbose and stats['unmatched_files']:
        print(f"\nUnmatched files:")
        for fname in stats['unmatched_files'][:10]:
            print(f"  {fname}")
        if len(stats['unmatched_files']) > 10:
            print(f"  ... and {len(stats['unmatched_files']) - 10} more")
    
    if args.dry_run:
        print("\n(Dry run - no records updated)")
    
    return 0


def cmd_discover(args):
    """Run full discovery pipeline."""
    from search.discovery_orchestrator import DiscoveryOrchestrator
    
    db = get_db()
    
    email = args.email or get('apis.openalex.email')
    if not email or '@' not in email:
        print("Error: Valid email required for API access")
        return 1
    
    print("=== Discovery Pipeline ===")
    print(f"Relevance threshold: {args.threshold}")
    print(f"Max iterations:      {args.iterations}")
    print(f"Expansion limit:     {args.expansion_limit}")
    print(f"PDF limit:           {args.pdf_limit}")
    print()
    
    def progress_callback(phase, message, stats):
        print(f"[{phase}] {message}")
    
    orchestrator = DiscoveryOrchestrator(
        database=db,
        email=email,
        relevance_threshold=args.threshold,
        max_expansion_depth=args.depth,
        progress_callback=progress_callback
    )
    
    import_file = Path(args.import_file) if args.import_file else None
    
    try:
        run = orchestrator.run_discovery(
            import_file=import_file,
            expansion_limit=args.expansion_limit,
            pdf_limit=args.pdf_limit,
            max_iterations=args.iterations
        )
        
        print(f"\n=== Discovery Complete ===")
        print(f"Status:             {run.status}")
        print(f"Papers discovered:  {run.total_papers_discovered}")
        print(f"Papers queued:      {run.total_papers_queued}")
        print(f"PDFs acquired:      {run.total_pdfs_acquired}")
        print(f"Jobs created:       {run.total_jobs_created}")
        
        print(f"\nPhase timings:")
        for phase in run.phases:
            print(f"  {phase.phase}: {phase.duration_seconds:.1f}s "
                  f"({phase.items_succeeded}/{phase.items_processed} succeeded)")
        
        return 0
        
    except Exception as e:
        print(f"\nError: {e}")
        return 1


# ============================================================================
# BIBLIOGRAPHER COMMAND
# ============================================================================

def cmd_bibliographer(args):
    """Systematic taxonomy-driven literature discovery."""
    from search.bibliographer import Bibliographer
    
    db = get_db()
    email = args.email or get('apis.openalex.email', 'research@ucsd.edu')
    
    biblio = Bibliographer(
        database=db,
        email=email,
        relevance_threshold=args.threshold
    )
    
    if args.subcmd == 'init':
        biblio.initialize_cells(Path('./config/taxonomy.yaml'))
        print(f"Initialized {len(biblio.state.cells)} cells from taxonomy")
        
    elif args.subcmd == 'status':
        status = biblio.get_status()
        print("\n=== Bibliographer Status ===")
        print(f"Cells: {status['complete']}/{status['total_cells']} complete")
        print(f"  Pending: {status['pending']}")
        print(f"  Errors: {status['errors']}")
        print(f"\nBy priority:")
        for p, data in status['by_priority'].items():
            print(f"  {p}: {data['complete']}/{data['total']} cells, {data['papers_imported']} papers")
        print(f"\nTotals:")
        print(f"  Found: {status['total_papers_found']}")
        print(f"  Imported: {status['total_papers_imported']}")
        print(f"  Rejected: {status['total_papers_rejected']}")
        if status['last_run']:
            print(f"  Last run: {status['last_run']}")
        
    elif args.subcmd == 'run':
        if not biblio.state.cells:
            print("No cells initialized. Run 'bibliographer init' first.")
            return 1
        results = biblio.run(
            priority_filter=args.priority,
            cell_filter=args.cell,
            limit_per_api=args.limit
        )
        print(f"\n=== Run Complete ===")
        print(f"Cells processed: {results['cells_processed']}")
        print(f"Papers found: {results['papers_found']}")
        print(f"Papers imported: {results['papers_imported']}")
        
    elif args.subcmd == 'gaps':
        gaps = biblio.get_gaps(args.min_papers)
        print(f"\n=== Gaps (cells with < {args.min_papers} papers) ===")
        if not gaps:
            print("No gaps found!")
        else:
            for gap in gaps[:20]:  # Show top 20
                print(f"  {gap['factor']:20} × {gap['outcome']:20} = {gap['papers']} papers")
                
    elif args.subcmd == 'reset':
        if args.cell:
            biblio.reset_cell(args.cell)
            print(f"Reset cell: {args.cell}")
        else:
            print("Specify --cell to reset")
    
    return 0


# ============================================================================
# PDF DOWNLOAD COMMANDS
# ============================================================================

def cmd_download(args):
    """Download PDFs for papers."""
    from ingest.pdf_downloader import PDFDownloader
    
    db = get_db()
    
    email = args.email or get('apis.unpaywall.email', get('apis.openalex.email'))
    if not email or '@' not in email:
        print("Error: Valid email required for Unpaywall")
        return 1
    
    downloader = PDFDownloader(db, email=email)
    
    print("Downloading PDFs...")
    stats = downloader.download_all(limit=args.limit or 50)
    
    print(f"\n=== Download Results ===")
    print(f"Attempted: {stats.get('attempted', 0)}")
    print(f"Downloaded: {stats.get('downloaded', 0)}")
    print(f"Not available: {stats.get('not_available', 0)}")
    
    return 0


# ============================================================================
# ZOTERO INTEGRATION COMMANDS
# ============================================================================

def cmd_zotero(args):
    """Zotero integration for PDF acquisition."""
    from ingest.zotero_bridge import ZoteroLocalReader, ZoteroImporter, ZoteroExporter
    
    db = get_db()
    
    if args.action == 'stats':
        # Show Zotero library statistics
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
            
            # Also show Article Finder PDF status
            exporter = ZoteroExporter(db)
            af_status = exporter.get_pdf_acquisition_status()
            
            print(f"\n=== Article Finder PDF Status ===")
            print(f"Total papers: {af_status['total_papers']}")
            print(f"With PDF: {af_status['with_pdf']} ({af_status['pdf_coverage_pct']:.1f}%)")
            print(f"Need PDF: {af_status['without_pdf']}")
            print(f"  (with DOI, acquirable): {af_status['acquirable_via_doi']}")
            
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print("\nZotero data directory not found.")
            print("Specify with --zotero-dir or ensure Zotero is installed.")
            return 1
        
        return 0
    
    elif args.action == 'import':
        # Import PDFs from Zotero
        try:
            pdf_dir = args.pdf_dir or Path(get('paths.pdfs', 'data/pdfs'))
            importer = ZoteroImporter(
                database=db,
                zotero_dir=args.zotero_dir,
                pdf_output_dir=pdf_dir
            )
            
            print(f"Scanning Zotero library at {importer.reader.zotero_dir}...")
            
            stats = importer.import_all(dry_run=args.dry_run)
            
            print("\n=== Import Results ===")
            print(f"Zotero items found: {stats.zotero_items_found}")
            print(f"Zotero items with PDFs: {stats.zotero_pdfs_found}")
            print(f"Matched to Article Finder: {stats.matched_to_af_papers}")
            print(f"PDFs copied: {stats.pdfs_copied}")
            print(f"Already present: {stats.pdfs_already_present}")
            print(f"No match found: {stats.match_failures}")
            
            if args.dry_run:
                print("\n(Dry run - no files copied)")
            
            if stats.errors:
                print(f"\nErrors ({len(stats.errors)}):")
                for err in stats.errors[:5]:
                    print(f"  {err}")
                    
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return 1
        
        return 0
    
    elif args.action == 'export':
        # Export papers needing PDFs to Zotero format
        exporter = ZoteroExporter(db)
        
        output_path = args.output or Path(f"papers_needing_pdfs.{args.format}")
        
        count = exporter.export_papers_needing_pdfs(
            output_path,
            format=args.format,
            limit=args.limit
        )
        
        print(f"Exported {count} papers to {output_path}")
        print(f"\nFormat: {args.format.upper()}")
        
        status = exporter.get_pdf_acquisition_status()
        print(f"\nPDF Status: {status['with_pdf']}/{status['total_papers']} papers have PDFs ({status['pdf_coverage_pct']:.1f}%)")
        
        print(f"\n=== Next Steps ===")
        print(f"1. Open Zotero")
        print(f"2. File → Import... → Select {output_path}")
        print(f"3. Select all imported items")
        print(f"4. Right-click → Find Available PDF")
        print(f"5. Once Zotero downloads PDFs, run:")
        print(f"   python cli/main.py zotero import")
        
        return 0
    
    return 1


# ============================================================================
# JOB BUNDLE COMMANDS
# ============================================================================

def cmd_build_jobs(args):
    """Create Article Eater job bundles."""
    from eater_interface.job_bundle_v2 import JobBundleBuilder
    
    db = get_db()
    
    output_dir = Path(args.output or get('paths.job_bundles', 'data/job_bundles'))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get papers by status
    status = args.status or 'send_to_eater'
    papers = db.get_papers_by_status(status, limit=args.limit or 100)
    
    print(f"Building job bundles for {len(papers)} papers (status={status})...")
    
    builder = JobBundleBuilder(output_dir)
    built = 0
    
    for paper in papers:
        pdf_path = paper.get('pdf_path')
        if not pdf_path or not Path(pdf_path).exists():
            if args.verbose:
                print(f"  Skipping {paper['paper_id']}: no PDF")
            continue
        
        try:
            bundle_path = builder.build_bundle(paper, Path(pdf_path))
            built += 1
            if args.verbose:
                print(f"  Built: {bundle_path}")
        except Exception as e:
            print(f"  Error building bundle for {paper['paper_id']}: {e}")
    
    print(f"\n=== Built {built} job bundles ===")
    print(f"Output: {output_dir}")
    
    return 0

def cmd_eater_batch(args):
    """Run Article Eater in a time- or count-limited batch loop."""
    pipeline = build_pipeline()

    # Force local LLM for batch runs unless user overrides env explicitly.
    os.environ.setdefault("AE_LLM_MODEL", "ollama:mistral")
    os.environ.setdefault("OLLAMA_BASE", "http://localhost:11434")

    hours = args.hours or 0
    minutes = args.minutes or 0
    time_budget_seconds = int(hours * 3600 + minutes * 60) if (hours or minutes) else None
    if time_budget_seconds == 0:
        time_budget_seconds = None

    def progress(info):
        remaining = info.get('remaining_seconds')
        remaining_str = f"{int(remaining)}s" if remaining is not None else "n/a"
        state = info.get('state', "running")
        print(
            f"State: {state} | "
            f"Processed: {info.get('processed', 0)} | "
            f"Elapsed: {int(info.get('elapsed_seconds', 0))}s | "
            f"Remaining: {remaining_str}"
        )

    result = pipeline.run_eater_batch(
        status_filter=args.status,
        max_papers=args.max_papers,
        time_budget_seconds=time_budget_seconds,
        profile=args.profile,
        progress_callback=progress,
        continuous=args.continuous,
        idle_sleep_seconds=args.idle_sleep
    )

    print("\n=== Article Eater Batch Complete ===")
    print(f"Processed: {result.get('processed', 0)}")
    print(f"Elapsed:   {int(result.get('elapsed_seconds', 0))}s")
    return 0


def cmd_stats(args):
    """Show corpus statistics."""
    db = get_db()
    
    stats = db.get_corpus_stats()
    papers = db.search_papers(limit=10000)
    
    print("\n=== Corpus Statistics ===")
    print(f"Total papers:     {len(papers)}")
    print(f"With DOI:         {sum(1 for p in papers if p.get('doi'))}")
    print(f"With abstract:    {sum(1 for p in papers if p.get('abstract'))}")
    print(f"With PDF:         {sum(1 for p in papers if p.get('pdf_path'))}")
    
    print("\n=== By Status ===")
    by_status = stats.get('papers_by_status', {})
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    
    print(f"\n=== Database ===")
    print(f"Claims: {stats.get('total_claims', 0)}")
    print(f"Rules:  {stats.get('total_rules', 0)}")
    print(f"Citations: {stats.get('total_citations', 0)}")
    print(f"Expansion queue: {stats.get('expansion_queue_pending', 0)}")
    
    return 0


# ============================================================================
# UI COMMAND
# ============================================================================
def _get_ports_contract() -> dict:
    ports_path = Path(__file__).parent.parent / 'contracts' / 'ports.json'
    if not ports_path.exists():
        return {}
    try:
        return json.loads(ports_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _get_ui_port_from_contract(default_port: int = 8501) -> int:
    data = _get_ports_contract()
    return int(data.get('ports', {}).get('ui', {}).get('host', default_port))


def _port_status(port: int) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return "free"
    except OSError:
        return "in use"
    finally:
        sock.close()


def cmd_doctor(args):
    print("== Doctor ==")
    load_config()

    settings_local = Path(__file__).parent.parent / "config" / "settings.local.yaml"
    if settings_local.exists():
        print("OK: settings.local.yaml present")
    else:
        print("WARN: settings.local.yaml missing (defaults only)")

    def _email_ok(key: str) -> bool:
        val = get(key, "")
        return bool(val) and val != "your-email@ucsd.edu"

    for key in ["apis.openalex.email", "apis.crossref.email", "apis.unpaywall.email"]:
        if _email_ok(key):
            print(f"OK: {key}")
        else:
            print(f"WARN: {key} not set")

    db_path = Path(get('paths.database', 'data/article_finder.db'))
    if db_path.parent.exists():
        print(f"OK: database dir {db_path.parent}")
    else:
        print(f"WARN: database dir missing {db_path.parent}")

    ports_path = Path(__file__).parent.parent / "contracts" / "ports.json"
    if ports_path.exists():
        ui_port = _get_ui_port_from_contract()
        print(f"OK: ports.json found (ui={ui_port}, { _port_status(ui_port) })")
    else:
        print("WARN: contracts/ports.json missing")

    job_bundles = Path(get("paths.job_bundles", "data/job_bundles"))
    ae_outputs = Path(get("paths.ae_outputs", "data/ae_outputs"))
    for p, name in [(job_bundles, "job_bundles"), (ae_outputs, "ae_outputs")]:
        if p.exists():
            print(f"OK: {name} dir {p}")
        else:
            print(f"WARN: {name} dir missing {p}")

    ae_exec = get("article_eater.executable", "article_eater")
    if shutil.which(ae_exec):
        print(f"OK: article_eater executable '{ae_exec}'")
    else:
        print(f"WARN: article_eater executable '{ae_exec}' not found on PATH")

    return 0



def cmd_ui(args):
    """Launch Streamlit UI."""
    import subprocess
    
    ui_path = Path(__file__).parent.parent / 'ui' / 'app.py'
    
    if not ui_path.exists():
        print(f"Error: UI not found at {ui_path}")
        return 1
    
    port = _get_ui_port_from_contract()
    print("Launching Article Finder UI...")
    print(f"Open http://localhost:{port} in your browser")
    
    subprocess.run(['streamlit', 'run', str(ui_path), '--server.port', str(port)])
    return 0


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Article Finder v3.2 - Neuroarchitecture Literature Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from spreadsheet
  python cli/main.py import data/references.xlsx --source MyCorpus
  
  # Import PDFs
  python cli/main.py import-pdfs data/pdfs/ --source PDFs
  
  # Enrich with metadata
  python cli/main.py enrich --limit 100
  
  # Classify papers
  python cli/main.py classify --load-taxonomy --build-centroids --score-all
  
  # Fetch citations
  python cli/main.py citations --fetch --limit 50
  
  # Download PDFs
  python cli/main.py download --limit 50
  
  # Build job bundles for Article Eater
  python cli/main.py build-jobs --status send_to_eater
  
  # Launch UI
  python cli/main.py ui
"""
    )
    
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--email', help='Email for API access')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Import command
    p_import = subparsers.add_parser('import', help='Import references from file')
    p_import.add_argument('file', type=Path, help='File to import (CSV, Excel)')
    p_import.add_argument('--source', help='Source name for tracking')
    p_import.add_argument('--limit', type=int, help='Max rows to import')
    p_import.add_argument('--preview', action='store_true', help='Preview only')
    p_import.add_argument('--no-resolve', action='store_true', help='Skip DOI resolution')
    p_import.add_argument('--no-crossref', action='store_true', help='Skip CrossRef search')
    p_import.set_defaults(func=cmd_import)
    
    # Import PDFs command
    p_pdfs = subparsers.add_parser('import-pdfs', help='Import from PDF directory')
    p_pdfs.add_argument('directory', type=Path, help='Directory containing PDFs')
    p_pdfs.add_argument('--source', help='Source name')
    p_pdfs.add_argument('--limit', type=int, help='Max PDFs to process')
    p_pdfs.add_argument('--no-resolve', action='store_true', help='Skip DOI resolution')
    p_pdfs.add_argument('--no-crossref', action='store_true', help='Skip CrossRef search')
    p_pdfs.add_argument('--copy-to-storage', action='store_true',
                        help='Copy PDFs into storage directory')
    p_pdfs.add_argument('--storage-dir', type=Path,
                        help='PDF storage directory (default: paths.pdfs)')
    p_pdfs.add_argument('--no-text-doi', action='store_true',
                        help='Skip DOI extraction from PDF text')
    p_pdfs.set_defaults(func=cmd_import_pdfs)
    
    # Enrich command
    p_enrich = subparsers.add_parser('enrich', help='Enrich papers with metadata')
    p_enrich.add_argument('--limit', type=int, help='Max papers to enrich')
    p_enrich.set_defaults(func=cmd_enrich)
    
    # Abstracts command
    p_abstracts = subparsers.add_parser('abstracts', help='Fetch abstracts for queued papers')
    p_abstracts.add_argument('--limit', type=int, help='Max queue items to process')
    p_abstracts.add_argument('--retry-not-found', action='store_true', help='Retry items marked not_found')
    p_abstracts.set_defaults(func=cmd_abstracts)
    
    # Classify command
    p_classify = subparsers.add_parser('classify', help='Run classification')
    p_classify.add_argument('--load-taxonomy', action='store_true', help='Load taxonomy from YAML')
    p_classify.add_argument('--build-centroids', action='store_true', help='Build embedding centroids')
    p_classify.add_argument('--score-all', action='store_true', help='Score all papers')
    p_classify.add_argument('--report', action='store_true', help='Show classification report')
    p_classify.set_defaults(func=cmd_classify)
    
    # Semantic search command
    p_search = subparsers.add_parser('search', help='Semantic search over papers')
    p_search.add_argument('query', nargs='+', help='Search query')
    p_search.add_argument('--limit', type=int, default=20, help='Max results')
    p_search.add_argument('--min-score', type=float, default=0.0, help='Minimum similarity score')
    p_search.add_argument('--year-min', type=int, help='Minimum year')
    p_search.add_argument('--year-max', type=int, help='Maximum year')
    p_search.add_argument('--require-abstract', action='store_true', help='Only papers with abstracts')
    p_search.set_defaults(func=cmd_search)
    
    # Similar papers command
    p_similar = subparsers.add_parser('similar', help='Find papers similar to a given paper')
    p_similar.add_argument('paper_id', help='Paper ID or DOI')
    p_similar.add_argument('--limit', type=int, default=10, help='Max results')
    p_similar.set_defaults(func=cmd_similar)
    
    # Claim search command
    p_claims = subparsers.add_parser('claims', help='Search and analyze claims')
    p_claims.add_argument('action', choices=['search', 'duplicates', 'stats'], help='Action to perform')
    p_claims.add_argument('query', nargs='*', help='Search query (for search action)')
    p_claims.add_argument('--limit', type=int, default=20, help='Max results')
    p_claims.add_argument('--threshold', type=float, default=0.92, help='Similarity threshold for duplicates')
    p_claims.set_defaults(func=cmd_claims)
    
    # Knowledge graph command
    p_graph = subparsers.add_parser('graph', help='Build and query knowledge graph')
    p_graph.add_argument('action', choices=['build', 'stats', 'what-affects', 'affects-what', 'paper-claims'], 
                         help='Action to perform')
    p_graph.add_argument('query', nargs='*', help='Query argument (construct ID or paper ID)')
    p_graph.add_argument('--rebuild', action='store_true', help='Force rebuild graph from database')
    p_graph.set_defaults(func=cmd_graph)
    
    # Natural language query command
    p_query = subparsers.add_parser('query', help='Natural language query over knowledge graph')
    p_query.add_argument('question', nargs='+', help='Question to answer')
    p_query.add_argument('--verbose', '-v', action='store_true', help='Show detailed results')
    p_query.set_defaults(func=cmd_query)
    
    # Synthesis command
    p_synthesize = subparsers.add_parser('synthesize', help='Meta-analytic synthesis of claims')
    p_synthesize.add_argument('construct', nargs='+', help='Construct to synthesize')
    p_synthesize.add_argument('--iv', help='Independent variable (for IV->DV synthesis)')
    p_synthesize.add_argument('--dv', help='Dependent variable (for IV->DV synthesis)')
    p_synthesize.add_argument('--forest-plot', action='store_true', help='Generate forest plot data')
    p_synthesize.set_defaults(func=cmd_synthesize)
    
    # Citations command
    p_citations = subparsers.add_parser('citations', help='Manage citations')
    p_citations.add_argument('--fetch', action='store_true', help='Fetch citations from OpenAlex')
    p_citations.add_argument('--show-queue', action='store_true', help='Show expansion queue')
    p_citations.add_argument('--limit', type=int, help='Limit')
    p_citations.set_defaults(func=cmd_citations)
    
    # Expand command (bounded expansion)
    p_expand = subparsers.add_parser('expand', help='Expand corpus via citations with taxonomy filtering')
    p_expand.add_argument('--threshold', type=float, default=0.35, help='Relevance threshold (0-1)')
    p_expand.add_argument('--depth', type=int, default=2, help='Max citation depth')
    p_expand.add_argument('--limit', type=int, default=20, help='Papers to expand from')
    p_expand.add_argument('--status', default='send_to_eater', help='Expand from papers with this status')
    p_expand.add_argument('--iterate', action='store_true', help='Run iterative expansion')
    p_expand.add_argument('--iterations', type=int, default=3, help='Max iterations (with --iterate)')
    p_expand.add_argument('--min-growth', type=int, default=5, help='Stop if queue growth below this')
    p_expand.set_defaults(func=cmd_expand)
    
    # Match PDFs command
    p_match = subparsers.add_parser('match-pdfs', help='Match PDFs to existing paper records')
    p_match.add_argument('directory', type=Path, help='Directory containing PDFs')
    p_match.add_argument('--dry-run', action='store_true', help='Show matches without updating records')
    p_match.set_defaults(func=cmd_match_pdfs)

    # Inbox command
    p_inbox = subparsers.add_parser('inbox', help='Process PDFs from inbox folder')
    p_inbox.add_argument('--dir', dest='directory', type=Path,
                         help='Inbox folder (default: paths.inbox_pdfs)')
    p_inbox.add_argument('--source', help='Source name')
    p_inbox.add_argument('--limit', type=int, help='Max PDFs to process')
    p_inbox.add_argument('--no-resolve', action='store_true', help='Skip DOI resolution')
    p_inbox.add_argument('--no-crossref', action='store_true', help='Skip CrossRef search')
    p_inbox.add_argument('--no-text-doi', action='store_true', help='Skip DOI extraction from PDF text')
    p_inbox.add_argument('--no-copy', action='store_true',
                         help='Do not copy PDFs into storage directory')
    p_inbox.add_argument('--storage-dir', type=Path,
                         help='PDF storage directory (default: paths.pdfs)')
    p_inbox.add_argument('--archive-dir', type=Path,
                         help='Where to archive processed PDFs')
    p_inbox.add_argument('--no-archive', action='store_true',
                         help='Leave PDFs in inbox after processing')
    p_inbox.add_argument('--watch', action='store_true',
                         help='Continuously watch the inbox folder')
    p_inbox.add_argument('--interval', type=int, default=30,
                         help='Polling interval when --watch is set')
    p_inbox.set_defaults(func=cmd_inbox)
    
    # Discover command (full pipeline)
    p_discover = subparsers.add_parser('discover', help='Run full discovery pipeline')
    p_discover.add_argument('--import-file', type=Path, help='Optional file to import first')
    p_discover.add_argument('--threshold', type=float, default=0.35, help='Relevance threshold')
    p_discover.add_argument('--depth', type=int, default=2, help='Max citation depth')
    p_discover.add_argument('--iterations', type=int, default=3, help='Max expansion iterations')
    p_discover.add_argument('--expansion-limit', type=int, default=50, help='Papers per expansion')
    p_discover.add_argument('--pdf-limit', type=int, default=100, help='Max PDFs to download')
    p_discover.set_defaults(func=cmd_discover)
    
    # Download command
    p_download = subparsers.add_parser('download', help='Download PDFs')
    p_download.add_argument('--limit', type=int, help='Max PDFs to download')
    p_download.set_defaults(func=cmd_download)
    
    # Build jobs command
    p_jobs = subparsers.add_parser('build-jobs', help='Create Article Eater job bundles')
    p_jobs.add_argument('--status', help='Paper status to select (default: send_to_eater)')
    p_jobs.add_argument('--output', type=Path, help='Output directory')
    p_jobs.add_argument('--limit', type=int, help='Max bundles to create')
    p_jobs.set_defaults(func=cmd_build_jobs)

    # Article Eater batch command
    p_batch = subparsers.add_parser('eater-batch', help='Run Article Eater batch processing')
    p_batch.add_argument('--continuous', action='store_true', help='Keep polling and processing until stopped')
    p_batch.add_argument('--idle-sleep', type=int, default=30, help='Seconds to sleep between idle polls')
    p_batch.add_argument('--status', default='send_to_eater', help='Status/triage decision to bundle')
    p_batch.add_argument('--max-papers', type=int, help='Max papers to process')
    p_batch.add_argument('--hours', type=float, help='Time budget in hours')
    p_batch.add_argument('--minutes', type=float, help='Time budget in minutes')
    p_batch.add_argument('--profile', choices=['fast', 'standard', 'deep'], help='Override Article Eater profile')
    p_batch.set_defaults(func=cmd_eater_batch)

    
    # Zotero commands
    p_zotero = subparsers.add_parser('zotero', help='Zotero integration for PDF acquisition')
    p_zotero.add_argument('action', choices=['stats', 'import', 'export'], 
                          help='Action: stats, import (PDFs from Zotero), export (papers to Zotero)')
    p_zotero.add_argument('--zotero-dir', type=Path, help='Path to Zotero data directory (default: ~/Zotero)')
    p_zotero.add_argument('--pdf-dir', type=Path, help='Where to copy PDFs (default: paths.pdfs)')
    p_zotero.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    p_zotero.add_argument('--format', choices=['csv', 'ris'], default='ris', help='Export format (default: ris)')
    p_zotero.add_argument('--output', '-o', type=Path, help='Output file for export')
    p_zotero.add_argument('--limit', type=int, help='Limit number of items')
    p_zotero.set_defaults(func=cmd_zotero)
    
    # Bibliographer command
    p_bib = subparsers.add_parser('bibliographer', help='Systematic taxonomy-driven discovery')
    p_bib.add_argument('subcmd', choices=['init', 'status', 'run', 'gaps', 'reset'],
                       help='init=setup cells, status=show progress, run=search APIs, gaps=find holes')
    p_bib.add_argument('--priority', choices=['HIGH', 'MEDIUM', 'LOW'],
                       help='Only process cells with this priority')
    p_bib.add_argument('--cell', help='Process specific cell ID')
    p_bib.add_argument('--limit', type=int, default=50, help='Papers per API per cell')
    p_bib.add_argument('--threshold', type=float, default=0.35, help='Relevance threshold')
    p_bib.add_argument('--min-papers', type=int, default=5, help='Min papers for gaps command')
    p_bib.add_argument('--email', help='Email for API access')
    p_bib.set_defaults(func=cmd_bibliographer)
    
    # Stats command
    p_stats = subparsers.add_parser('stats', help='Show statistics')
    p_stats.set_defaults(func=cmd_stats)
    
    # Doctor command
    p_doctor = subparsers.add_parser('doctor', help='Check config, ports, and handoff paths')
    p_doctor.set_defaults(func=cmd_doctor)

    # UI command
    p_ui = subparsers.add_parser('ui', help='Launch Streamlit UI')
    p_ui.set_defaults(func=cmd_ui)
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
