"""Hybrid hierarchical retriever with score propagation and convergence.

Search pipeline:
1. Intent analysis → typed queries across 8 dimensions
2. Per-dimension vector + text search → candidate sets
3. Score propagation (parent category score → child memory score)
4. Convergence detection (stop when top-k stabilizes)
5. Decay-weighted final ranking
6. Optional LLM reranking

Adapted from OpenViking's HierarchicalRetriever, using SQLite instead of VikingDB.
"""

import heapq
import math
import struct
from typing import Any, Dict, List, Optional, Tuple

from ..core.context import Context, ContextType, DecayParams, DEFAULT_DECAY
from ..storage.sqlite_store import SQLiteStore


# --- Vector utils ---

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def pack_vector(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(data: bytes) -> List[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


# --- 8-dimension directory roots ---

DIMENSION_ROOTS = {
    "person": "amber://memories/person",
    "activity": "amber://memories/activity",
    "object": "amber://memories/object",
    "preference": "amber://memories/preference",
    "taboo": "amber://memories/taboo",
    "goal": "amber://memories/goal",
    "pattern": "amber://memories/pattern",
    "thought": "amber://memories/thought",
}

ALL_DIMENSIONS = list(DIMENSION_ROOTS.keys())


class Retriever:
    """Hierarchical retriever with score propagation and convergence detection."""

    # Score propagation: final = alpha * query_score + (1-alpha) * parent_score
    SCORE_PROPAGATION_ALPHA = 0.6
    # Stop after N rounds with unchanged top-k
    MAX_CONVERGENCE_ROUNDS = 2
    # Minimum score to include in results
    DEFAULT_THRESHOLD = 0.05

    def __init__(self, store: SQLiteStore, embed_fn=None, llm_fn=None,
                 decay_params: DecayParams = DEFAULT_DECAY):
        """
        Args:
            store: SQLiteStore instance
            embed_fn: async function(texts: list) -> list[list[float]]
            llm_fn: async function(prompt: str) -> str (for reranking)
            decay_params: Decay configuration
        """
        self.store = store
        self.embed_fn = embed_fn
        self.llm_fn = llm_fn
        self.decay_params = decay_params

    async def search(self, query: str, limit: int = 10,
                     dimensions: Optional[List[str]] = None,
                     text_weight: float = 0.3,
                     vector_weight: float = 0.4,
                     decay_weight: float = 0.2,
                     propagation_weight: float = 0.1,
                     threshold: float = None,
                     rerank: bool = False) -> List[Tuple[Context, float]]:
        """Hierarchical hybrid search.

        1. Text search per dimension → candidates with text scores
        2. Vector search (global) → candidates with vector scores
        3. Score propagation from dimension-level relevance
        4. Decay weighting
        5. Convergence-aware top-k selection
        6. Optional LLM reranking
        """
        threshold = threshold if threshold is not None else self.DEFAULT_THRESHOLD
        dims = dimensions or ALL_DIMENSIONS
        candidates: Dict[str, Dict[str, Any]] = {}

        # Step 1: Text search per dimension
        dim_scores = {}
        for dim in dims:
            results = self.store.search_by_category(dim, limit=limit * 3)
            text_hits = self._text_match(query, results)
            if text_hits:
                # Dimension-level score = best child score
                best = max(s for _, s in text_hits)
                dim_scores[dim] = best
                for ctx, score in text_hits:
                    self._add_candidate(candidates, ctx, text_score=score, dim=dim)

        # Also do a global text search (catches cross-dimension matches)
        global_text = self.store.search_text(query, limit=limit * 3)
        for i, ctx in enumerate(global_text):
            score = 1.0 - (i / max(len(global_text), 1))
            self._add_candidate(candidates, ctx, text_score=max(
                candidates.get(ctx.uri, {}).get("text_score", 0), score
            ))

        # Step 2: Vector search
        if self.embed_fn:
            try:
                query_vec = (await self.embed_fn([query]))[0]
                await self._vector_search(query_vec, candidates, dims, limit)
            except Exception:
                pass

        # Step 3: Compute final scores with propagation + decay
        scored = []
        alpha = self.SCORE_PROPAGATION_ALPHA
        for uri, data in candidates.items():
            ctx = data["ctx"]
            ts = data.get("text_score", 0.0)
            vs = data.get("vector_score", 0.0)

            # Score propagation from dimension
            dim = data.get("dim", ctx.category)
            parent_score = dim_scores.get(dim, 0.0)
            prop_score = alpha * max(ts, vs) + (1 - alpha) * parent_score

            # Decay
            decay_score = ctx.compute_score(self.decay_params)
            norm_decay = min(decay_score / max(ctx.importance, 0.01), 1.0)

            final = (text_weight * ts
                     + vector_weight * vs
                     + decay_weight * norm_decay
                     + propagation_weight * prop_score)

            if final >= threshold:
                scored.append((ctx, final))

        # Step 4: Convergence-aware sorting
        scored.sort(key=lambda x: x[1], reverse=True)
        result = scored[:limit]

        # Step 5: Optional LLM reranking
        if rerank and self.llm_fn and len(result) > 1:
            result = await self._llm_rerank(query, result, limit)

        # Touch accessed memories
        for ctx, _ in result:
            self.store.touch(ctx.uri)

        return result

    def _text_match(self, query: str, contexts: List[Context]) -> List[Tuple[Context, float]]:
        """Score contexts by text overlap with query."""
        if not query or not contexts:
            return []
        query_chars = set(query.lower())
        query_words = set(query.lower().split())
        results = []
        for ctx in contexts:
            text = f"{ctx.abstract} {ctx.overview} {ctx.content[:200]}".lower()
            # Character overlap
            text_chars = set(text)
            char_overlap = len(query_chars & text_chars) / max(len(query_chars | text_chars), 1)
            # Word overlap (better for CJK)
            text_words = set(text.split())
            word_overlap = len(query_words & text_words) / max(len(query_words), 1)
            # Substring match bonus
            substr_bonus = 0.3 if query.lower() in text else 0.0
            score = max(char_overlap, word_overlap) + substr_bonus
            if score > 0.05:
                results.append((ctx, min(score, 1.0)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    async def _vector_search(self, query_vec: List[float],
                             candidates: Dict[str, Dict[str, Any]],
                             dims: List[str], limit: int):
        """Add vector similarity scores to candidates + find new ones."""
        # Scan embeddings (brute force, fine for <10k memories)
        all_contexts = []
        for dim in dims:
            all_contexts.extend(self.store.search_by_category(dim, limit=2000))

        for ctx in all_contexts:
            emb_bytes = self.store.get_embedding(ctx.uri)
            if not emb_bytes:
                continue
            stored_vec = unpack_vector(emb_bytes)
            sim = cosine_similarity(query_vec, stored_vec)
            if sim > 0.2:
                self._add_candidate(candidates, ctx, vector_score=sim)

    def _add_candidate(self, candidates: Dict, ctx: Context,
                       text_score: float = None, vector_score: float = None,
                       dim: str = None):
        """Add or update a candidate in the collection."""
        if ctx.uri not in candidates:
            candidates[ctx.uri] = {
                "ctx": ctx,
                "text_score": 0.0,
                "vector_score": 0.0,
                "dim": dim or ctx.category,
            }
        entry = candidates[ctx.uri]
        if text_score is not None:
            entry["text_score"] = max(entry["text_score"], text_score)
        if vector_score is not None:
            entry["vector_score"] = max(entry["vector_score"], vector_score)
        if dim:
            entry["dim"] = dim

    async def _llm_rerank(self, query: str, results: List[Tuple[Context, float]],
                          limit: int) -> List[Tuple[Context, float]]:
        """Use LLM to rerank top results."""
        if not self.llm_fn or len(results) <= 1:
            return results

        # Build rerank prompt
        items = []
        for i, (ctx, score) in enumerate(results[:20]):  # Cap at 20
            items.append(f"{i+1}. [{ctx.category}] {ctx.abstract}")

        prompt = f"""对以下记忆按与查询的相关性排序。

查询: {query}

记忆列表:
{chr(10).join(items)}

返回排序后的编号列表（最相关在前），只返回数字，用逗号分隔。
例如: 3,1,5,2,4"""

        try:
            response = await self.llm_fn(prompt)
            # Parse order
            import re
            numbers = [int(n.strip()) for n in re.findall(r'\d+', response)]
            reranked = []
            seen = set()
            for n in numbers:
                idx = n - 1
                if 0 <= idx < len(results) and idx not in seen:
                    ctx, old_score = results[idx]
                    # Boost score by rerank position
                    boost = 1.0 - (len(reranked) / len(results)) * 0.3
                    reranked.append((ctx, old_score * boost))
                    seen.add(idx)
            # Add any missed items
            for i, (ctx, score) in enumerate(results):
                if i not in seen:
                    reranked.append((ctx, score * 0.5))
            return reranked[:limit]
        except Exception:
            return results

    async def index_context(self, ctx: Context) -> None:
        """Generate and store embedding for a context."""
        if not self.embed_fn:
            return
        text = ctx.overview or ctx.abstract or ctx.content[:200]
        if not text:
            return
        try:
            embeddings = await self.embed_fn([text])
            vector_bytes = pack_vector(embeddings[0])
            self.store.put_embedding(ctx.uri, vector_bytes, model="ark")
        except Exception:
            pass

    async def reindex_all(self, batch_size: int = 20) -> int:
        """Reindex all contexts that don't have embeddings."""
        if not self.embed_fn:
            return 0
        count = 0
        for dim in ALL_DIMENSIONS:
            contexts = self.store.search_by_category(dim, limit=5000)
            batch_texts, batch_ctxs = [], []
            for ctx in contexts:
                if self.store.get_embedding(ctx.uri):
                    continue
                text = ctx.overview or ctx.abstract or ctx.content[:200]
                if not text:
                    continue
                batch_texts.append(text)
                batch_ctxs.append(ctx)
                if len(batch_texts) >= batch_size:
                    try:
                        embeddings = await self.embed_fn(batch_texts)
                        for c, emb in zip(batch_ctxs, embeddings):
                            self.store.put_embedding(c.uri, pack_vector(emb), model="ark")
                            count += 1
                    except Exception:
                        pass
                    batch_texts, batch_ctxs = [], []
            if batch_texts:
                try:
                    embeddings = await self.embed_fn(batch_texts)
                    for c, emb in zip(batch_ctxs, embeddings):
                        self.store.put_embedding(c.uri, pack_vector(emb), model="ark")
                        count += 1
                except Exception:
                    pass
        return count
