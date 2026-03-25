# Version: 3.2.2
"""
Article Finder v3.2 - Citation Network Visualization
Interactive graph visualization of citation relationships.
"""

import streamlit as st
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

st.set_page_config(page_title="Citations - Article Finder", layout="wide")


@st.cache_resource
def get_database():
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))


def build_network_data(db: Database, center_paper_id: str = None, depth: int = 2, limit: int = 100):
    """
    Build network graph data for visualization.
    
    Returns:
        nodes: list of {id, label, group, size}
        edges: list of {source, target, type}
    """
    nodes = {}
    edges = []
    
    # Get citations from database
    citations = db.get_all_citations(limit=limit * 5)
    
    if not citations:
        return [], []
    
    # Build node and edge lists
    for cite in citations:
        source_id = cite.get('source_paper_id')
        target_id = cite.get('cited_paper_id')
        
        # Get paper info
        if source_id and source_id not in nodes:
            paper = db.get_paper(source_id)
            if paper:
                title = paper.get('title', 'Unknown')[:50]
                year = paper.get('year', '')
                nodes[source_id] = {
                    'id': source_id,
                    'label': f"{title}... ({year})" if year else title,
                    'title': paper.get('title', 'Unknown'),
                    'year': year,
                    'group': 'corpus',
                    'size': 10
                }
        
        if target_id and target_id not in nodes:
            paper = db.get_paper(target_id)
            if paper:
                title = paper.get('title', 'Unknown')[:50]
                year = paper.get('year', '')
                nodes[target_id] = {
                    'id': target_id,
                    'label': f"{title}... ({year})" if year else title,
                    'title': paper.get('title', 'Unknown'),
                    'year': year,
                    'group': 'corpus',
                    'size': 10
                }
            else:
                # External paper (not in corpus)
                nodes[target_id] = {
                    'id': target_id,
                    'label': cite.get('cited_title', target_id)[:50],
                    'title': cite.get('cited_title', target_id),
                    'year': cite.get('cited_year'),
                    'group': 'external',
                    'size': 5
                }
        
        if source_id and target_id:
            edges.append({
                'source': source_id,
                'target': target_id,
                'type': cite.get('direction', 'cites')
            })
    
    # Calculate node sizes based on citation count
    citation_counts = {}
    for edge in edges:
        target = edge['target']
        citation_counts[target] = citation_counts.get(target, 0) + 1
    
    for node_id, count in citation_counts.items():
        if node_id in nodes:
            nodes[node_id]['size'] = 5 + min(count * 2, 30)
    
    return list(nodes.values())[:limit], edges[:limit * 2]


def render_network_pyvis(nodes: list, edges: list, height: int = 600):
    """Render network using PyVis (if available)."""
    try:
        from pyvis.network import Network
        import tempfile
        
        net = Network(height=f"{height}px", width="100%", bgcolor="#ffffff", font_color="black")
        
        # Add nodes
        for node in nodes:
            color = "#4CAF50" if node['group'] == 'corpus' else "#9E9E9E"
            net.add_node(
                node['id'],
                label=node['label'],
                title=node['title'],
                color=color,
                size=node['size']
            )
        
        # Add edges
        for edge in edges:
            net.add_edge(edge['source'], edge['target'], arrows='to')
        
        # Configure physics
        net.set_options("""
        {
            "physics": {
                "forceAtlas2Based": {
                    "gravitationalConstant": -50,
                    "centralGravity": 0.01,
                    "springLength": 100,
                    "springConstant": 0.08
                },
                "solver": "forceAtlas2Based",
                "stabilization": {"iterations": 100}
            },
            "interaction": {
                "hover": true,
                "navigationButtons": true
            }
        }
        """)
        
        # Save and display
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            net.save_graph(f.name)
            with open(f.name, 'r') as html_file:
                html_content = html_file.read()
            
            st.components.v1.html(html_content, height=height + 50)
        
        return True
    except ImportError:
        return False


def render_network_plotly(nodes: list, edges: list, height: int = 600):
    """Render network using Plotly."""
    try:
        import plotly.graph_objects as go
        import random
        
        # Create positions (simple force-directed approximation)
        positions = {}
        for i, node in enumerate(nodes):
            # Arrange in a circle with some randomness
            angle = (i / len(nodes)) * 2 * 3.14159
            radius = 1 + random.random() * 0.5
            positions[node['id']] = {
                'x': radius * (1 + 0.3 * (hash(node['id']) % 10) / 10) * (1 if i % 2 == 0 else -1) * abs(angle - 3.14),
                'y': radius * (hash(node['id'][::-1]) % 100) / 50 - 1
            }
        
        # Create edge traces
        edge_x = []
        edge_y = []
        for edge in edges:
            if edge['source'] in positions and edge['target'] in positions:
                x0 = positions[edge['source']]['x']
                y0 = positions[edge['source']]['y']
                x1 = positions[edge['target']]['x']
                y1 = positions[edge['target']]['y']
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
        
        edge_trace = go.Scatter(
            x=edge_x, y=edge_y,
            line=dict(width=0.5, color='#888'),
            hoverinfo='none',
            mode='lines'
        )
        
        # Create node traces
        corpus_nodes = [n for n in nodes if n['group'] == 'corpus']
        external_nodes = [n for n in nodes if n['group'] == 'external']
        
        def make_node_trace(node_list, color, name):
            return go.Scatter(
                x=[positions[n['id']]['x'] for n in node_list if n['id'] in positions],
                y=[positions[n['id']]['y'] for n in node_list if n['id'] in positions],
                mode='markers+text',
                name=name,
                hoverinfo='text',
                hovertext=[n['title'] for n in node_list if n['id'] in positions],
                marker=dict(
                    size=[n['size'] for n in node_list if n['id'] in positions],
                    color=color,
                    line=dict(width=1, color='white')
                ),
                textposition='top center',
                textfont=dict(size=8)
            )
        
        corpus_trace = make_node_trace(corpus_nodes, '#4CAF50', 'In Corpus')
        external_trace = make_node_trace(external_nodes, '#9E9E9E', 'External')
        
        fig = go.Figure(
            data=[edge_trace, corpus_trace, external_trace],
            layout=go.Layout(
                showlegend=True,
                hovermode='closest',
                margin=dict(b=20, l=5, r=5, t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                height=height,
                title="Citation Network"
            )
        )
        
        st.plotly_chart(fig, use_container_width=True)
        return True
    except ImportError:
        return False


def render_network_table(nodes: list, edges: list):
    """Fallback: render network as tables."""
    import pandas as pd
    
    st.subheader("Papers in Network")
    
    # Nodes table
    node_df = pd.DataFrame([
        {
            'Title': n['title'][:60] + ('...' if len(n['title']) > 60 else ''),
            'Year': n.get('year', '-'),
            'Type': 'In Corpus' if n['group'] == 'corpus' else 'External',
            'Citations': n['size'] - 5
        }
        for n in sorted(nodes, key=lambda x: x['size'], reverse=True)
    ])
    
    st.dataframe(node_df, use_container_width=True, hide_index=True)
    
    st.subheader("Citation Links")
    
    # Get paper titles for edges
    node_titles = {n['id']: n['title'][:40] for n in nodes}
    
    edge_df = pd.DataFrame([
        {
            'From': node_titles.get(e['source'], e['source'][:20]),
            'To': node_titles.get(e['target'], e['target'][:20]),
            'Type': e.get('type', 'cites')
        }
        for e in edges[:100]
    ])
    
    st.dataframe(edge_df, use_container_width=True, hide_index=True)


def main():
    st.title("🔗 Citation Network")
    
    db = get_database()
    
    # Sidebar controls
    with st.sidebar:
        st.subheader("Network Options")
        
        max_nodes = st.slider("Max nodes", 20, 200, 50)
        
        viz_type = st.radio(
            "Visualization",
            ["Auto", "Interactive (PyVis)", "Static (Plotly)", "Table"],
            index=0
        )
        
        st.divider()
        
        fetch_limit = st.number_input("Fetch limit", min_value=1, max_value=500, value=50)
        
        if st.button("🔄 Fetch New Citations"):
            from search.citation_network import CitationFetcher
            
            email = get('apis.openalex.email')
            if not email or '@' not in email:
                st.error("Missing OpenAlex email. Set apis.openalex.email in config/settings.local.yaml.")
            else:
                st.info("Fetching citations from OpenAlex...")
                
                fetcher = CitationFetcher(db, email=email)
                papers = db.search_papers(limit=10000)
                with_doi = [p for p in papers if p.get('doi')][:fetch_limit]
                
                progress = st.progress(0)
                fetched = 0
                for i, paper in enumerate(with_doi):
                    if i % 5 == 0:
                        progress.progress((i + 1) / max(len(with_doi), 1))
                    try:
                        result = fetcher.fetch_citations_for_paper(paper['paper_id'])
                        if result.get('references_found', 0) > 0 or result.get('citations_found', 0) > 0:
                            fetched += 1
                    except Exception as e:
                        st.warning(f"Fetch failed for {paper.get('doi', 'no-doi')}: {e}")
                
                progress.progress(1.0)
                st.success(f"Fetched citations for {fetched} papers")
    
    # Main content
    tab_network, tab_expand, tab_stats = st.tabs(["📊 Network", "➕ Expansion Queue", "📈 Statistics"])
    
    with tab_network:
        # Build network data
        nodes, edges = build_network_data(db, limit=max_nodes)
        
        if not nodes:
            st.info("No citation data available yet. Import papers and fetch citations first.")
            
            st.markdown("""
            ### How to build the citation network:
            
            1. **Import papers** with DOIs via the Import page
            2. **Fetch citations** for papers (coming soon in UI, use CLI for now):
               ```bash
               python cli/main.py citations --fetch --limit 50
               ```
            3. Return here to visualize the network
            """)
        else:
            st.write(f"Showing {len(nodes)} papers and {len(edges)} citation links")
            
            # Render visualization
            rendered = False
            
            if viz_type == "Auto":
                rendered = render_network_pyvis(nodes, edges)
                if not rendered:
                    rendered = render_network_plotly(nodes, edges)
            elif viz_type == "Interactive (PyVis)":
                rendered = render_network_pyvis(nodes, edges)
                if not rendered:
                    st.warning("PyVis not available. Install: pip install pyvis")
            elif viz_type == "Static (Plotly)":
                rendered = render_network_plotly(nodes, edges)
                if not rendered:
                    st.warning("Plotly not available. Install: pip install plotly")
            
            if not rendered or viz_type == "Table":
                render_network_table(nodes, edges)
    
    with tab_expand:
        st.subheader("Expansion Queue")
        st.caption("Papers discovered through citations that could be added to the corpus")
        
        # Get expansion queue
        try:
            queue = db.get_expansion_queue(limit=50)
            
            if queue:
                import pandas as pd
                
                df = pd.DataFrame([
                    {
                        'Title': q.get('title', '-')[:50],
                        'DOI': q.get('doi', '-'),
                        'Discovered From': q.get('discovered_from', '-')[:20],
                        'Priority': q.get('priority', 0)
                    }
                    for q in queue
                ])
                
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("📥 Add Top 10 to Corpus"):
                        st.info("Adding papers from queue...")
                        # Would add papers here
                
                with col2:
                    if st.button("🗑️ Clear Queue"):
                        st.warning("This would clear the expansion queue")
            else:
                st.info("Expansion queue is empty")
        except Exception as e:
            st.info(f"Expansion queue not yet populated. {e}")
    
    with tab_stats:
        st.subheader("Citation Statistics")
        
        # Get basic stats
        papers = db.search_papers(limit=1000)
        
        if papers:
            with_doi = sum(1 for p in papers if p.get('doi'))
            
            col1, col2, col3, col4 = st.columns(4)
            
            col1.metric("Total Papers", len(papers))
            col2.metric("With DOI", with_doi)
            col3.metric("Citation Links", len(edges))
            col4.metric("In Network", len(nodes))
            
            # Most cited papers
            st.divider()
            st.subheader("Most Connected Papers")
            
            if nodes:
                import pandas as pd
                
                top_cited = sorted(nodes, key=lambda x: x['size'], reverse=True)[:10]
                
                df = pd.DataFrame([
                    {
                        'Title': n['title'][:60],
                        'Year': n.get('year', '-'),
                        'Links': n['size'] - 5,
                        'Type': 'In Corpus' if n['group'] == 'corpus' else 'External'
                    }
                    for n in top_cited
                ])
                
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No papers in corpus yet")


if __name__ == "__main__":
    main()
