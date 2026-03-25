# Version: 3.2.2
"""
Article Finder v3 - Streamlit UI
Main application entry point.

Run with: streamlit run ui/app.py
"""

import streamlit as st
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from config.loader import get, ensure_directories

# Page config
st.set_page_config(
    page_title="Article Finder v3",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize
ensure_directories()


@st.cache_resource
def get_database():
    """Get cached database connection."""
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))


def main():
    st.title("📚 Article Finder v3")
    st.markdown("*Neuroarchitecture Literature Corpus Management*")
    
    db = get_database()
    stats = db.get_corpus_stats()
    
    # Quick stats
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Papers", stats.get('total_papers', 0))
    
    with col2:
        st.metric("Claims Extracted", stats.get('total_claims', 0))
    
    with col3:
        st.metric("Rules Extracted", stats.get('total_rules', 0))
    
    with col4:
        st.metric("Expansion Queue", stats.get('expansion_queue_pending', 0))
    
    st.divider()
    
    # Status breakdown
    st.subheader("Papers by Status")
    
    status_data = stats.get('papers_by_status', {})
    if status_data:
        cols = st.columns(len(status_data))
        for i, (status, count) in enumerate(sorted(status_data.items())):
            with cols[i % len(cols)]:
                st.metric(status.replace('_', ' ').title(), count)
    else:
        st.info("No papers in corpus yet. Import some references to get started!")
    
    st.divider()
    
    # Quick actions
    st.subheader("Quick Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.page_link("pages/1_dashboard.py", label="📊 Dashboard", icon="📊")
        st.caption("Corpus statistics and visualizations")
    
    with col2:
        st.page_link("pages/2_search.py", label="🔍 Search", icon="🔍")
        st.caption("Search and filter papers")
    
    with col3:
        st.page_link("pages/3_triage.py", label="📋 Triage Queue", icon="📋")
        st.caption("Review and approve papers")
    
    # Footer
    st.divider()
    st.caption("Article Finder v3.0 | UCSD Cognitive Science")


if __name__ == "__main__":
    main()
