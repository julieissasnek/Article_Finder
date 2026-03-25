# Version: 3.2.2
"""
Article Finder v3 - Hierarchical Scorer
Scores papers against the multi-facet taxonomy and assigns triage decisions.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from triage.embeddings import EmbeddingService, get_embedding_service
from triage.taxonomy_loader import CentroidBuilder
from config.loader import get


class HierarchicalScorer:
    """
    Score papers against the multi-facet taxonomy.
    
    Uses embedding similarity to classify papers across all facet trees.
    """
    
    def __init__(
        self,
        database: Database,
        embedding_service: Optional[EmbeddingService] = None
    ):
        self.db = database
        self.embeddings = embedding_service or get_embedding_service()
        self.centroid_builder = CentroidBuilder(database, self.embeddings)
        
        # Thresholds from config
        self.send_threshold = get('triage.send_to_eater_threshold', 0.70)
        self.review_threshold = get('triage.review_threshold', 0.40)
        self.min_score = get('classification.min_score_to_store', 0.25)
        self.top_k = get('classification.top_k_per_facet', 5)
        
        # Cache centroids
        self._centroids: Optional[Dict[str, np.ndarray]] = None
        self._node_facets: Optional[Dict[str, str]] = None
    
    def _ensure_centroids(self):
        """Load centroids if not cached."""
        if self._centroids is None:
            self._centroids = self.centroid_builder.get_all_centroids()
            
            # Build node->facet mapping
            nodes = self.db.get_taxonomy_nodes()
            self._node_facets = {n['node_id']: n['facet_id'] for n in nodes}
    
    def score_paper(self, paper: Dict) -> Dict[str, Any]:
        """
        Score a single paper against all taxonomy nodes.
        
        Returns dict with:
            - node_scores: {node_id: score}
            - top_nodes: [(node_id, score), ...]
            - facet_scores: {facet_id: max_score}
            - triage_score: overall relevance score
            - triage_decision: send_to_eater|review|reject
            - triage_reasons: [list of top matching concepts]
        """
        self._ensure_centroids()
        
        if not self._centroids:
            raise ValueError("No centroids available. Run centroid builder first.")
        
        # Embed paper
        title = paper.get('title', '')
        abstract = paper.get('abstract', '')
        paper_embedding = self.embeddings.embed_paper(title, abstract)
        
        # Score against all nodes
        node_scores = {}
        for node_id, centroid in self._centroids.items():
            score = self.embeddings.similarity(paper_embedding, centroid)
            if score >= self.min_score:
                node_scores[node_id] = float(score)
        
        # Get top nodes overall
        sorted_scores = sorted(node_scores.items(), key=lambda x: x[1], reverse=True)
        top_nodes = sorted_scores[:20]
        
        # Aggregate by facet (max score per facet)
        facet_scores = {}
        for node_id, score in node_scores.items():
            facet = self._node_facets.get(node_id, 'unknown')
            if facet not in facet_scores or score > facet_scores[facet]:
                facet_scores[facet] = score
        
        # Compute triage score
        # Weight: environmental_factors and outcomes are most important
        priority_facets = ['environmental_factors', 'outcomes']
        other_facets = [f for f in facet_scores if f not in priority_facets]
        
        priority_scores = [facet_scores.get(f, 0) for f in priority_facets]
        other_scores = [facet_scores.get(f, 0) for f in other_facets]
        
        if priority_scores:
            triage_score = 0.7 * np.mean(priority_scores) + 0.3 * np.mean(other_scores or [0])
        else:
            triage_score = np.mean(list(facet_scores.values())) if facet_scores else 0.0
        
        # Make triage decision
        if triage_score >= self.send_threshold:
            triage_decision = 'send_to_eater'
        elif triage_score >= self.review_threshold:
            triage_decision = 'review'
        else:
            triage_decision = 'reject'
        
        # Extract reasons (top node names)
        triage_reasons = []
        for node_id, score in top_nodes[:5]:
            node = self.db.get_node(node_id)
            if node:
                triage_reasons.append(f"{node['name']} ({score:.2f})")
        
        return {
            'node_scores': node_scores,
            'top_nodes': top_nodes,
            'facet_scores': facet_scores,
            'triage_score': float(triage_score),
            'triage_decision': triage_decision,
            'triage_reasons': triage_reasons
        }
    
    def score_and_store(self, paper: Dict) -> Dict[str, Any]:
        """Score a paper and store results in database."""
        result = self.score_paper(paper)
        paper_id = paper['paper_id']
        
        # Store node scores
        for node_id, score in result['node_scores'].items():
            self.db.set_paper_facet_score(paper_id, node_id, score, method='embedding')
        
        # Update paper with triage info
        paper['triage_score'] = result['triage_score']
        paper['triage_decision'] = result['triage_decision']
        paper['triage_reasons'] = result['triage_reasons']
        paper['updated_at'] = datetime.utcnow().isoformat()
        
        self.db.add_paper(paper)
        
        return result
    
    def score_all_papers(
        self,
        status_filter: Optional[str] = None,
        force: bool = False,
        limit: Optional[int] = None,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Score all papers in corpus.
        
        Args:
            status_filter: Only score papers with this status
            force: Re-score papers that already have scores
            limit: Maximum papers to score
            progress_callback: Function(current, total) for progress
        """
        self._ensure_centroids()
        
        stats = {
            'total': 0,
            'scored': 0,
            'skipped': 0,
            'errors': [],
            'by_decision': {
                'send_to_eater': 0,
                'review': 0,
                'reject': 0
            }
        }
        
        # Get papers
        if status_filter:
            papers = self.db.get_papers_by_status(status_filter)
        else:
            papers = self.db.search_papers(limit=10000)
        
        # Filter papers needing scoring
        if not force:
            papers = [p for p in papers if p.get('triage_score') is None]
        
        # Only score papers with abstracts (better quality)
        papers_with_text = [p for p in papers if p.get('abstract') or p.get('title')]
        
        if limit:
            papers_with_text = papers_with_text[:limit]
        
        stats['total'] = len(papers_with_text)
        
        print(f"Scoring {len(papers_with_text)} papers...")
        
        for i, paper in enumerate(papers_with_text):
            if progress_callback:
                progress_callback(i + 1, len(papers_with_text))
            
            try:
                result = self.score_and_store(paper)
                stats['scored'] += 1
                stats['by_decision'][result['triage_decision']] += 1
                
            except Exception as e:
                stats['errors'].append(f"{paper.get('paper_id')}: {e}")
            
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i + 1}/{len(papers_with_text)}")
        
        return stats

    def score_deferred_papers(self, progress_callback=None) -> Dict[str, Any]:
        """
        Score papers that were deferred due to scorer unavailability.

        This method finds all papers with status='pending_scorer' and scores them.
        Papers are then updated with proper triage scores and moved to appropriate status.

        Returns:
            Dict with scoring statistics
        """
        self._ensure_centroids()

        if not self._centroids:
            return {
                'total': 0,
                'scored': 0,
                'errors': ['No centroids available - cannot score deferred papers']
            }

        stats = {
            'total': 0,
            'scored': 0,
            'rejected': 0,
            'promoted': 0,
            'errors': [],
            'by_decision': {
                'send_to_eater': 0,
                'review': 0,
                'reject': 0
            }
        }

        # Get papers that were deferred
        papers = self.db.get_papers_by_status('pending_scorer')
        stats['total'] = len(papers)

        if not papers:
            return stats

        print(f"Scoring {len(papers)} deferred papers...")

        for i, paper in enumerate(papers):
            if progress_callback:
                progress_callback(i + 1, len(papers))

            try:
                result = self.score_paper(paper)

                # Update paper with triage info
                paper['triage_score'] = result['triage_score']
                paper['triage_decision'] = result['triage_decision']
                paper['triage_reasons'] = result.get('triage_reasons', [])

                # Update status based on decision
                if result['triage_decision'] == 'reject':
                    paper['status'] = 'rejected'
                    stats['rejected'] += 1
                else:
                    paper['status'] = 'candidate'
                    stats['promoted'] += 1

                # Store node scores
                for node_id, score in result['node_scores'].items():
                    self.db.set_paper_facet_score(paper['paper_id'], node_id, score, method='embedding')

                # Update paper in database
                self.db.add_paper(paper)

                stats['scored'] += 1
                stats['by_decision'][result['triage_decision']] += 1

            except Exception as e:
                stats['errors'].append(f"{paper.get('paper_id')}: {e}")

            if (i + 1) % 50 == 0:
                print(f"  Progress: {i + 1}/{len(papers)}")

        print(f"Deferred scoring complete: {stats['promoted']} promoted, {stats['rejected']} rejected")
        return stats

    def get_paper_classification(self, paper_id: str) -> Dict[str, Any]:
        """Get stored classification for a paper."""
        scores = self.db.get_paper_facet_scores(paper_id)
        
        if not scores:
            return {'node_scores': {}, 'top_nodes': [], 'facet_scores': {}}
        
        # Aggregate
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        facet_scores = {}
        for node_id, score in scores.items():
            facet = self._node_facets.get(node_id, 'unknown') if self._node_facets else 'unknown'
            if facet not in facet_scores or score > facet_scores[facet]:
                facet_scores[facet] = score
        
        return {
            'node_scores': scores,
            'top_nodes': sorted_scores[:20],
            'facet_scores': facet_scores
        }
    
    def find_similar_papers(
        self,
        paper_id: str,
        limit: int = 10
    ) -> List[Tuple[str, float]]:
        """Find papers with similar classification profiles."""
        target_scores = self.db.get_paper_facet_scores(paper_id)
        
        if not target_scores:
            return []
        
        # Get all papers with scores
        all_papers = self.db.search_papers(limit=10000)
        
        similarities = []
        for paper in all_papers:
            if paper['paper_id'] == paper_id:
                continue
            
            other_scores = self.db.get_paper_facet_scores(paper['paper_id'])
            if not other_scores:
                continue
            
            # Compute similarity (Jaccard-like over shared nodes)
            shared_nodes = set(target_scores.keys()) & set(other_scores.keys())
            if not shared_nodes:
                continue
            
            # Weighted overlap
            sim = sum(
                min(target_scores[n], other_scores[n])
                for n in shared_nodes
            ) / max(
                sum(target_scores.values()),
                sum(other_scores.values())
            )
            
            similarities.append((paper['paper_id'], sim))
        
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]


def get_triage_report(db: Database) -> Dict[str, Any]:
    """Generate a triage summary report."""
    papers = db.search_papers(limit=10000)
    
    report = {
        'total': len(papers),
        'with_scores': 0,
        'by_decision': {
            'send_to_eater': 0,
            'review': 0,
            'reject': 0,
            'unscored': 0
        },
        'score_distribution': {
            '0.0-0.2': 0,
            '0.2-0.4': 0,
            '0.4-0.6': 0,
            '0.6-0.8': 0,
            '0.8-1.0': 0
        }
    }
    
    for paper in papers:
        score = paper.get('triage_score')
        decision = paper.get('triage_decision')
        
        if score is not None:
            report['with_scores'] += 1
            
            # Score distribution
            if score < 0.2:
                report['score_distribution']['0.0-0.2'] += 1
            elif score < 0.4:
                report['score_distribution']['0.2-0.4'] += 1
            elif score < 0.6:
                report['score_distribution']['0.4-0.6'] += 1
            elif score < 0.8:
                report['score_distribution']['0.6-0.8'] += 1
            else:
                report['score_distribution']['0.8-1.0'] += 1
        
        if decision:
            report['by_decision'][decision] = report['by_decision'].get(decision, 0) + 1
        else:
            report['by_decision']['unscored'] += 1
    
    return report


# CLI
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Score papers against taxonomy')
    parser.add_argument('--db', type=Path, default='data/article_finder.db')
    parser.add_argument('--score-all', action='store_true', help='Score all papers')
    parser.add_argument('--force', action='store_true', help='Re-score papers')
    parser.add_argument('--limit', type=int, help='Max papers to score')
    parser.add_argument('--status', help='Only score papers with this status')
    parser.add_argument('--report', action='store_true', help='Show triage report')
    parser.add_argument('--paper', help='Score single paper by ID')
    
    args = parser.parse_args()
    
    db = Database(args.db)
    scorer = HierarchicalScorer(db)
    
    if args.report:
        report = get_triage_report(db)
        print("\nTriage Report:")
        print(f"  Total papers: {report['total']}")
        print(f"  With scores: {report['with_scores']}")
        print("\nBy decision:")
        for decision, count in report['by_decision'].items():
            print(f"  {decision}: {count}")
        print("\nScore distribution:")
        for bucket, count in report['score_distribution'].items():
            print(f"  {bucket}: {count}")
    
    elif args.paper:
        paper = db.get_paper(args.paper)
        if not paper:
            print(f"Paper not found: {args.paper}")
        else:
            result = scorer.score_and_store(paper)
            print(f"\nPaper: {paper.get('title', 'Unknown')[:60]}...")
            print(f"Triage score: {result['triage_score']:.3f}")
            print(f"Decision: {result['triage_decision']}")
            print("\nTop classifications:")
            for node_id, score in result['top_nodes'][:10]:
                node = db.get_node(node_id)
                name = node['name'] if node else node_id
                print(f"  {score:.3f}: {name}")
    
    elif args.score_all:
        print("Scoring papers...")
        stats = scorer.score_all_papers(
            status_filter=args.status,
            force=args.force,
            limit=args.limit
        )
        
        print(f"\nScoring complete:")
        print(f"  Total: {stats['total']}")
        print(f"  Scored: {stats['scored']}")
        print(f"\nBy decision:")
        for decision, count in stats['by_decision'].items():
            print(f"  {decision}: {count}")
        
        if stats['errors']:
            print(f"\nErrors ({len(stats['errors'])}):")
            for err in stats['errors'][:5]:
                print(f"  - {err}")
    
    else:
        parser.print_help()
