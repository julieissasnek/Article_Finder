# Version: 3.2.2
"""
Article Finder v3 - Dashboard Page
Corpus statistics and visualizations.
"""

import streamlit as st
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

def _load_api_metrics():
    path = Path(get('paths.api_metrics', 'data/api_metrics.json'))
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _format_api_metric(stats: dict) -> tuple[str, str]:
    if not stats or not stats.get('requests'):
        return ("N/A", "")
    requests = stats.get('requests', 0)
    errors = stats.get('errors', 0)
    avg_ms = stats.get('avg_ms', 0.0)
    error_rate = (errors / requests) * 100 if requests else 0.0
    return (f"{error_rate:.1f}%", f"{avg_ms:.0f} ms")

st.set_page_config(page_title="Dashboard - Article Finder", layout="wide")


@st.cache_resource
def get_database():
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))


def main():
    st.title("📊 Dashboard")
    
    db = get_database()
    
    # Get all papers for analysis
    papers = db.search_papers(limit=10000)
    
    if not papers:
        st.warning("No papers in corpus. Import some references to see statistics.")
        return
    
    # Overview metrics
    st.subheader("Corpus Overview")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total = len(papers)
    with_doi = sum(1 for p in papers if p.get('doi'))
    with_abstract = sum(1 for p in papers if p.get('abstract'))
    with_pdf = sum(1 for p in papers if p.get('pdf_path'))
    processed = sum(1 for p in papers if p.get('status', '').startswith('processed'))
    
    col1.metric("Total Papers", total)
    col2.metric("With DOI", with_doi, f"{100*with_doi/total:.0f}%" if total else "")
    col3.metric("With Abstract", with_abstract, f"{100*with_abstract/total:.0f}%" if total else "")
    col4.metric("With PDF", with_pdf, f"{100*with_pdf/total:.0f}%" if total else "")
    col5.metric("Processed", processed)
    
    st.divider()
    
    st.subheader("Efficiency (Last 24 Hours)")
    
    with db.connection() as conn:
        papers_24h = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE created_at >= datetime('now','-24 hours')"
        ).fetchone()[0]
        citations_24h = conn.execute(
            "SELECT COUNT(*) FROM citations WHERE created_at >= datetime('now','-24 hours')"
        ).fetchone()[0]
        pdfs_24h = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != '' AND updated_at >= datetime('now','-24 hours')"
        ).fetchone()[0]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Papers/hour", f"{papers_24h/24:.1f}")
    col2.metric("Citations/hour", f"{citations_24h/24:.1f}")
    col3.metric("PDFs/hour", f"{pdfs_24h/24:.1f}")
    
    st.subheader("API Health")
    api_metrics = _load_api_metrics()
    openalex_rate, openalex_ms = _format_api_metric(api_metrics.get('openalex'))
    crossref_rate, crossref_ms = _format_api_metric(api_metrics.get('crossref'))
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("OpenAlex error rate", openalex_rate)
    col2.metric("OpenAlex avg", openalex_ms)
    col3.metric("CrossRef error rate", crossref_rate)
    col4.metric("CrossRef avg", crossref_ms)
    
    st.divider()
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Papers by Status")
        
        status_counts = {}
        for p in papers:
            status = p.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        if status_counts:
            import pandas as pd
            df = pd.DataFrame([
                {'Status': k, 'Count': v} 
                for k, v in sorted(status_counts.items())
            ])
            st.bar_chart(df, x='Status', y='Count')
    
    with col2:
        st.subheader("Papers by Year")
        
        year_counts = {}
        for p in papers:
            year = p.get('year')
            if year and 1950 <= year <= 2030:
                year_counts[year] = year_counts.get(year, 0) + 1
        
        if year_counts:
            import pandas as pd
            df = pd.DataFrame([
                {'Year': k, 'Count': v}
                for k, v in sorted(year_counts.items())
            ])
            st.line_chart(df, x='Year', y='Count')
    
    st.divider()
    
    # Triage distribution
    st.subheader("Triage Distribution")
    
    col1, col2 = st.columns(2)
    
    with col1:
        decision_counts = {}
        for p in papers:
            decision = p.get('triage_decision') or 'unscored'
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        
        if decision_counts:
            import pandas as pd
            df = pd.DataFrame([
                {'Decision': k, 'Count': v}
                for k, v in sorted(decision_counts.items())
            ])
            st.bar_chart(df, x='Decision', y='Count')
    
    with col2:
        # Score histogram
        scores = [p.get('triage_score', 0) for p in papers if p.get('triage_score') is not None]
        
        if scores:
            import pandas as pd
            st.write(f"Score distribution (n={len(scores)})")
            df = pd.DataFrame({'Triage Score': scores})
            st.bar_chart(df['Triage Score'].value_counts().sort_index())
    
    st.divider()
    
    # Top sources
    st.subheader("Top Sources")
    
    source_counts = {}
    for p in papers:
        source = p.get('source', 'unknown')
        source_counts[source] = source_counts.get(source, 0) + 1
    
    if source_counts:
        import pandas as pd
        df = pd.DataFrame([
            {'Source': k, 'Count': v}
            for k, v in sorted(source_counts.items(), key=lambda x: -x[1])[:10]
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Top venues
    st.subheader("Top Venues")
    
    venue_counts = {}
    for p in papers:
        venue = p.get('venue')
        if venue:
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
    
    if venue_counts:
        import pandas as pd
        df = pd.DataFrame([
            {'Venue': k, 'Count': v}
            for k, v in sorted(venue_counts.items(), key=lambda x: -x[1])[:15]
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
