"""Embedder base classes.

Simplified from OpenViking — just the core abstractions we need.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def truncate_and_normalize(embedding: List[float], dimension: Optional[int]) -> List[float]:
    """Truncate and L2 normalize embedding vector."""
    if not dimension or len(embedding) <= dimension:
        return embedding
    embedding = embedding[:dimension]
    norm = math.sqrt(sum(x ** 2 for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]
    return embedding


@dataclass
class EmbedResult:
    """Embedding result supporting dense and sparse vectors."""
    dense_vector: Optional[List[float]] = None
    sparse_vector: Optional[Dict[str, float]] = None

    @property
    def is_dense(self) -> bool:
        return self.dense_vector is not None

    @property
    def is_sparse(self) -> bool:
        return self.sparse_vector is not None

    @property
    def is_hybrid(self) -> bool:
        return self.dense_vector is not None and self.sparse_vector is not None


class EmbedderBase(ABC):
    """Base class for all embedders."""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        self.model_name = model_name
        self.config = config or {}

    @abstractmethod
    def embed(self, text: str) -> EmbedResult:
        pass

    def embed_batch(self, texts: List[str]) -> List[EmbedResult]:
        return [self.embed(text) for text in texts]

    def close(self):
        pass


class DenseEmbedderBase(EmbedderBase):
    """Dense embedder that returns dense vectors."""

    @abstractmethod
    def embed(self, text: str) -> EmbedResult:
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        pass
