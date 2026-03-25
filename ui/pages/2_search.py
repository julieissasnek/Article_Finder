# Version: 3.2.2
"""
Article Finder v3 - Search Page
Keyword and semantic search with faceted filtering.
"""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

st.set_page_config(page_title="Search - Article Finder", layout="wide")


@st.cache_resource
def get_database():
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))


def format_authors(authors):
    """Format authors list for display."""
    if not authors:
        return "Unknown"
    if isinstance(authors, str):
        return authors
    if isinstance(authors, list):
        names = [a.get('name', str(a)) if isinstance(a, dict) else str(a) for a in authors[:3]]
        if len(authors) > 3:
            names.append(f"et al. (+{len(authors)-3})")
        return ", ".join(names)
    return str(authors)


def main():
    st.title("🔍 Search")
    
    db = get_database()
    
    # Search inputs
    col1, col2 = st.columns([3, 1])
    
    with col1:
        query = st.text_input(
            "Search",
            placeholder="Enter keywords or paste a title...",
            label_visibility="collapsed"
        )
    
    with col2:
        search_type = st.selectbox(
            "Type",
            ["Keyword", "Semantic"],
            label_visibility="collapsed"
        )
    
    # Filters
    with st.expander("Filters", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            status_filter = st.selectbox(
                "Status",
                ["All", "candidate", "send_to_eater", "review", "reject", 
                 "processed_success", "processed_partial", "processed_fail"]
            )
        
        with col2:
            year_min = st.number_input("Year from", min_value=1900, max_value=2030, value=1990)
        
        with col3:
            year_max = st.number_input("Year to", min_value=1900, max_value=2030, value=2025)
        
        with col4:
            has_abstract = st.checkbox("Has abstract", value=False)
    
    # Search button
    if st.button("Search", type="primary") or query:
        with st.spinner("Searching..."):
            if search_type == "Keyword":
                # Keyword search
                results = db.search_papers(
                    query=query if query else None,
                    status=status_filter if status_filter != "All" else None,
                    year_min=year_min,
                    year_max=year_max,
                    limit=100
                )
            else:
                # Semantic search
                if query:
                    try:
                        from triage.embeddings import get_embedding_service
                        from triage.scorer import HierarchicalScorer
                        
                        embeddings = get_embedding_service()
                        query_embedding = embeddings.embed(query)
                        
                        # Get all papers with abstracts
                        all_papers = db.search_papers(limit=5000)
                        all_papers = [p for p in all_papers if p.get('abstract')]
                        
                        if has_abstract:
                            all_papers = [p for p in all_papers if p.get('abstract')]
                        
                        if status_filter != "All":
                            all_papers = [p for p in all_papers if p.get('status') == status_filter]
                        
                        all_papers = [p for p in all_papers if year_min <= (p.get('year') or 2000) <= year_max]
                        
                        # Score papers
                        scored = []
                        for p in all_papers:
                            text = f"{p.get('title', '')}. {p.get('abstract', '')}"
                            paper_embedding = embeddings.embed(text)
                            sim = embeddings.similarity(query_embedding, paper_embedding)
                            scored.append((sim, p))
                        
                        scored.sort(key=lambda x: -x[0])
                        results = [p for _, p in scored[:100]]
                        
                        # Add similarity scores
                        for i, (sim, p) in enumerate(scored[:100]):
                            results[i]['_similarity'] = sim
                            
                    except ImportError:
                        st.error("Semantic search requires sentence-transformers. Falling back to keyword.")
                        results = db.search_papers(query=query, limit=100)
                else:
                    results = db.search_papers(limit=100)
            
            # Apply additional filters
            if has_abstract:
                results = [r for r in results if r.get('abstract')]
        
        # Display results
        st.subheader(f"Results ({len(results)})")
        
        if not results:
            st.info("No papers found matching your criteria.")
        else:
            for paper in results:
                with st.container():
                    # Title and metadata
                    col1, col2 = st.columns([4, 1])
                    
                    with col1:
                        title = paper.get('title', 'Untitled')
                        doi = paper.get('doi')
                        
                        if doi:
                            st.markdown(f"**[{title}](https://doi.org/{doi})**")
                        else:
                            st.markdown(f"**{title}**")
                        
                        authors = format_authors(paper.get('authors'))
                        year = paper.get('year', 'N/A')
                        venue = paper.get('venue', '')
                        
                        st.caption(f"{authors} • {year} • {venue}")
                    
                    with col2:
                        status = paper.get('status', 'unknown')
                        score = paper.get('triage_score')
                        sim = paper.get('_similarity')
                        
                        if sim:
                            st.metric("Similarity", f"{sim:.2f}")
                        elif score:
                            st.metric("Score", f"{score:.2f}")
                        
                        # Status badge
                        status_colors = {
                            'send_to_eater': '🟢',
                            'review': '🟡',
                            'reject': '🔴',
                            'candidate': '⚪',
                            'processed_success': '✅',
                            'processed_partial': '⚠️',
                            'processed_fail': '❌'
                        }
                        st.write(f"{status_colors.get(status, '⚪')} {status}")
                    
                    # Abstract (expandable)
                    abstract = paper.get('abstract')
                    if abstract:
                        with st.expander("Abstract"):
                            st.write(abstract[:500] + "..." if len(abstract) > 500 else abstract)
                    
                    st.divider()
    
    else:
        # Show recent papers
        st.subheader("Recent Papers")
        
        recent = db.search_papers(limit=20)
        
        if recent:
            import pandas as pd
            
            df = pd.DataFrame([
                {
                    'Title': p.get('title', 'Untitled')[:60] + ('...' if len(p.get('title', '')) > 60 else ''),
                    'Year': p.get('year'),
                    'Status': p.get('status', 'unknown'),
                    'Score': f"{p.get('triage_score', 0):.2f}" if p.get('triage_score') else '-'
                }
                for p in recent
            ])
            
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No papers in corpus yet.")


if __name__ == "__main__":
    main()
