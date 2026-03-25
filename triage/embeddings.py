# Version: 3.2.2
"""
Article Finder v3 - Embeddings Service
Wrapper for sentence-transformers with caching.
"""

import json
import hashlib
import pickle
from pathlib import Path
from typing import List, Optional, Union
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.loader import get


class EmbeddingService:
    """
    Embedding service using sentence-transformers.
    Includes caching for efficiency.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        device: Optional[str] = None
    ):
        self.model_name = model_name or get('embeddings.model', 'all-MiniLM-L6-v2')
        self.cache_dir = Path(cache_dir or get('paths.cache', 'data/cache')) / 'embeddings'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.device = device
        self._model = None
        self._dimension = None
    
    @property
    def model(self):
        """Lazy-load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, device=self.device)
                self._dimension = self._model.get_sentence_embedding_dimension()
            except ImportError:
                raise ImportError(
                    "sentence-transformers required. Run: pip install sentence-transformers"
                )
        return self._model
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        if self._dimension is None:
            _ = self.model  # Force model load
        return self._dimension
    
    def embed(self, text: Union[str, List[str]], use_cache: bool = True) -> np.ndarray:
        """
        Embed text(s) into vectors.
        
        Args:
            text: Single text or list of texts
            use_cache: Whether to use/store cache
            
        Returns:
            numpy array of shape (n_texts, dimension)
        """
        single = isinstance(text, str)
        texts = [text] if single else text
        
        if not texts:
            return np.array([])
        
        embeddings = []
        texts_to_embed = []
        indices_to_embed = []
        
        # Check cache
        if use_cache:
            for i, t in enumerate(texts):
                cached = self._get_cached(t)
                if cached is not None:
                    embeddings.append((i, cached))
                else:
                    texts_to_embed.append(t)
                    indices_to_embed.append(i)
        else:
            texts_to_embed = texts
            indices_to_embed = list(range(len(texts)))
        
        # Embed uncached texts
        if texts_to_embed:
            batch_size = get('embeddings.batch_size', 32)
            new_embeddings = self.model.encode(
                texts_to_embed,
                batch_size=batch_size,
                show_progress_bar=len(texts_to_embed) > 100,
                convert_to_numpy=True
            )
            
            # Cache and collect results
            for i, (idx, t) in enumerate(zip(indices_to_embed, texts_to_embed)):
                emb = new_embeddings[i]
                if use_cache:
                    self._set_cached(t, emb)
                embeddings.append((idx, emb))
        
        # Sort by original index and extract embeddings
        embeddings.sort(key=lambda x: x[0])
        result = np.array([e[1] for e in embeddings])
        
        if single:
            return result[0]
        return result
    
    def embed_paper(self, title: str, abstract: Optional[str] = None) -> np.ndarray:
        """
        Embed a paper using title and abstract.
        
        Combines title and abstract with appropriate weighting.
        """
        if abstract:
            # Combine title and abstract
            text = f"{title}. {abstract}"
        else:
            text = title
        
        return self.embed(text)
    
    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        a = np.asarray(a).flatten()
        b = np.asarray(b).flatten()
        
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def batch_similarity(self, query: np.ndarray, corpus: np.ndarray) -> np.ndarray:
        """
        Compute similarities between query and all corpus vectors.
        
        Args:
            query: Single embedding vector (dimension,)
            corpus: Matrix of embeddings (n_docs, dimension)
            
        Returns:
            Array of similarities (n_docs,)
        """
        query = np.asarray(query).flatten()
        corpus = np.asarray(corpus)
        
        if len(corpus.shape) == 1:
            corpus = corpus.reshape(1, -1)
        
        # Normalize
        query_norm = query / (np.linalg.norm(query) + 1e-10)
        corpus_norms = corpus / (np.linalg.norm(corpus, axis=1, keepdims=True) + 1e-10)
        
        # Dot product
        return np.dot(corpus_norms, query_norm)
    
    def _cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        text_hash = hashlib.md5(text.encode()).hexdigest()
        model_hash = hashlib.md5(self.model_name.encode()).hexdigest()[:8]
        return f"{model_hash}_{text_hash}"
    
    def _get_cached(self, text: str) -> Optional[np.ndarray]:
        """Get cached embedding."""
        cache_file = self.cache_dir / f"{self._cache_key(text)}.npy"
        if cache_file.exists():
            try:
                return np.load(cache_file)
            except Exception:
                pass
        return None
    
    def _set_cached(self, text: str, embedding: np.ndarray) -> None:
        """Cache an embedding."""
        if not get('embeddings.cache_embeddings', True):
            return
        cache_file = self.cache_dir / f"{self._cache_key(text)}.npy"
        try:
            np.save(cache_file, embedding)
        except Exception:
            pass
    
    def clear_cache(self) -> int:
        """Clear embedding cache. Returns number of files deleted."""
        count = 0
        for f in self.cache_dir.glob('*.npy'):
            f.unlink()
            count += 1
        return count


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get the global embedding service instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


# CLI
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test embedding service')
    parser.add_argument('--text', help='Text to embed')
    parser.add_argument('--clear-cache', action='store_true', help='Clear cache')
    
    args = parser.parse_args()
    
    service = EmbeddingService()
    
    if args.clear_cache:
        count = service.clear_cache()
        print(f"Cleared {count} cached embeddings")
    
    elif args.text:
        print(f"Model: {service.model_name}")
        print(f"Dimension: {service.dimension}")
        
        embedding = service.embed(args.text)
        print(f"Embedding shape: {embedding.shape}")
        print(f"Embedding (first 10): {embedding[:10]}")
    
    else:
        # Test with sample texts
        texts = [
            "The effect of daylight on cognitive performance in office workers",
            "Stress recovery in hospital patients with nature views",
            "Acoustic comfort in open plan offices"
        ]
        
        print(f"Model: {service.model_name}")
        print(f"Dimension: {service.dimension}")
        print()
        
        embeddings = service.embed(texts)
        print(f"Embedded {len(texts)} texts")
        print(f"Shape: {embeddings.shape}")
        print()
        
        # Similarity matrix
        print("Similarity matrix:")
        for i, t1 in enumerate(texts):
            for j, t2 in enumerate(texts):
                sim = service.similarity(embeddings[i], embeddings[j])
                print(f"  [{i}][{j}] = {sim:.3f}")
