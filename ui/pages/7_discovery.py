# Version: 3.2.2
"""
Article Finder v3.2 - Discovery Dashboard
Streamlit page for monitoring corpus discovery and expansion.
"""

import streamlit as st
from pathlib import Path
import json
from datetime import datetime

# Page config
st.set_page_config(page_title="Discovery Dashboard", page_icon="🔍", layout="wide")

st.title("🔍 Discovery Dashboard")
st.markdown("Monitor corpus expansion and paper discovery")

# Initialize database
@st.cache_resource
def get_database():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.database import Database
    from config.loader import get
    return Database(Path(get('paths.database', 'data/article_finder.db')))

db = get_database()

# Sidebar controls
st.sidebar.header("Discovery Controls")

# Get corpus stats
stats = db.get_corpus_stats()

# Display key metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Papers", stats.get('total_papers', 0))

with col2:
    st.metric("With DOI", stats.get('papers_with_doi', 0))

with col3:
    st.metric("With PDF", stats.get('papers_with_pdf', 0))

with col4:
    st.metric("Expansion Queue", stats.get('expansion_queue_pending', 0))

st.divider()

# Tabs for different views
tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🔄 Expansion", "📥 Acquisition", "⚙️ Run Discovery"])

with tab1:
    st.subheader("Corpus Composition")
    
    # Papers by triage status
    papers_by_status = stats.get('papers_by_status', {})
    if papers_by_status:
        import pandas as pd
        df = pd.DataFrame([
            {'Status': status, 'Count': count}
            for status, count in papers_by_status.items()
        ])
        st.bar_chart(df.set_index('Status'))
    else:
        st.info("No papers in corpus yet")
    
    # Papers by source
    st.subheader("Papers by Source")
    papers = db.search_papers(limit=10000)
    sources = {}
    for p in papers:
        source = p.get('source', 'unknown')
        sources[source] = sources.get(source, 0) + 1
    
    if sources:
        import pandas as pd
        df = pd.DataFrame([
            {'Source': s, 'Papers': c}
            for s, c in sorted(sources.items(), key=lambda x: -x[1])
        ])
        st.dataframe(df, use_container_width=True)
    
    # Recent additions
    st.subheader("Recent Additions")
    recent = sorted(papers, key=lambda p: p.get('created_at', ''), reverse=True)[:10]
    for p in recent:
        with st.expander(f"📄 {p.get('title', 'Untitled')[:60]}..."):
            st.write(f"**DOI:** {p.get('doi', 'N/A')}")
            st.write(f"**Year:** {p.get('year', 'N/A')}")
            st.write(f"**Source:** {p.get('source', 'N/A')}")
            st.write(f"**Status:** {p.get('triage_decision', 'N/A')}")
            if p.get('pdf_path'):
                st.success("✅ Has PDF")
            else:
                st.warning("📭 No PDF")

with tab2:
    st.subheader("Expansion Queue")
    
    queue = db.get_expansion_queue(limit=50)
    
    if queue:
        st.info(f"**{len(queue)}** papers in queue (showing first 50)")
        
        for item in queue[:20]:
            score = item.get('relevance_score', item.get('priority_score', 0)) or 0
            title = item.get('title', 'Unknown')[:60]
            doi = item.get('doi', 'no-doi')
            
            col1, col2, col3 = st.columns([0.7, 0.15, 0.15])
            with col1:
                st.write(f"**{title}**")
                st.caption(f"DOI: {doi}")
            with col2:
                st.metric("Score", f"{score:.2f}")
            with col3:
                if st.button("Add", key=f"add_{doi}"):
                    # Add to corpus
                    paper = {
                        'paper_id': f"doi:{doi}",
                        'doi': doi,
                        'title': item.get('title'),
                        'authors': item.get('authors', []),
                        'year': item.get('year'),
                        'source': 'expansion_queue',
                        'triage_decision': 'needs_review'
                    }
                    db.add_paper(paper)
                    db.update_expansion_queue_status(doi, 'processed')
                    st.rerun()
        
        st.divider()
        
        # Bulk actions
        st.subheader("Bulk Actions")
        
        col1, col2 = st.columns(2)
        with col1:
            min_score = st.slider("Minimum score to accept", 0.0, 1.0, 0.4, 0.05)
        with col2:
            if st.button("Accept all above threshold"):
                accepted = 0
                for item in queue:
                    score = item.get('relevance_score', item.get('priority_score', 0)) or 0
                    if score >= min_score:
                        paper = {
                            'paper_id': f"doi:{item.get('doi')}",
                            'doi': item.get('doi'),
                            'title': item.get('title'),
                            'authors': item.get('authors', []),
                            'year': item.get('year'),
                            'source': 'expansion_queue',
                            'triage_decision': 'needs_review'
                        }
                        db.add_paper(paper)
                        db.update_expansion_queue_status(item.get('doi'), 'processed')
                        accepted += 1
                st.success(f"Accepted {accepted} papers")
                st.rerun()
    else:
        st.info("Expansion queue is empty")
        st.write("Run expansion to discover new papers:")
        st.code("python cli/main.py expand --limit 20")

with tab3:
    st.subheader("PDF Acquisition Status")
    
    papers = db.search_papers(limit=10000)
    
    with_doi = [p for p in papers if p.get('doi')]
    with_pdf = [p for p in papers if p.get('pdf_path')]
    pending = [p for p in with_doi if not p.get('pdf_path') and p.get('triage_decision') == 'send_to_eater']
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Papers with DOI", len(with_doi))
    with col2:
        st.metric("PDFs Downloaded", len(with_pdf))
    with col3:
        st.metric("Awaiting Download", len(pending))
    
    if with_doi:
        coverage = len(with_pdf) / len(with_doi) * 100
        coverage_ratio = max(0.0, min(coverage / 100, 1.0))
    st.progress(coverage_ratio, text=f"PDF Coverage: {coverage:.1f}%")
    
    st.divider()
    
    st.subheader("Pending Downloads")
    
    for p in pending[:20]:
        col1, col2 = st.columns([0.8, 0.2])
        with col1:
            st.write(f"**{p.get('title', 'Untitled')[:50]}**")
            st.caption(f"DOI: {p.get('doi')}")
        with col2:
            if st.button("Download", key=f"dl_{p.get('paper_id')}"):
                try:
                    from ingest.pdf_downloader import PDFDownloader
                    from config.loader import get
                    
                    email = get('apis.unpaywall.email', get('apis.openalex.email'))
                    if email:
                        downloader = PDFDownloader(db, email=email)
                        result = downloader.download_pdf(p['paper_id'])
                        if result['success']:
                            st.success(f"✅ Downloaded")
                        else:
                            st.error(f"❌ {result.get('error', 'Failed')}")
                    else:
                        st.error("No email configured")
                except Exception as e:
                    st.error(f"Error: {e}")
    
    if not pending:
        st.success("All eligible papers have PDFs!")

with tab4:
    st.subheader("Run Discovery Pipeline")
    
    st.write("""
    The discovery pipeline:
    1. **Classify** - Score papers against taxonomy
    2. **Expand** - Find related papers via citations
    3. **Acquire** - Download available PDFs
    4. **Bundle** - Create Article Eater jobs
    """)
    
    with st.form("discovery_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            threshold = st.slider("Relevance Threshold", 0.0, 1.0, 0.35, 0.05,
                                help="Minimum taxonomy score to accept papers")
            expansion_limit = st.number_input("Expansion Limit", 10, 200, 50,
                                            help="Papers to expand per iteration")
        
        with col2:
            max_depth = st.slider("Max Citation Depth", 1, 5, 2,
                                help="Maximum citation hops from seed papers")
            iterations = st.slider("Max Iterations", 1, 10, 3,
                                 help="Maximum expansion iterations")
        
        pdf_limit = st.number_input("PDF Download Limit", 0, 500, 100,
                                   help="Maximum PDFs to download (0 to skip)")
        
        email = st.text_input("Email (for API access)",
                            value="",
                            help="Required for Unpaywall and OpenAlex")
        
        submitted = st.form_submit_button("▶️ Run Discovery", type="primary")
        
        if submitted:
            if not email or '@' not in email:
                st.error("Valid email required")
            else:
                st.info("Discovery started... Check terminal for progress")
                st.code(f"""python cli/main.py discover \\
    --threshold {threshold} \\
    --depth {max_depth} \\
    --iterations {iterations} \\
    --expansion-limit {expansion_limit} \\
    --pdf-limit {pdf_limit} \\
    --email {email}""")
                st.warning("Note: For long runs, use the CLI directly")

# Footer
st.divider()
st.caption("Article Finder v3.2 | Discovery Dashboard")
