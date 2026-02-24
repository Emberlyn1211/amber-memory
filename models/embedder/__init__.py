"""Embedder base classes and ARK implementation.

Adapted from OpenViking's embedder abstraction.
Supports dense, sparse, and hybrid embedding modes.
"""

from .base import EmbedResult, EmbedderBase, DenseEmbedderBase
from .ark_embedder import ArkEmbedder

__all__ = ["EmbedResult", "EmbedderBase", "DenseEmbedderBase", "ArkEmbedder"]
