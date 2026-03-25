# Version: 3.2.2
"""
Article Finder v3 - Triage Queue Page
Review and approve/reject papers for Article Eater processing.
"""

import streamlit as st
import os
import time
import threading
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import Database
from config.loader import get

st.set_page_config(page_title="Triage Queue - Article Finder", layout="wide")


@st.cache_resource
def get_database():
    db_path = get('paths.database', 'data/article_finder.db')
    return Database(Path(db_path))



@st.cache_resource
def get_pipeline():
    """Create a cached ArticleFinderPipeline for batch processing."""
    from eater_interface.pipeline import ArticleFinderPipeline, PipelineConfig

    base_dir = Path(__file__).parent.parent.parent
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

def format_authors(authors):
    """Format authors list for display."""
    if not authors:
        return "Unknown"
    if isinstance(authors, str):
        return authors
    if isinstance(authors, list):
        names = [a.get('name', str(a)) if isinstance(a, dict) else str(a) for a in authors[:3]]
        if len(authors) > 3:
            names.append(f"et al.")
        return ", ".join(names)
    return str(authors)


def main():
    st.title("📋 Triage Queue")
    
    db = get_database()
    
    # Get queue counts
    review_papers = db.get_papers_by_status('review')
    candidate_papers = db.get_papers_by_status('candidate')
    send_papers = db.get_papers_by_status('send_to_eater')
    
    # Tabs for different queues
    tab1, tab2, tab3 = st.tabs([
        f"Review ({len(review_papers)})",
        f"Candidates ({len(candidate_papers)})",
        f"Approved ({len(send_papers)})"
    ])
    
    with tab1:
        st.subheader("Papers Needing Review")
        st.caption("Papers with triage scores between 0.4 and 0.7")
        
        if not review_papers:
            st.info("No papers in review queue.")
        else:
            for paper in review_papers[:20]:
                render_paper_card(db, paper, ['send_to_eater', 'reject'])
    
    with tab2:
        st.subheader("Unscored Candidates")
        st.caption("Papers that haven't been classified yet")
        
        if not candidate_papers:
            st.info("No unscored candidates.")
        else:
            # Filter to those with abstracts (scoreable)
            scoreable = [p for p in candidate_papers if p.get('abstract')]
            unscoreable = [p for p in candidate_papers if not p.get('abstract')]
            
            st.write(f"With abstracts: {len(scoreable)} | Missing abstracts: {len(unscoreable)}")
            
            if st.button("Score All Candidates"):
                with st.spinner("Scoring papers..."):
                    try:
                        from triage.scorer import HierarchicalScorer
                        scorer = HierarchicalScorer(db)
                        stats = scorer.score_all_papers(status_filter='candidate', limit=100)
                        st.success(f"Scored {stats['scored']} papers!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error scoring: {e}")
            
            for paper in scoreable[:20]:
                render_paper_card(db, paper, ['send_to_eater', 'review', 'reject'])
    
    with tab3:
        st.subheader("Approved for Article Eater")
        st.caption("Papers ready to be processed")
        
        if not send_papers:
            st.info("No papers approved for processing.")
        else:
            # Show count and option to build job bundles
            st.write(f"{len(send_papers)} papers ready for Article Eater")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Build Job Bundles"):
                    st.info("Job bundle building coming soon...")
            
            with col2:
                if st.button("Clear Approved Queue"):
                    if st.session_state.get('confirm_clear'):
                        for paper in send_papers:
                            paper['status'] = 'candidate'
                            paper['triage_decision'] = None
                            paper['triage_score'] = None
                            db.add_paper(paper)
                        st.success("Queue cleared!")
                        st.session_state.confirm_clear = False
                        st.rerun()
                    else:
                        st.session_state.confirm_clear = True
                        st.warning("Click again to confirm")
            
            st.divider()
            st.subheader("Batch Process with Article Eater")
            st.caption("Run continuously until you stop it. Uses local LLM.")

            if "batch_running" not in st.session_state:
                st.session_state.batch_running = False
            if "batch_progress" not in st.session_state:
                st.session_state.batch_progress = {}
            if "last_action_ts" not in st.session_state:
                st.session_state.last_action_ts = time.time()

            idle_prompt = st.checkbox("Enable idle/late prompt", value=True)
            late_hour = st.number_input("Late-hour prompt (24h)", min_value=0, max_value=23, value=22, step=1)

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                max_papers = st.number_input("Max papers (0 = no limit)", min_value=0, value=0, step=1)
            with col_b:
                idle_sleep = st.number_input("Idle sleep seconds", min_value=5, value=30, step=5)
            with col_c:
                profile = st.selectbox("Profile", ["standard", "fast", "deep"], index=0)

            def _start_batch():
                if st.session_state.batch_running:
                    return
                st.session_state.batch_running = True
                st.session_state.batch_stop = threading.Event()
                st.session_state.batch_progress = {"state": "starting"}

                def _worker():
                    try:
                        pipeline = get_pipeline()
                        os.environ.setdefault("AE_LLM_MODEL", "ollama:mistral")
                        os.environ.setdefault("OLLAMA_BASE", "http://localhost:11434")

                        max_papers_val = None if max_papers == 0 else int(max_papers)
                        result = pipeline.run_eater_batch(
                            status_filter="send_to_eater",
                            max_papers=max_papers_val,
                            time_budget_seconds=None,
                            profile=profile,
                            progress_callback=lambda info: st.session_state.update(batch_progress=info),
                            continuous=True,
                            idle_sleep_seconds=int(idle_sleep),
                            stop_event=st.session_state.batch_stop
                        )
                        st.session_state.batch_result = result
                    finally:
                        st.session_state.batch_running = False

                thread = threading.Thread(target=_worker, daemon=True)
                st.session_state.batch_thread = thread
                thread.start()

            col_run, col_stop = st.columns(2)
            with col_run:
                if st.button("▶ Start Continuous Batch"):
                    st.session_state.last_action_ts = time.time()
                    _start_batch()
            with col_stop:
                if st.button("■ Stop Batch"):
                    st.session_state.last_action_ts = time.time()
                    if st.session_state.get("batch_stop"):
                        st.session_state.batch_stop.set()

            progress = st.session_state.get("batch_progress", {})
            state = progress.get("state", "idle")
            processed = progress.get("processed", 0)
            elapsed = int(progress.get("elapsed_seconds", 0))
            remaining = progress.get("remaining_seconds")
            remaining_str = f"{int(remaining)}s" if remaining is not None else "n/a"
            st.info(f"State: {state} | Processed: {processed} | Elapsed: {elapsed}s | Remaining: {remaining_str}")
            st.caption("Refresh this page to update progress if it appears stale.")

            now = datetime.now()
            idle_seconds = time.time() - st.session_state.last_action_ts
            if idle_prompt and not st.session_state.batch_running:
                if idle_seconds >= 300 or now.hour >= int(late_hour):
                    st.warning("You've been idle or it's late. Start a continuous batch run?")
                    if st.button("Start Batch Now"):
                        st.session_state.last_action_ts = time.time()
                        _start_batch()

            for paper in send_papers[:20]:
                render_paper_card(db, paper, ['reject'], show_actions=False)


def render_paper_card(db, paper, action_options, show_actions=True):
    """Render a paper card with actions."""
    
    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            # Title
            title = paper.get('title', 'Untitled')
            doi = paper.get('doi')
            
            if doi:
                st.markdown(f"**[{title}](https://doi.org/{doi})**")
            else:
                st.markdown(f"**{title}**")
            
            # Metadata
            authors = format_authors(paper.get('authors'))
            year = paper.get('year', 'N/A')
            venue = paper.get('venue', '')
            
            st.caption(f"{authors} • {year} • {venue}")
            
            # Triage reasons
            reasons = paper.get('triage_reasons', [])
            if reasons:
                if isinstance(reasons, str):
                    reasons = [reasons]
                st.caption(f"Tags: {', '.join(reasons[:5])}")
        
        with col2:
            # Score
            score = paper.get('triage_score')
            if score is not None:
                color = 'normal'
                if score >= 0.7:
                    color = 'normal'  # Would be green
                elif score >= 0.4:
                    color = 'normal'  # Would be yellow
                else:
                    color = 'off'
                st.metric("Score", f"{score:.2f}")
        
        with col3:
            # Actions
            if show_actions:
                paper_id = paper['paper_id']
                
                for action in action_options:
                    button_label = {
                        'send_to_eater': '✅ Approve',
                        'review': '🔍 Review',
                        'reject': '❌ Reject'
                    }.get(action, action)
                    
                    button_type = 'primary' if action == 'send_to_eater' else 'secondary'
                    
                    if st.button(button_label, key=f"{action}_{paper_id}", type=button_type):
                        paper['status'] = action if action in ['reject'] else 'queued_for_eater' if action == 'send_to_eater' else action
                        paper['triage_decision'] = action
                        paper['updated_at'] = datetime.utcnow().isoformat()
                        db.add_paper(paper)
                        st.rerun()
        
        # Abstract preview
        abstract = paper.get('abstract', '')
        if abstract:
            with st.expander("Abstract"):
                st.write(abstract[:400] + "..." if len(abstract) > 400 else abstract)
        
        st.divider()


if __name__ == "__main__":
    main()
