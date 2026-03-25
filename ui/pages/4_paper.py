# Version: 3.2.2
"""
Article Finder v3 - Paper Detail Page
Full paper view with facet scores and extracted claims.
"""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

st.set_page_config(page_title="Paper Detail - Article Finder", layout="wide")


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
        return ", ".join(
            a.get('name', str(a)) if isinstance(a, dict) else str(a)
            for a in authors
        )
    return str(authors)


def main():
    st.title("📄 Paper Detail")
    
    db = get_database()
    
    # Paper ID input
    paper_id = st.text_input(
        "Paper ID",
        placeholder="Enter paper ID (e.g., doi:10.1234/example)",
        help="Enter a paper ID or DOI"
    )
    
    # Also allow DOI without prefix
    if paper_id and not paper_id.startswith(('doi:', 'sha256:')):
        if '10.' in paper_id:
            paper_id = f"doi:{paper_id}"
    
    if not paper_id:
        # Show recent papers as links
        st.subheader("Recent Papers")
        
        recent = db.search_papers(limit=10)
        for p in recent:
            title = p.get('title', 'Untitled')[:60]
            if st.button(f"📄 {title}", key=p['paper_id']):
                st.session_state.selected_paper = p['paper_id']
                st.rerun()
        
        if 'selected_paper' in st.session_state:
            paper_id = st.session_state.selected_paper
        else:
            return
    
    # Get paper
    paper = db.get_paper(paper_id)
    if not paper:
        # Try as DOI
        paper = db.get_paper_by_doi(paper_id.replace('doi:', ''))
    
    if not paper:
        st.error(f"Paper not found: {paper_id}")
        return
    
    # Display paper
    st.subheader(paper.get('title', 'Untitled'))
    
    # Metadata
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("**Authors:**", format_authors(paper.get('authors')))
        st.write("**Year:**", paper.get('year', 'N/A'))
    
    with col2:
        st.write("**Venue:**", paper.get('venue', 'N/A'))
        st.write("**Publisher:**", paper.get('publisher', 'N/A'))
    
    with col3:
        doi = paper.get('doi')
        if doi:
            st.write("**DOI:**", f"[{doi}](https://doi.org/{doi})")
        st.write("**Status:**", paper.get('status', 'unknown'))
    
    st.divider()
    
    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["Abstract", "Classification", "Claims & Rules", "Metadata"])
    
    with tab1:
        abstract = paper.get('abstract')
        if abstract:
            st.write(abstract)
        else:
            st.info("No abstract available.")
    
    with tab2:
        # Facet scores
        scores = db.get_paper_facet_scores(paper['paper_id'])
        
        if scores:
            st.write(f"**Triage Score:** {paper.get('triage_score', 0):.3f}")
            st.write(f"**Decision:** {paper.get('triage_decision', 'N/A')}")
            
            st.divider()
            
            # Group by facet
            facet_groups = {}
            for node_id, score in scores.items():
                facet = node_id.split('.')[0] if '.' in node_id else 'other'
                if facet not in facet_groups:
                    facet_groups[facet] = []
                facet_groups[facet].append((node_id, score))
            
            for facet, nodes in sorted(facet_groups.items()):
                with st.expander(f"{facet.replace('_', ' ').title()} ({len(nodes)} matches)"):
                    sorted_nodes = sorted(nodes, key=lambda x: -x[1])
                    for node_id, score in sorted_nodes[:10]:
                        node = db.get_node(node_id)
                        name = node['name'] if node else node_id
                        st.write(f"- **{score:.3f}**: {name}")
        else:
            st.info("Paper has not been classified yet.")
            
            if st.button("Classify Now"):
                with st.spinner("Classifying..."):
                    try:
                        from triage.scorer import HierarchicalScorer
                        scorer = HierarchicalScorer(db)
                        result = scorer.score_and_store(paper)
                        st.success(f"Classified! Score: {result['triage_score']:.3f}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    with tab3:
        # Claims
        claims = db.get_claims_by_paper(paper['paper_id'])
        
        if claims:
            st.subheader(f"Claims ({len(claims)})")
            
            for claim in claims:
                with st.expander(f"Claim: {claim.get('claim_type', 'unknown')}"):
                    st.write(f"**Statement:** {claim.get('statement', 'N/A')}")
                    
                    effect = claim.get('effect_size_value')
                    if effect:
                        st.write(f"**Effect Size:** {claim.get('effect_size_type', '')} = {effect}")
                    
                    p_value = claim.get('p_value')
                    if p_value:
                        st.write(f"**p-value:** {p_value}")
                    
                    st.write(f"**Confidence:** {claim.get('ae_confidence', 0):.2f}")
        else:
            st.info("No claims extracted yet.")
        
        # Rules
        rules = db.get_rules_by_paper(paper['paper_id'])
        
        if rules:
            st.subheader(f"Rules ({len(rules)})")
            
            for rule in rules:
                with st.expander(f"Rule: {rule.get('rule_type', 'unknown')}"):
                    lhs = rule.get('lhs', [])
                    rhs = rule.get('rhs', [])
                    
                    if isinstance(lhs, list) and lhs:
                        lhs_str = ', '.join(f"{v.get('var')}={v.get('state')}" for v in lhs if isinstance(v, dict))
                    else:
                        lhs_str = str(lhs)
                    
                    if isinstance(rhs, list) and rhs:
                        rhs_str = ', '.join(f"{v.get('var')}={v.get('state')}" for v in rhs if isinstance(v, dict))
                    else:
                        rhs_str = str(rhs)
                    
                    st.write(f"**{lhs_str}** → **{rhs_str}**")
                    st.write(f"**Polarity:** {rule.get('polarity', 'unknown')}")
                    st.write(f"**Confidence:** {rule.get('ae_confidence', 0):.2f}")
        elif not claims:
            st.info("Paper has not been processed by Article Eater yet.")
    
    with tab4:
        st.json(paper)


if __name__ == "__main__":
    main()
