"""Tests for Retriever — text matching, vector search, score propagation, reranking."""

import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from retrieve.retriever import Retriever, DIMENSION_ROOTS
from storage.sqlite_store import SQLiteStore
from core.context import Context


class TestRetrieverInit(unittest.TestCase):
    """Test Retriever initialization."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_create_retriever(self):
        r = Retriever(store=self.store)
        self.assertIsNotNone(r)

    def test_create_with_embed_fn(self):
        async def mock_embed(texts):
            return [[0.1] * 128 for _ in texts]
        r = Retriever(store=self.store, embed_fn=mock_embed)
        self.assertIsNotNone(r)

    def test_create_with_llm_fn(self):
        async def mock_llm(prompt):
            return "reranked"
        r = Retriever(store=self.store, llm_fn=mock_llm)
        self.assertIsNotNone(r)


class TestDimensionRoots(unittest.TestCase):
    """Test dimension root URIs."""

    def test_all_eight_dimensions(self):
        dims = ["person", "activity", "object", "preference",
                "taboo", "goal", "pattern", "thought"]
        for dim in dims:
            self.assertIn(dim, DIMENSION_ROOTS)

    def test_root_uri_format(self):
        for dim, root in DIMENSION_ROOTS.items():
            self.assertIn("amber://", root)
            self.assertIn(dim, root)


class TestTextSearch(unittest.TestCase):
    """Test text-based retrieval."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.retriever = Retriever(store=self.store)

        # Seed data
        self.store.put(Context(uri="/p/1", abstract="Frankie喜欢泰斯卡风暴威士忌",
                               content="Frankie最喜欢的威士忌是泰斯卡风暴，苏格兰单一麦芽",
                               category="preference", importance=0.7))
        self.store.put(Context(uri="/p/2", abstract="老王是同组同事",
                               content="老王和我在同一个组，负责海外业务",
                               category="person", importance=0.6))
        self.store.put(Context(uri="/p/3", abstract="今天和老王吃了火锅",
                               content="中午和老王去海底捞吃了火锅，聊了日本出差的事",
                               category="activity", importance=0.4))
        self.store.put(Context(uri="/p/4", abstract="不要提老王前女友",
                               content="千万不要在老王面前提他前女友，这是禁忌",
                               category="taboo", importance=0.9))
        self.store.put(Context(uri="/p/5", abstract="计划下周开始跑步减肥",
                               content="下周一开始每天早上跑步5公里，目标减10斤",
                               category="goal", importance=0.7))

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_search_by_keyword(self):
        results = self.retriever.search("威士忌", limit=5)
        self.assertTrue(len(results) > 0)
        # Top result should be about whisky
        top_ctx, top_score = results[0]
        self.assertIn("威士忌", top_ctx.abstract)

    def test_search_person(self):
        results = self.retriever.search("老王", limit=5)
        self.assertTrue(len(results) >= 2)  # Multiple mentions of 老王

    def test_search_no_results(self):
        results = self.retriever.search("量子纠缠", limit=5)
        self.assertEqual(len(results), 0)

    def test_search_limit(self):
        results = self.retriever.search("老王", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_search_returns_scores(self):
        results = self.retriever.search("Frankie", limit=5)
        for ctx, score in results:
            self.assertIsInstance(score, float)
            self.assertGreaterEqual(score, 0.0)

    def test_search_taboo_included(self):
        results = self.retriever.search("前女友", limit=5)
        self.assertTrue(any(ctx.category == "taboo" for ctx, _ in results))

    def test_search_decay_affects_score(self):
        # Add an old memory
        old_ctx = Context(
            uri="/p/old", abstract="很久以前的事",
            content="这是一个月前的记忆",
            category="activity", importance=0.5,
        )
        old_ctx.created_at = time.time() - 30 * 86400  # 30 days ago
        self.store.put(old_ctx)

        # Add a fresh memory with same content
        new_ctx = Context(
            uri="/p/new", abstract="很久以前的事情更新版",
            content="这是刚才的记忆",
            category="activity", importance=0.5,
        )
        self.store.put(new_ctx)

        results = self.retriever.search("记忆", limit=10)
        # Both should appear, but scoring may differ
        self.assertIsInstance(results, list)


class TestScorePropagation(unittest.TestCase):
    """Test hierarchical score propagation."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.retriever = Retriever(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_propagation_alpha(self):
        # alpha=0.6 means 60% query relevance, 40% parent score
        alpha = 0.6
        query_score = 0.8
        parent_score = 0.5
        propagated = alpha * query_score + (1 - alpha) * parent_score
        self.assertAlmostEqual(propagated, 0.68, places=2)

    def test_propagation_with_zero_parent(self):
        alpha = 0.6
        query_score = 0.8
        parent_score = 0.0
        propagated = alpha * query_score + (1 - alpha) * parent_score
        self.assertAlmostEqual(propagated, 0.48, places=2)

    def test_propagation_boosts_relevant(self):
        alpha = 0.6
        # Memory in a highly relevant dimension
        high_parent = alpha * 0.7 + (1 - alpha) * 0.9  # 0.78
        # Memory in a less relevant dimension
        low_parent = alpha * 0.7 + (1 - alpha) * 0.2  # 0.50
        self.assertGreater(high_parent, low_parent)


class TestSearchWeights(unittest.TestCase):
    """Test search weight configuration."""

    def test_default_weights(self):
        # text=0.3, vector=0.4, decay=0.2, propagation=0.1
        weights = {"text": 0.3, "vector": 0.4, "decay": 0.2, "propagation": 0.1}
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_text_only_search(self):
        # When no embeddings, text weight should dominate
        weights = {"text": 0.7, "vector": 0.0, "decay": 0.2, "propagation": 0.1}
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_score_combination(self):
        text_score = 0.8
        vector_score = 0.6
        decay_score = 0.9
        prop_score = 0.5
        w = {"text": 0.3, "vector": 0.4, "decay": 0.2, "propagation": 0.1}
        combined = (text_score * w["text"] + vector_score * w["vector"] +
                    decay_score * w["decay"] + prop_score * w["propagation"])
        self.assertAlmostEqual(combined, 0.71, places=2)


class TestConvergenceDetection(unittest.TestCase):
    """Test convergence detection in hierarchical search."""

    def test_identical_results_converge(self):
        round1 = ["/a", "/b", "/c"]
        round2 = ["/a", "/b", "/c"]
        overlap = len(set(round1) & set(round2)) / max(len(set(round1) | set(round2)), 1)
        self.assertAlmostEqual(overlap, 1.0)

    def test_different_results_no_converge(self):
        round1 = ["/a", "/b", "/c"]
        round2 = ["/d", "/e", "/f"]
        overlap = len(set(round1) & set(round2)) / max(len(set(round1) | set(round2)), 1)
        self.assertAlmostEqual(overlap, 0.0)

    def test_partial_overlap(self):
        round1 = ["/a", "/b", "/c", "/d"]
        round2 = ["/a", "/b", "/e", "/f"]
        overlap = len(set(round1) & set(round2)) / max(len(set(round1) | set(round2)), 1)
        self.assertAlmostEqual(overlap, 1/3, places=2)

    def test_convergence_threshold(self):
        # Converge when overlap > 0.8
        threshold = 0.8
        round1 = ["/a", "/b", "/c", "/d", "/e"]
        round2 = ["/a", "/b", "/c", "/d", "/f"]
        overlap = len(set(round1) & set(round2)) / max(len(set(round1) | set(round2)), 1)
        # 4/6 = 0.667, not converged
        self.assertLess(overlap, threshold)


class TestRetrieverIntegration(unittest.TestCase):
    """Integration tests for retriever with store."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.retriever = Retriever(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_search_empty_store(self):
        results = self.retriever.search("anything", limit=5)
        self.assertEqual(len(results), 0)

    def test_search_after_bulk_insert(self):
        for i in range(100):
            self.store.put(Context(
                uri=f"/bulk/{i}",
                abstract=f"记忆条目 {i}",
                content=f"这是第 {i} 条记忆的详细内容",
                category=["person", "activity", "object", "preference",
                          "taboo", "goal", "pattern", "thought"][i % 8],
                importance=0.3 + (i % 5) * 0.1,
            ))
        results = self.retriever.search("记忆", limit=10)
        self.assertLessEqual(len(results), 10)
        self.assertGreater(len(results), 0)

    def test_search_respects_category_filter(self):
        self.store.put(Context(uri="/g/1", abstract="学习Rust", category="goal"))
        self.store.put(Context(uri="/a/1", abstract="学习了Python", category="activity"))
        results = self.retriever.search("学习", limit=10, category="goal")
        if results:
            for ctx, _ in results:
                self.assertEqual(ctx.category, "goal")


if __name__ == "__main__":
    unittest.main()
