# Version: 3.2.4
"""
Article Finder v3.2 - Import Page
Smart file import with preview, column mapping, and PDF support.
"""

import streamlit as st
from pathlib import Path
import tempfile
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

st.set_page_config(page_title="Import - Article Finder", layout="wide")


@st.cache_resource
def get_database():
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))


def render_preview_table(preview: dict):
    """Render a preview of the file contents."""
    import pandas as pd
    
    if not preview.get('sample_rows'):
        st.warning("No data rows found in file")
        return
    
    df = pd.DataFrame(preview['sample_rows'])
    
    # Highlight detected columns
    mapping = preview['column_mapping']
    detected = {}
    
    for field in ['doi', 'title', 'authors', 'year', 'venue', 'abstract', 'citation']:
        col = mapping.get(field)
        if col:
            detected[col] = field
    
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )
    
    return detected


def render_column_mapping(preview: dict) -> dict:
    """Render column mapping interface and return user-adjusted mapping."""
    mapping = preview['column_mapping']
    columns = preview['columns']
    
    st.subheader("Column Mapping")
    st.caption("Verify or adjust the detected column mappings")
    
    # Build options
    options = ["(not mapped)"] + columns
    
    # Create mapping UI
    col1, col2, col3, col4 = st.columns(4)
    
    adjusted = {}
    
    with col1:
        # DOI column
        doi_default = columns.index(mapping['doi']) + 1 if mapping.get('doi') in columns else 0
        doi_col = st.selectbox("DOI Column", options, index=doi_default, key="map_doi")
        if doi_col != "(not mapped)":
            adjusted['doi'] = doi_col
        
        # Year column
        year_default = columns.index(mapping['year']) + 1 if mapping.get('year') in columns else 0
        year_col = st.selectbox("Year Column", options, index=year_default, key="map_year")
        if year_col != "(not mapped)":
            adjusted['year'] = year_col
    
    with col2:
        # Title column
        title_default = columns.index(mapping['title']) + 1 if mapping.get('title') in columns else 0
        title_col = st.selectbox("Title Column", options, index=title_default, key="map_title")
        if title_col != "(not mapped)":
            adjusted['title'] = title_col
        
        # Venue column
        venue_default = columns.index(mapping['venue']) + 1 if mapping.get('venue') in columns else 0
        venue_col = st.selectbox("Venue/Journal Column", options, index=venue_default, key="map_venue")
        if venue_col != "(not mapped)":
            adjusted['venue'] = venue_col
    
    with col3:
        # Authors column
        auth_default = columns.index(mapping['authors']) + 1 if mapping.get('authors') in columns else 0
        auth_col = st.selectbox("Authors Column", options, index=auth_default, key="map_authors")
        if auth_col != "(not mapped)":
            adjusted['authors'] = auth_col
        
        # Abstract column
        abs_default = columns.index(mapping['abstract']) + 1 if mapping.get('abstract') in columns else 0
        abs_col = st.selectbox("Abstract Column", options, index=abs_default, key="map_abstract")
        if abs_col != "(not mapped)":
            adjusted['abstract'] = abs_col
    
    with col4:
        # Citation string column
        cite_default = columns.index(mapping['citation']) + 1 if mapping.get('citation') in columns else 0
        cite_col = st.selectbox("Citation String Column", options, index=cite_default, key="map_citation")
        if cite_col != "(not mapped)":
            adjusted['citation'] = cite_col
        
        # URL column
        url_default = columns.index(mapping['url']) + 1 if mapping.get('url') in columns else 0
        url_col = st.selectbox("URL Column", options, index=url_default, key="map_url")
        if url_col != "(not mapped)":
            adjusted['url'] = url_col
    
    # Show detection confidence
    confidence = mapping.get('detection_confidence', 0)
    if confidence > 0.7:
        st.success(f"✓ High confidence column detection ({confidence:.0%})")
    elif confidence > 0.4:
        st.info(f"Medium confidence column detection ({confidence:.0%}) - please verify")
    else:
        st.warning(f"Low confidence column detection ({confidence:.0%}) - manual mapping recommended")
    
    return adjusted


def render_import_options() -> dict:
    """Render import options and return settings."""
    st.subheader("Import Options")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        source_name = st.text_input(
            "Source Name",
            value="imported",
            help="Identifier for this import batch"
        )
        
        parse_citations = st.checkbox(
            "Parse citation strings",
            value=True,
            help="Extract title/author/year from citation text"
        )
    
    with col2:
        resolve_dois = st.checkbox(
            "Resolve DOIs",
            value=True,
            help="Fetch full metadata from CrossRef/OpenAlex"
        )
        
        search_crossref = st.checkbox(
            "Search CrossRef when no DOI",
            value=True,
            help="Try to find DOI by title/author search"
        )
        
        queue_only = st.checkbox(
            "Queue only (do not add to corpus)",
            value=False,
            help="Add DOI items to expansion queue; rows without DOI will be skipped"
        )
    
    with col3:
        limit = st.number_input(
            "Max rows to import",
            min_value=0,
            value=0,
            help="0 = import all rows"
        )
    
    return {
        'source_name': source_name,
        'parse_citations': parse_citations,
        'resolve_dois': resolve_dois,
        'search_crossref': search_crossref,
        'queue_only': queue_only,
        'limit': limit if limit > 0 else None
    }


def render_suggestions(suggestions: list):
    """Render suggestions/warnings from file analysis."""
    if not suggestions:
        return
    
    for sug in suggestions:
        sug_type = sug.get('type', 'info')
        msg = sug.get('message', '')
        fix = sug.get('fix', '')
        
        if sug_type == 'warning':
            st.warning(f"⚠️ {msg}")
            if fix:
                st.caption(f"💡 Suggestion: {fix}")
        elif sug_type == 'error':
            st.error(f"❌ {msg}")
            if fix:
                st.caption(f"💡 Suggestion: {fix}")
        else:
            st.info(f"ℹ️ {msg}")


def unique_destination_path(dest_dir: Path, filename: str) -> Path:
    """Create a unique destination path for an uploaded file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(filename).name
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem = dest.stem or "upload"
    suffix = dest.suffix or ".pdf"
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest


def run_import(filepath: Path, options: dict, mapping: dict, db: Database):
    """Run the import with progress tracking."""
    from ingest.smart_importer import SmartImporter, ColumnMapping
    from ingest.citation_parser import CitationParser
    from ingest.doi_resolver import DOIResolver
    
    # Build column mapping
    col_mapping = ColumnMapping(
        doi=mapping.get('doi'),
        title=mapping.get('title'),
        authors=mapping.get('authors'),
        year=mapping.get('year'),
        venue=mapping.get('venue'),
        abstract=mapping.get('abstract'),
        citation=mapping.get('citation'),
        url=mapping.get('url')
    )
    
    # Initialize components
    citation_parser = CitationParser() if options['parse_citations'] else None
    doi_resolver = DOIResolver(email=get('apis.openalex.email')) if options['resolve_dois'] else None
    
    importer = SmartImporter(
        database=db,
        doi_resolver=doi_resolver,
        citation_parser=citation_parser
    )
    
    # Progress tracking
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(current, total):
        progress_bar.progress(current / total)
        status_text.text(f"Processing row {current} of {total}...")
    
    # Run import
    stats = importer.import_file(
        filepath,
        source_name=options['source_name'],
        column_mapping=col_mapping,
        resolve_dois=options['resolve_dois'],
        search_crossref=options['search_crossref'],
        parse_citations=options['parse_citations'],
        queue_only=options['queue_only'],
        limit=options['limit'],
        progress_callback=update_progress
    )
    
    progress_bar.progress(1.0)
    status_text.text("Import complete!")
    
    return stats


def render_import_results(stats: dict):
    """Render import results."""
    st.subheader("Import Results")
    
    # Success metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    
    col1.metric("Total Rows", stats['total_rows'])
    col2.metric("Papers Created", stats['papers_created'], delta_color="normal")
    col3.metric("Papers Updated", stats['papers_updated'])
    col4.metric("DOIs Found", stats['dois_found'])
    col5.metric("Skipped", stats['skipped'])
    
    # Additional stats
    st.divider()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("DOIs Resolved", stats.get('dois_resolved', 0))
    with col2:
        st.metric("Citations Parsed", stats.get('citations_parsed', 0))
    with col3:
        st.metric("Queued", stats.get('queued', 0))
    with col4:
        st.metric("CrossRef Matches", stats.get('crossref_matches', 0))
    
    # Errors
    if stats.get('errors'):
        with st.expander(f"❌ Errors ({len(stats['errors'])})", expanded=len(stats['errors']) < 10):
            for err in stats['errors'][:20]:
                st.error(f"Row {err.get('row', '?')}: {err.get('error', 'Unknown error')}")
            
            if len(stats['errors']) > 20:
                st.warning(f"... and {len(stats['errors']) - 20} more errors")
    
    # Warnings
    if stats.get('warnings'):
        with st.expander(f"⚠️ Warnings ({len(stats['warnings'])})"):
            for warn in stats['warnings'][:20]:
                st.warning(f"{warn.get('type', 'warning')}: {warn.get('message', '')}")


def main():
    st.title("📥 Import References")
    
    db = get_database()
    
    # Tab layout
    tab_file, tab_pdfs, tab_inbox, tab_history = st.tabs(
        ["📄 Import File", "📁 Import PDFs", "📥 Inbox PDFs", "📊 Import History"]
    )
    
    with tab_file:
        st.subheader("Upload Reference File")
        
        uploaded_file = st.file_uploader(
            "Choose a file",
            type=['csv', 'xlsx', 'xls', 'tsv'],
            help="Upload Excel or CSV file with references. Supports various formats."
        )
        
        if uploaded_file:
            # Save to temp file
            suffix = Path(uploaded_file.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = Path(tmp.name)
            
            # Show file info
            st.write(f"**File:** {uploaded_file.name} ({uploaded_file.size / 1024:.1f} KB)")
            
            # Preview file
            try:
                from ingest.smart_importer import SmartImporter
                
                importer = SmartImporter()
                preview = importer.preview_file(tmp_path)
                
                st.divider()
                
                # Show suggestions first
                render_suggestions(preview.get('suggestions', []))
                
                # Preview data
                st.subheader("Data Preview")
                st.caption(f"Showing first {len(preview['sample_rows'])} rows of {preview['file_info'].get('total_rows', '?')} total")
                
                render_preview_table(preview)
                
                # Column mapping
                st.divider()
                adjusted_mapping = render_column_mapping(preview)
                
                # Import options
                st.divider()
                options = render_import_options()
                
                # Import button
                st.divider()
                
                if st.button("🚀 Import References", type="primary"):
                    with st.spinner("Importing..."):
                        try:
                            stats = run_import(tmp_path, options, adjusted_mapping, db)
                            st.success("✅ Import complete!")
                            render_import_results(stats)
                        except Exception as e:
                            st.error(f"Import failed: {e}")
                            import traceback
                            st.code(traceback.format_exc())
                
                # Cleanup
                try:
                    tmp_path.unlink()
                except:
                    pass
                
            except Exception as e:
                st.error(f"Failed to preview file: {e}")
                import traceback
                st.code(traceback.format_exc())
    
    with tab_pdfs:
        st.subheader("Import from PDF Directory")
        st.caption("Catalog PDF files and create paper records from filenames")
        
        pdf_dir = st.text_input(
            "PDF Directory Path",
            value=str(Path(get('paths.pdfs', 'data/pdfs'))),
            help="Path to directory containing PDF files"
        )
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            pdf_source = st.text_input("Source Name", value="pdf_catalog")
            search_crossref_pdf = st.checkbox("Search CrossRef for metadata", value=True)
            extract_doi_from_text = st.checkbox("Extract DOI from PDF text", value=True)
        
        with col2:
            pdf_limit = st.number_input("Max PDFs to process", min_value=0, value=50)
            copy_to_storage = st.checkbox("Copy PDFs into storage", value=False)

        with col3:
            pdf_storage_dir = st.text_input(
                "PDF Storage Directory",
                value=str(Path(get('paths.pdfs', 'data/pdfs'))),
                help="Used when copying PDFs into storage"
            )
        
        if st.button("🔍 Scan PDFs"):
            pdf_path = Path(pdf_dir)
            
            if not pdf_path.exists():
                st.error(f"Directory not found: {pdf_dir}")
            else:
                try:
                    from ingest.pdf_cataloger import PDFCataloger
                    
                    cataloger = PDFCataloger()
                    
                    # Show preview of PDFs
                    pdfs = list(pdf_path.glob("*.pdf"))[:20]
                    st.write(f"Found {len(list(pdf_path.glob('*.pdf')))} PDFs")
                    
                    if pdfs:
                        preview_data = []
                        for pdf in pdfs[:10]:
                            meta = cataloger.filename_parser.parse(pdf.name)
                            preview_data.append({
                                'Filename': pdf.name[:40],
                                'Authors': ', '.join(meta.authors[:2]) if meta.authors else '-',
                                'Year': meta.year or '-',
                                'Title': (meta.title or '-')[:40],
                                'Confidence': f"{meta.confidence:.0%}"
                            })
                        
                        import pandas as pd
                        st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)
                        
                        if st.button("📥 Import PDFs", type="primary"):
                            with st.spinner("Processing PDFs..."):
                                from ingest.doi_resolver import DOIResolver
                                
                                resolver = DOIResolver(email=get('apis.openalex.email')) if search_crossref_pdf else None
                                cataloger = PDFCataloger(
                                    database=db,
                                    doi_resolver=resolver,
                                    pdf_storage_dir=Path(pdf_storage_dir) if copy_to_storage else None,
                                    copy_to_storage=copy_to_storage,
                                    extract_doi_from_text=extract_doi_from_text
                                )
                                
                                stats = cataloger.catalog_directory(
                                    pdf_path,
                                    source_name=pdf_source,
                                    search_crossref=search_crossref_pdf,
                                    limit=pdf_limit if pdf_limit > 0 else None
                                )
                                
                                st.success("✅ PDF import complete!")
                                
                                col1, col2, col3, col4, col5 = st.columns(5)
                                col1.metric("Total PDFs", stats['total_pdfs'])
                                col2.metric("Papers Created", stats['created'])
                                col3.metric("CrossRef Matches", stats['matched_crossref'])
                                col4.metric("Copied", stats.get('copied', 0))
                                col5.metric("Already Present", stats.get('already_present', 0))
                except ImportError as e:
                    st.error(f"Missing dependency: {e}")
                except Exception as e:
                    st.error(f"Error: {e}")

    with tab_inbox:
        st.subheader("Inbox PDF Ingestion")
        st.caption("Drop PDFs into the inbox folder or upload them here, then process.")

        inbox_dir = st.text_input(
            "Inbox Directory",
            value=str(Path(get('paths.inbox_pdfs', 'data/inbox_pdfs'))),
            help="Folder watched for new PDFs"
        )

        uploaded_pdfs = st.file_uploader(
            "Upload PDFs to Inbox",
            type=['pdf'],
            accept_multiple_files=True
        )

        if uploaded_pdfs:
            inbox_path = Path(inbox_dir)
            saved = 0
            for pdf in uploaded_pdfs:
                dest = unique_destination_path(inbox_path, pdf.name)
                dest.write_bytes(pdf.getvalue())
                saved += 1
            st.success(f"Saved {saved} PDFs to inbox")

        inbox_path = Path(inbox_dir)
        inbox_files = list(inbox_path.glob("*.pdf")) if inbox_path.exists() else []
        st.write(f"Found {len(inbox_files)} PDFs in inbox")

        if inbox_files:
            st.caption("Preview")
            for pdf in inbox_files[:5]:
                st.write(f"- {pdf.name}")

        col1, col2, col3 = st.columns(3)

        with col1:
            inbox_source = st.text_input("Source Name", value="pdf_inbox", key="inbox_source")
            resolve_dois = st.checkbox("Resolve DOIs", value=True, key="inbox_resolve")
            search_crossref = st.checkbox("Search CrossRef when no DOI", value=True, key="inbox_crossref")

        with col2:
            copy_to_storage = st.checkbox("Copy into storage", value=True, key="inbox_copy")
            extract_doi_from_text = st.checkbox("Extract DOI from PDF text", value=True, key="inbox_text_doi")
            inbox_limit = st.number_input("Max PDFs to process", min_value=0, value=100, key="inbox_limit")

        with col3:
            inbox_storage_dir = st.text_input(
                "PDF Storage Directory",
                value=str(Path(get('paths.pdfs', 'data/pdfs'))),
                key="inbox_storage_dir"
            )
            archive_processed = st.checkbox("Archive processed PDFs", value=True, key="inbox_archive")
            archive_dir = st.text_input(
                "Archive Directory",
                value=str(Path(inbox_dir) / "processed"),
                key="inbox_archive_dir"
            )

        if st.button("📥 Process Inbox", type="primary"):
            if not inbox_path.exists():
                st.error(f"Directory not found: {inbox_dir}")
            else:
                with st.spinner("Processing inbox PDFs..."):
                    try:
                        from ingest.pdf_watcher import PDFWatcherService
                        from ingest.doi_resolver import DOIResolver

                        resolver = None
                        if resolve_dois or search_crossref:
                            email = get('apis.openalex.email')
                            if email and '@' in email:
                                resolver = DOIResolver(email=email)
                            else:
                                st.warning("No valid API email configured; DOI resolution is disabled.")

                        service = PDFWatcherService(
                            watch_dir=inbox_path,
                            database=db,
                            resolver=resolver,
                            storage_dir=Path(inbox_storage_dir) if copy_to_storage else None,
                            archive_dir=Path(archive_dir) if archive_processed else None,
                            source_name=inbox_source,
                            copy_to_storage=copy_to_storage,
                            extract_doi_from_text=extract_doi_from_text,
                            resolve_dois=resolve_dois,
                            search_crossref=search_crossref
                        )

                        stats = service.process_once(limit=inbox_limit if inbox_limit > 0 else None)

                        st.success("✅ Inbox processing complete!")

                        col1, col2, col3, col4, col5 = st.columns(5)
                        col1.metric("Total PDFs", stats.get('total_pdfs', 0))
                        col2.metric("Processed", stats.get('processed', 0))
                        col3.metric("Created", stats.get('created', 0))
                        col4.metric("Updated", stats.get('updated', 0))
                        col5.metric("Archived", stats.get('archived', 0))

                        col1, col2, col3 = st.columns(3)
                        col1.metric("Copied", stats.get('copied', 0))
                        col2.metric("Already Present", stats.get('already_present', 0))
                        col3.metric("Errors", len(stats.get('errors', [])))
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    with tab_history:
        st.subheader("Import History")
        
        # Get papers grouped by source
        papers = db.search_papers(limit=1000)
        
        if papers:
            by_source = {}
            for p in papers:
                source = p.get('source', 'unknown')
                if source not in by_source:
                    by_source[source] = {'count': 0, 'with_doi': 0, 'with_abstract': 0, 'with_pdf': 0}
                by_source[source]['count'] += 1
                if p.get('doi'):
                    by_source[source]['with_doi'] += 1
                if p.get('abstract'):
                    by_source[source]['with_abstract'] += 1
                if p.get('pdf_path'):
                    by_source[source]['with_pdf'] += 1
            
            import pandas as pd
            df = pd.DataFrame([
                {
                    'Source': source,
                    'Papers': stats['count'],
                    'With DOI': f"{100*stats['with_doi']/stats['count']:.0f}%",
                    'With Abstract': f"{100*stats['with_abstract']/stats['count']:.0f}%",
                    'With PDF': f"{100*stats['with_pdf']/stats['count']:.0f}%"
                }
                for source, stats in sorted(by_source.items(), key=lambda x: -x[1]['count'])
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No papers imported yet")
        
        # Enrichment section
        st.divider()
        st.subheader("Enrich Papers")
        st.caption("Fetch missing metadata (abstracts, authors) from APIs")
        
        papers_missing = [p for p in papers if not p.get('abstract') and p.get('doi')]
        st.write(f"Papers needing enrichment: {len(papers_missing)}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            enrich_email = st.text_input("Email for API", value=get('apis.openalex.email', 'your-email@example.com'))
        with col2:
            enrich_limit = st.number_input("Max to enrich", min_value=1, max_value=500, value=50)
        
        if st.button("🔄 Enrich Papers"):
            if '@' not in enrich_email:
                st.error("Please enter a valid email")
            else:
                with st.spinner(f"Enriching up to {enrich_limit} papers..."):
                    try:
                        from ingest.enricher import BatchEnricher
                        
                        enricher = BatchEnricher(db, email=enrich_email)
                        stats = enricher.enrich_all(limit=enrich_limit)
                        
                        st.success(f"✅ Enriched {stats.get('enriched', 0)} papers!")
                    except ImportError:
                        # Fallback to basic enrichment
                        from ingest.doi_resolver import DOIResolver
                        
                        resolver = DOIResolver(email=enrich_email)
                        enriched = 0
                        
                        progress = st.progress(0)
                        for i, p in enumerate(papers_missing[:enrich_limit]):
                            if p.get('doi'):
                                result = resolver.resolve(p['doi'])
                                if result and result.get('abstract'):
                                    p['abstract'] = result['abstract']
                                    if result.get('authors') and not p.get('authors'):
                                        p['authors'] = result['authors']
                                    db.add_paper(p)
                                    enriched += 1
                            progress.progress((i + 1) / min(len(papers_missing), enrich_limit))
                        
                        st.success(f"✅ Enriched {enriched} papers!")
                    except Exception as e:
                        st.error(f"Error: {e}")


if __name__ == "__main__":
    main()
