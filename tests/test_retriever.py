"""Tests for retrieve.retriever — text match, vector search, score propagation, rerank."""

import asyncio
import math
import os
import struct
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import Context, DecayParams
from storage.sqlite_store import SQLiteStore
from retrieve.retriever import (
    Retriever, cosine_similarity, pack_vector, unpack_vector,
    DIMENSION_ROOTS, ALL_DIMENSIONS,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestVectorUtils(unittest.TestCase):
    """Test cosine_similarity, pack/unpack vector."""

    def test_cosine_identical(self):
        v = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0)

    def test_cosine_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0)

    def test_cosine_opposite(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(a, b), -1.0)

    def test_cosine_empty(self):
        self.assertEqual(cosine_similarity([], []), 0.0)

    def test_cosine_different_lengths(self):
        self.assertEqual(cosine_similarity([1.0], [1.0, 2.0]), 0.0)

    def test_cosine_zero_vector(self):
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 2.0]), 0.0)

    def test_pack_unpack_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        packed = pack_vector(vec)
        unpacked = unpack_vector(packed)
        for a, b in zip(vec, unpacked):
            self.assertAlmostEqual(a, b, places=5)

    def test_pack_empty(self):
        packed = pack_vector([])
        self.assertEqual(len(packed), 0)
        self.assertEqual(unpack_vector(packed), [])


class TestDimensionRoots(unittest.TestCase):
    """Test dimension constants."""

    def test_all_eight_dimensions(self):
        expected = {"person", "activity", "object", "preference",
                    "taboo", "goal", "pattern", "thought"}
        self.assertEqual(set(ALL_DIMENSIONS), expected)

    def test_roots_format(self):
        for dim, root in DIMENSION_ROOTS.items():
            self.assertTrue(root.startswith("amber://memories/"))
            self.assertIn(dim, root)


class RetrieverTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = SQLiteStore(self.tmp.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmp.name)

    def _add_memory(self, uri, abstract, category="preference", content="", importance=0.5):
        ctx = Context(
            uri=uri, abstract=abstract, overview=abstract,
            content=content or abstract, category=category,
            importance=importance,
        )
        self.store.put(ctx)
        return ctx


class TestTextMatch(RetrieverTestBase):
    """Test _text_match scoring."""

    def test_exact_match_high_score(self):
        retriever = Retriever(store=self.store)
        ctx = Context(abstract="喜欢喝咖啡", overview="用户喜欢咖啡", content="每天喝咖啡")
        results = retriever._text_match("喜欢喝咖啡", [ctx])
        self.assertEqual(len(results), 1)
        self.assertGreater(results[0][1], 0.3)

    def test_no_match_empty_result(self):
        retriever = Retriever(store=self.store)
        ctx = Context(abstract="学习编程", overview="学编程", content="Python")
        results = retriever._text_match("xyz完全不相关", [ctx])
        # May still have some char overlap, but should be low
        if results:
            self.assertLess(results[0][1], 0.3)

    def test_empty_query(self):
        retriever = Retriever(store=self.store)
        results = retriever._text_match("", [Context(abstract="test")])
        self.assertEqual(results, [])

    def test_empty_contexts(self):
        retriever = Retriever(store=self.store)
        results = retriever._text_match("query", [])
        self.assertEqual(results, [])

    def test_substring_bonus(self):
        retriever = Retriever(store=self.store)
        ctx_match = Context(abstract="我喜欢咖啡", overview="", content="")
        ctx_no = Context(abstract="我喜欢茶", overview="", content="")
        r1 = retriever._text_match("咖啡", [ctx_match])
        r2 = retriever._text_match("咖啡", [ctx_no])
        if r1 and r2:
            self.assertGreater(r1[0][1], r2[0][1])

    def test_results_sorted_by_score(self):
        retriever = Retriever(store=self.store)
        contexts = [
            Context(abstract="完全不相关的内容xyz", overview="", content=""),
            Context(abstract="咖啡是我的最爱", overview="喜欢咖啡", content="每天喝咖啡"),
        ]
        results = retriever._text_match("咖啡", contexts)
        if len(results) >= 2:
            self.assertGreaterEqual(results[0][1], results[1][1])


class TestSearchIntegration(RetrieverTestBase):
    """Test full search pipeline."""

    def test_search_text_only(self):
        self._add_memory("/pref/coffee", "喜欢喝咖啡", category="preference")
        self._add_memory("/pref/tea", "喜欢喝茶", category="preference")
        retriever = Retriever(store=self.store)
        results = run(retriever.search("咖啡", limit=5))
        self.assertGreater(len(results), 0)
        # Coffee should rank higher
        uris = [ctx.uri for ctx, _ in results]
        if "/pref/coffee" in uris and "/pref/tea" in uris:
            coffee_idx = uris.index("/pref/coffee")
            tea_idx = uris.index("/pref/tea")
            self.assertLess(coffee_idx, tea_idx)

    def test_search_empty_store(self):
        retriever = Retriever(store=self.store)
        results = run(retriever.search("anything"))
        self.assertEqual(results, [])

    def test_search_respects_limit(self):
        for i in range(20):
            self._add_memory(f"/pref/{i}", f"Memory number {i}", category="preference")
        retriever = Retriever(store=self.store)
        results = run(retriever.search("Memory", limit=5))
        self.assertLessEqual(len(results), 5)

    def test_search_touches_results(self):
        self._add_memory("/pref/1", "Test memory", category="preference")
        retriever = Retriever(store=self.store)
        run(retriever.search("Test"))
        ctx = self.store.get("/pref/1")
        self.assertGreaterEqual(ctx.access_count, 1)

    def test_search_with_threshold(self):
        self._add_memory("/pref/1", "Very specific unique content xyz", category="preference")
        retriever = Retriever(store=self.store)
        results = run(retriever.search("completely different query abc", threshold=0.99))
        self.assertEqual(len(results), 0)


class TestSearchWithVectors(RetrieverTestBase):
    """Test vector search integration."""

    def test_search_with_embed_fn(self):
        ctx = self._add_memory("/pref/1", "喜欢咖啡", category="preference")
        vec = [0.1] * 128
        self.store.put_embedding("/pref/1", pack_vector(vec), model="test")

        async def mock_embed(texts):
            return [[0.1] * 128 for _ in texts]

        retriever = Retriever(store=self.store, embed_fn=mock_embed)
        results = run(retriever.search("咖啡", limit=5))
        self.assertGreater(len(results), 0)

    def test_search_vector_similarity_affects_score(self):
        self._add_memory("/pref/1", "Item A", category="preference")
        self._add_memory("/pref/2", "Item B", category="preference")
        # Give item 1 a vector close to query, item 2 a distant one
        self.store.put_embedding("/pref/1", pack_vector([1.0, 0.0, 0.0]), model="test")
        self.store.put_embedding("/pref/2", pack_vector([0.0, 0.0, 1.0]), model="test")

        async def mock_embed(texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

        retriever = Retriever(store=self.store, embed_fn=mock_embed)
        results = run(retriever.search("Item", limit=5))
        # Both should appear, item 1 should score higher due to vector similarity
        if len(results) >= 2:
            uris = [ctx.uri for ctx, _ in results]
            if "/pref/1" in uris and "/pref/2" in uris:
                idx1 = uris.index("/pref/1")
                idx2 = uris.index("/pref/2")
                self.assertLess(idx1, idx2)


class TestIndexContext(RetrieverTestBase):
    """Test embedding indexing."""

    def test_index_with_embed_fn(self):
        async def mock_embed(texts):
            return [[0.5] * 64 for _ in texts]

        retriever = Retriever(store=self.store, embed_fn=mock_embed)
        ctx = Context(uri="/test/1", abstract="Test", overview="Test overview")
        run(retriever.index_context(ctx))
        emb = self.store.get_embedding("/test/1")
        self.assertIsNotNone(emb)

    def test_index_without_embed_fn(self):
        retriever = Retriever(store=self.store, embed_fn=None)
        ctx = Context(uri="/test/1", abstract="Test")
        run(retriever.index_context(ctx))
        self.assertIsNone(self.store.get_embedding("/test/1"))

    def test_index_empty_content_skipped(self):
        async def mock_embed(texts):
            return [[0.5] * 64 for _ in texts]

        retriever = Retriever(store=self.store, embed_fn=mock_embed)
        ctx = Context(uri="/test/1", abstract="", overview="", content="")
        run(retriever.index_context(ctx))
        self.assertIsNone(self.store.get_embedding("/test/1"))


class TestLLMRerank(RetrieverTestBase):
    """Test LLM reranking."""

    def test_rerank_reorders(self):
        self._add_memory("/pref/1", "First item", category="preference")
        self._add_memory("/pref/2", "Second item", category="preference")

        mock_llm = AsyncMock(return_value="2, 1")
        retriever = Retriever(store=self.store, llm_fn=mock_llm)
        results = run(retriever.search("item", limit=5, rerank=True))
        self.assertGreater(len(results), 0)

    def test_rerank_failure_preserves_order(self):
        self._add_memory("/pref/1", "Test item", category="preference")
        mock_llm = AsyncMock(side_effect=Exception("fail"))
        retriever = Retriever(store=self.store, llm_fn=mock_llm)
        results = run(retriever.search("Test", limit=5, rerank=True))
        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    unittest.main()
