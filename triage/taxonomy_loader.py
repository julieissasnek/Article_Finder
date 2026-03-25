# Version: 3.2.5
"""
Article Finder v3.2.5 - Taxonomy Loader and Centroid Builder
Loads taxonomy from YAML and builds embedding centroids for each node.

v3.2.5 additions:
- get_theories(): Get all theory nodes
- get_neural_outcomes(): Get all neural outcome nodes
- get_nodes_by_facet(): Get nodes filtered by facet
- get_seeds_for_node(): Get seed phrases for a specific node
"""

import pickle
from pathlib import Path
from typing import Optional, Dict, Any, List
import numpy as np
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from triage.embeddings import EmbeddingService, get_embedding_service


TAXONOMY_FILE = Path(__file__).parent.parent / 'config' / 'taxonomy.yaml'


class TaxonomyLoader:
    """Load and manage the multi-facet taxonomy."""
    
    def __init__(self, database: Database):
        self.db = database
        self._taxonomy: Optional[Dict] = None
    
    def load_from_yaml(self, filepath: Optional[Path] = None) -> Dict:
        """Load taxonomy from YAML file."""
        filepath = filepath or TAXONOMY_FILE
        
        with open(filepath) as f:
            self._taxonomy = yaml.safe_load(f)
        
        return self._taxonomy
    
    def load_into_database(self, filepath: Optional[Path] = None) -> Dict[str, int]:
        """
        Load taxonomy into database tables.
        
        Returns counts of loaded facets and nodes.
        """
        taxonomy = self.load_from_yaml(filepath)
        
        stats = {
            'facets': 0,
            'nodes': 0
        }
        
        # Load facet definitions
        for facet in taxonomy.get('facets', []):
            self.db.load_taxonomy({'facets': [facet]})
            stats['facets'] += 1
        
        # Load each facet tree
        facet_keys = [
            'environmental_factors', 'outcomes', 'subjects', 'settings',
            'methodology', 'modality', 'cross_modal', 'theory', 'evidence_strength'
        ]
        
        for facet_key in facet_keys:
            if facet_key in taxonomy:
                nodes = taxonomy[facet_key]
                node_count = self._count_nodes(nodes)
                self.db.load_taxonomy({facet_key: nodes})
                stats['nodes'] += node_count
        
        return stats
    
    def _count_nodes(self, nodes: List[Dict]) -> int:
        """Recursively count nodes in a tree."""
        count = 0
        for node in nodes:
            count += 1
            if 'children' in node:
                count += self._count_nodes(node['children'])
        return count
    
    def get_all_nodes(self) -> List[Dict]:
        """Get all taxonomy nodes from database."""
        return self.db.get_taxonomy_nodes()
    
    def get_nodes_with_seeds(self) -> List[Dict]:
        """Get all nodes that have seed texts defined."""
        nodes = self.get_all_nodes()
        return [n for n in nodes if n.get('seeds')]

    # =========================================================================
    # v3.2.5: New methods for targeted access to taxonomy content
    # =========================================================================

    def get_theories(self) -> List[Dict]:
        """
        Get all theory nodes from taxonomy.

        Returns list of theory nodes with their seeds.
        """
        if self._taxonomy is None:
            self.load_from_yaml()

        theories = []
        theory_data = self._taxonomy.get('theory', [])

        for theory_group in theory_data:
            theories.append({
                'id': theory_group.get('id', ''),
                'name': theory_group.get('name', ''),
                'level': theory_group.get('level', 1),
                'seeds': theory_group.get('seeds', [])
            })
            # Include level-2 theories
            for child in theory_group.get('children', []):
                theories.append({
                    'id': child.get('id', ''),
                    'name': child.get('name', ''),
                    'level': child.get('level', 2),
                    'seeds': child.get('seeds', []),
                    'parent_id': theory_group.get('id', '')
                })

        return theories

    def get_neural_outcomes(self) -> List[Dict]:
        """
        Get all neural outcome nodes from taxonomy.

        Returns list of neural outcome nodes (EEG, fMRI markers, etc.)
        """
        if self._taxonomy is None:
            self.load_from_yaml()

        neural = []
        outcomes = self._taxonomy.get('outcomes', [])

        def find_neural(nodes, parent_id=None):
            for node in nodes:
                node_id = node.get('id', '')
                if 'neural' in node_id.lower():
                    neural.append({
                        'id': node_id,
                        'name': node.get('name', ''),
                        'level': node.get('level', 1),
                        'seeds': node.get('seeds', []),
                        'parent_id': parent_id
                    })
                    # Get children too
                    for child in node.get('children', []):
                        neural.append({
                            'id': child.get('id', ''),
                            'name': child.get('name', ''),
                            'level': child.get('level', 2),
                            'seeds': child.get('seeds', []),
                            'parent_id': node_id
                        })
                        # Level 3 children
                        for grandchild in child.get('children', []):
                            neural.append({
                                'id': grandchild.get('id', ''),
                                'name': grandchild.get('name', ''),
                                'level': grandchild.get('level', 3),
                                'seeds': grandchild.get('seeds', []),
                                'parent_id': child.get('id', '')
                            })
                else:
                    # Check children
                    find_neural(node.get('children', []), node_id)

        find_neural(outcomes)
        return neural

    def get_nodes_by_facet(self, facet_key: str, max_level: int = 3) -> List[Dict]:
        """
        Get all nodes from a specific facet.

        Args:
            facet_key: One of 'environmental_factors', 'outcomes', 'theory', etc.
            max_level: Maximum depth to include (1, 2, or 3)

        Returns:
            List of nodes from that facet
        """
        if self._taxonomy is None:
            self.load_from_yaml()

        nodes = []
        facet_data = self._taxonomy.get(facet_key, [])

        def extract_nodes(items, current_level=1):
            for item in items:
                if current_level <= max_level:
                    nodes.append({
                        'id': item.get('id', ''),
                        'name': item.get('name', ''),
                        'level': item.get('level', current_level),
                        'seeds': item.get('seeds', [])
                    })
                    if 'children' in item:
                        extract_nodes(item['children'], current_level + 1)

        extract_nodes(facet_data)
        return nodes

    def get_seeds_for_node(self, node_id: str) -> List[str]:
        """
        Get seed phrases for a specific taxonomy node.

        Args:
            node_id: The node ID (e.g., 'env.luminous.daylight')

        Returns:
            List of seed phrases, or empty list if not found
        """
        if self._taxonomy is None:
            self.load_from_yaml()

        # Search all facets
        facet_keys = [
            'environmental_factors', 'outcomes', 'subjects', 'settings',
            'methodology', 'modality', 'cross_modal', 'theory', 'evidence_strength'
        ]

        for facet_key in facet_keys:
            facet_data = self._taxonomy.get(facet_key, [])
            seeds = self._find_seeds_recursive(facet_data, node_id)
            if seeds is not None:
                return seeds

        return []

    def _find_seeds_recursive(self, nodes: List, target_id: str) -> Optional[List[str]]:
        """Recursively search for seeds of a node."""
        for node in nodes:
            if node.get('id') == target_id:
                return node.get('seeds', [])
            if 'children' in node:
                result = self._find_seeds_recursive(node['children'], target_id)
                if result is not None:
                    return result
        return None

    def get_environmental_factors(self, max_level: int = 2) -> List[Dict]:
        """Convenience method to get environmental factor nodes."""
        return self.get_nodes_by_facet('environmental_factors', max_level)

    def get_outcomes(self, max_level: int = 2) -> List[Dict]:
        """Convenience method to get outcome nodes."""
        return self.get_nodes_by_facet('outcomes', max_level)

    def get_taxonomy_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the taxonomy structure.

        Useful for understanding coverage and structure.
        """
        if self._taxonomy is None:
            self.load_from_yaml()

        summary = {
            'facets': {},
            'total_nodes': 0,
            'nodes_with_seeds': 0
        }

        facet_keys = [
            'environmental_factors', 'outcomes', 'subjects', 'settings',
            'methodology', 'modality', 'cross_modal', 'theory', 'evidence_strength'
        ]

        for facet_key in facet_keys:
            nodes = self.get_nodes_by_facet(facet_key, max_level=3)
            nodes_with_seeds = [n for n in nodes if n.get('seeds')]

            summary['facets'][facet_key] = {
                'total_nodes': len(nodes),
                'nodes_with_seeds': len(nodes_with_seeds)
            }
            summary['total_nodes'] += len(nodes)
            summary['nodes_with_seeds'] += len(nodes_with_seeds)

        # Specific counts for key areas
        summary['n_theories'] = len(self.get_theories())
        summary['n_neural_outcomes'] = len(self.get_neural_outcomes())

        return summary


class CentroidBuilder:
    """Build embedding centroids for taxonomy nodes."""
    
    def __init__(
        self,
        database: Database,
        embedding_service: Optional[EmbeddingService] = None
    ):
        self.db = database
        self.embeddings = embedding_service or get_embedding_service()
    
    def build_all_centroids(
        self,
        progress_callback=None,
        auto_score_deferred: bool = True
    ) -> Dict[str, Any]:
        """
        Build centroids for all taxonomy nodes with seeds.

        Args:
            progress_callback: Function(current, total) for progress updates
            auto_score_deferred: If True, automatically score papers that were
                                 deferred due to missing centroids

        Returns stats about the build process.
        """
        loader = TaxonomyLoader(self.db)
        nodes = loader.get_nodes_with_seeds()

        # Check if centroids existed before building
        existing_centroids = self.get_all_centroids()
        had_no_centroids = len(existing_centroids) == 0

        stats = {
            'total_nodes': len(nodes),
            'centroids_built': 0,
            'nodes_without_seeds': 0,
            'errors': [],
            'deferred_scoring': None
        }

        print(f"Building centroids for {len(nodes)} nodes...")

        for i, node in enumerate(nodes):
            if progress_callback:
                progress_callback(i + 1, len(nodes))

            try:
                self.build_centroid(node)
                stats['centroids_built'] += 1
            except Exception as e:
                stats['errors'].append(f"{node['node_id']}: {e}")

            if (i + 1) % 20 == 0:
                print(f"  Progress: {i + 1}/{len(nodes)}")

        # Auto-score deferred papers if centroids were just created
        if auto_score_deferred and stats['centroids_built'] > 0:
            # Check if there are deferred papers to score
            deferred_papers = self.db.get_papers_by_status('pending_scorer')
            if deferred_papers:
                print(f"\nFound {len(deferred_papers)} papers deferred due to missing scorer.")
                print("Auto-scoring deferred papers...")

                # Import here to avoid circular imports
                from triage.scorer import HierarchicalScorer
                scorer = HierarchicalScorer(self.db, self.embeddings)
                deferred_stats = scorer.score_deferred_papers()
                stats['deferred_scoring'] = deferred_stats

        return stats
    
    def build_centroid(self, node: Dict) -> np.ndarray:
        """
        Build centroid for a single node from its seed texts.
        
        The centroid is the mean of seed text embeddings.
        """
        seeds = node.get('seeds', [])
        if not seeds:
            raise ValueError(f"Node {node['node_id']} has no seeds")
        
        # Embed all seed texts
        embeddings = self.embeddings.embed(seeds)
        
        # Compute centroid (mean)
        centroid = np.mean(embeddings, axis=0)
        
        # Normalize
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        
        # Store in database
        self._store_centroid(node['node_id'], centroid)
        
        return centroid
    
    def _store_centroid(self, node_id: str, centroid: np.ndarray) -> None:
        """Store centroid in database."""
        with self.db.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO node_centroids 
                   (node_id, embedding, embedding_model, computed_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (node_id, centroid.tobytes(), self.embeddings.model_name)
            )
    
    def get_centroid(self, node_id: str) -> Optional[np.ndarray]:
        """Get centroid for a node."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT embedding FROM node_centroids WHERE node_id = ?",
                (node_id,)
            ).fetchone()
            
            if row and row['embedding']:
                return np.frombuffer(row['embedding'], dtype=np.float32)
        return None
    
    def get_all_centroids(self) -> Dict[str, np.ndarray]:
        """Get all centroids as a dictionary."""
        centroids = {}
        
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT node_id, embedding FROM node_centroids"
            ).fetchall()
            
            for row in rows:
                if row['embedding']:
                    centroids[row['node_id']] = np.frombuffer(
                        row['embedding'], dtype=np.float32
                    )
        
        return centroids
    
    def rebuild_for_node(self, node_id: str) -> np.ndarray:
        """Rebuild centroid for a specific node."""
        node = self.db.get_node(node_id)
        if not node:
            raise ValueError(f"Node not found: {node_id}")
        return self.build_centroid(node)


# CLI
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Load taxonomy and build centroids')
    parser.add_argument('--db', type=Path, default='data/article_finder.db')
    parser.add_argument('--taxonomy', type=Path, default=TAXONOMY_FILE)
    parser.add_argument('--load', action='store_true', help='Load taxonomy into database')
    parser.add_argument('--build', action='store_true', help='Build centroids')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    
    args = parser.parse_args()
    
    # Ensure directories
    args.db.parent.mkdir(parents=True, exist_ok=True)
    
    db = Database(args.db)
    
    if args.load:
        print(f"Loading taxonomy from {args.taxonomy}...")
        loader = TaxonomyLoader(db)
        stats = loader.load_into_database(args.taxonomy)
        print(f"Loaded {stats['facets']} facets and {stats['nodes']} nodes")
    
    if args.build:
        print("Building centroids...")
        builder = CentroidBuilder(db)
        stats = builder.build_all_centroids()
        print(f"\nBuild complete:")
        print(f"  Centroids built: {stats['centroids_built']}")
        if stats['errors']:
            print(f"  Errors: {len(stats['errors'])}")
            for err in stats['errors'][:5]:
                print(f"    - {err}")
    
    if args.stats:
        loader = TaxonomyLoader(db)
        nodes = loader.get_all_nodes()
        nodes_with_seeds = loader.get_nodes_with_seeds()
        
        builder = CentroidBuilder(db)
        centroids = builder.get_all_centroids()
        
        print("\nTaxonomy Statistics:")
        print(f"  Total nodes: {len(nodes)}")
        print(f"  Nodes with seeds: {len(nodes_with_seeds)}")
        print(f"  Centroids computed: {len(centroids)}")
        
        # Count by facet
        facet_counts = {}
        for node in nodes:
            facet = node.get('facet_id', 'unknown')
            facet_counts[facet] = facet_counts.get(facet, 0) + 1
        
        print("\nNodes by facet:")
        for facet, count in sorted(facet_counts.items()):
            print(f"  {facet}: {count}")
