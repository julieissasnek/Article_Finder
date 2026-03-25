# Version: 3.2.2
"""
Article Finder v3.2.2 - Knowledge Module
Semantic search, knowledge graph, and synthesis tools.
"""

# Lazy imports to avoid circular dependencies
__all__ = [
    # Semantic Search
    'SemanticSearch', 'SearchResult', 'search_papers', 'find_similar_papers',
    
    # Claim Embeddings
    'ClaimEmbeddings', 'ClaimMatch', 'search_claims', 'find_duplicate_claims',
    
    # Knowledge Graph
    'ClaimGraph', 'NodeType', 'EdgeType', 'GraphNode', 'GraphEdge',
    
    # Query Engine
    'QueryEngine', 'QueryParser', 'QueryType', 'QueryResult', 'query_knowledge_graph',
    
    # Synthesis
    'ClaimSynthesizer', 'SynthesisResult', 'EffectSizeData', 'synthesize_construct',
    
    # Parallel Processing
    'BatchProcessor', 'CheckpointManager', 'IncrementalScorer', 'EmbeddingBatcher',
]
