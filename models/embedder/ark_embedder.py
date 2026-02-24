"""ARK (火山方舟/豆包) embedder implementation.

Uses Volcengine ARK API for text embedding.
Model: doubao-embedding or similar.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

from .base import DenseEmbedderBase, EmbedResult, truncate_and_normalize

logger = logging.getLogger(__name__)

# Default ARK embedding model
DEFAULT_MODEL = "doubao-embedding-large-text-240915"
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


class ArkEmbedder(DenseEmbedderBase):
    """Volcengine ARK embedding client.
    
    Uses the OpenAI-compatible /embeddings endpoint.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        model = model_name or os.environ.get("ARK_EMBED_MODEL", DEFAULT_MODEL)
        super().__init__(model_name=model, config=config)
        
        self.api_key = api_key or os.environ.get("ARK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("ARK_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.dimension = dimension
        self._cached_dimension: Optional[int] = None

        if not self.api_key:
            logger.warning("ARK_API_KEY not set — embedding calls will fail")

    def embed(self, text: str) -> EmbedResult:
        """Embed a single text string."""
        if not text.strip():
            return EmbedResult(dense_vector=[0.0] * self.get_dimension())

        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "input": [text[:8000]],  # ARK has input length limits
                    "encoding_format": "float",
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            
            vector = data["data"][0]["embedding"]
            vector = truncate_and_normalize(vector, self.dimension)
            
            if self._cached_dimension is None:
                self._cached_dimension = len(vector)
            
            return EmbedResult(dense_vector=vector)

        except Exception as e:
            logger.error(f"ARK embedding failed: {e}")
            # Return zero vector on failure
            dim = self._cached_dimension or 2048
            return EmbedResult(dense_vector=[0.0] * dim)

    def embed_batch(self, texts: List[str]) -> List[EmbedResult]:
        """Batch embed — ARK supports up to 16 texts per request."""
        if not texts:
            return []

        results = []
        batch_size = 16
        
        for i in range(0, len(texts), batch_size):
            batch = [t[:8000] for t in texts[i:i + batch_size]]
            try:
                response = requests.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model_name,
                        "input": batch,
                        "encoding_format": "float",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                
                for item in data["data"]:
                    vector = truncate_and_normalize(item["embedding"], self.dimension)
                    results.append(EmbedResult(dense_vector=vector))
                    
                if self._cached_dimension is None and results:
                    self._cached_dimension = len(results[0].dense_vector)

            except Exception as e:
                logger.error(f"ARK batch embedding failed: {e}")
                dim = self._cached_dimension or 2048
                results.extend([EmbedResult(dense_vector=[0.0] * dim)] * len(batch))

        return results

    def get_dimension(self) -> int:
        """Get embedding dimension. Probes API if not cached."""
        if self._cached_dimension:
            return self._cached_dimension
        if self.dimension:
            return self.dimension
        
        # Probe with a test string
        try:
            result = self.embed("test")
            if result.dense_vector:
                self._cached_dimension = len(result.dense_vector)
                return self._cached_dimension
        except Exception:
            pass
        
        return 2048  # Default for doubao-embedding-large
