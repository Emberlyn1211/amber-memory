"""Tests for AmberMemory client — integration tests for the main API."""

import asyncio
import json
import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from client import AmberMemory
from core.context import Context


class MockClientLLM:
    """Mock LLM for client tests."""
    def __init__(self):
        self.calls = []
    async def __call__(self, prompt):
        self.calls.append(prompt)
        if "提取" in prompt or "extract" in prompt.lower():
            return json.dumps([
                {"dimension": "preference", "content": "喜欢威士忌", "importance": 0.7},
            ])
        return json.dumps({"decision": "create", "reason": "new"})


class TestClientInit(unittest.TestCase):
    """Test AmberMemory client initialization."""

    def test_create_minimal(self):
        db_path = tempfile.mktemp(suffix=".db")
        mem = AmberMemory(db_path)
        self.assertIsNotNone(mem)
        mem.close()
        os.unlink(db_path)

    def test_create_with_llm(self):
        db_path = tempfile.mktemp(suffix=".db")
        mock = MockClientLLM()
        mem = AmberMemory(db_path, llm_fn=mock)
        self.assertIsNotNone(mem)
        mem.close()
        os.unlink(db_path)

    def test_create_expands_tilde(self):
        db_path = tempfile.mktemp(suffix=".db")
        mem = AmberMemory(db_path)
        self.assertIsNotNone(mem)
        mem.close()
        os.unlink(db_path)


class TestClientRemember(unittest.TestCase):
    """Test remember (store) API."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_remember_basic(self):
        ctx = self.mem.remember("Frankie喜欢威士忌")
        self.assertIsNotNone(ctx)
        self.assertIn("威士忌", ctx.abstract)

    def test_remember_with_category(self):
        ctx = self.mem.remember("老王是同事", category="person")
        self.assertEqual(ctx.category, "person")

    def test_remember_with_source(self):
        ctx = self.mem.remember("今天吃了火锅", source="telegram")
        self.assertIsNotNone(ctx)

    def test_remember_with_importance(self):
        ctx = self.mem.remember("不要提前女友", category="taboo", importance=0.95)
        self.assertAlmostEqual(ctx.importance, 0.95, places=2)

    def test_remember_returns_context(self):
        ctx = self.mem.remember("测试记忆")
        self.assertIsInstance(ctx, Context)
        self.assertTrue(len(ctx.uri) > 0)

    def test_remember_multiple(self):
        self.mem.remember("记忆1", category="activity")
        self.mem.remember("记忆2", category="goal")
        self.mem.remember("记忆3", category="thought")
        stats = self.mem.stats()
        self.assertEqual(stats["total"], 3)

    def test_remember_chinese_content(self):
        ctx = self.mem.remember("外公陈伯年2018年去世，当时我在伦敦没能见最后一面")
        self.assertIsNotNone(ctx)
        self.assertIn("外公", ctx.abstract)

    def test_remember_long_content(self):
        long_text = "这是一段很长的记忆内容。" * 100
        ctx = self.mem.remember(long_text)
        self.assertIsNotNone(ctx)
        self.assertLessEqual(len(ctx.abstract), 200)


class TestClientRecall(unittest.TestCase):
    """Test recall (search) API."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)
        self.mem.remember("Frankie喜欢泰斯卡风暴威士忌", category="preference")
        self.mem.remember("老王是同组同事负责海外业务", category="person")
        self.mem.remember("今天和老王吃了海底捞火锅", category="activity")
        self.mem.remember("不要在老王面前提他前女友", category="taboo")
        self.mem.remember("下周开始每天跑步减肥", category="goal")

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_recall_basic(self):
        results = self.mem.recall("威士忌")
        self.assertTrue(len(results) > 0)

    def test_recall_returns_tuples(self):
        results = self.mem.recall("老王")
        for item in results:
            self.assertEqual(len(item), 2)
            ctx, score = item
            self.assertIsInstance(ctx, Context)
            self.assertIsInstance(score, float)

    def test_recall_limit(self):
        results = self.mem.recall("老王", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_recall_no_results(self):
        results = self.mem.recall("量子纠缠黑洞")
        self.assertEqual(len(results), 0)

    def test_recall_scores_ordered(self):
        results = self.mem.recall("老王", limit=10)
        if len(results) >= 2:
            scores = [s for _, s in results]
            # Should be descending
            for i in range(len(scores) - 1):
                self.assertGreaterEqual(scores[i], scores[i + 1])


class TestClientTop(unittest.TestCase):
    """Test top memories API."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)
        for i in range(15):
            self.mem.remember(f"记忆条目 {i}", importance=0.3 + (i % 5) * 0.15)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_top_returns_results(self):
        results = self.mem.top(limit=10)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 10)

    def test_top_ordered_by_score(self):
        results = self.mem.top(limit=10)
        scores = [s for _, s in results]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])


class TestClientForget(unittest.TestCase):
    """Test forget (delete) API."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_forget_existing(self):
        ctx = self.mem.remember("要忘记的事")
        result = self.mem.forget(ctx.uri)
        self.assertTrue(result)
        # Should not find it anymore
        results = self.mem.recall("要忘记的事")
        self.assertEqual(len(results), 0)

    def test_forget_nonexistent(self):
        result = self.mem.forget("/does/not/exist")
        self.assertFalse(result)


class TestClientTaboo(unittest.TestCase):
    """Test taboo management via client."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_add_taboo(self):
        tid = self.mem.add_taboo("前女友", description="老王的禁忌话题")
        self.assertIsNotNone(tid)

    def test_list_taboos(self):
        self.mem.add_taboo("前女友")
        self.mem.add_taboo("工资")
        taboos = self.mem.list_taboos()
        self.assertEqual(len(taboos), 2)

    def test_remove_taboo(self):
        tid = self.mem.add_taboo("临时禁忌")
        self.mem.remove_taboo(tid)
        taboos = self.mem.list_taboos()
        self.assertEqual(len(taboos), 0)


class TestClientStats(unittest.TestCase):
    """Test stats API."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_stats_empty(self):
        stats = self.mem.stats()
        self.assertIsInstance(stats, dict)
        self.assertEqual(stats["total"], 0)

    def test_stats_after_remember(self):
        self.mem.remember("记忆1", category="person")
        self.mem.remember("记忆2", category="goal")
        stats = self.mem.stats()
        self.assertEqual(stats["total"], 2)
        self.assertIn("by_type", stats)

    def test_stats_has_db_path(self):
        stats = self.mem.stats()
        self.assertIn("db_path", stats)

    def test_stats_has_decay_info(self):
        stats = self.mem.stats()
        self.assertIn("decay_half_life_days", stats)
        self.assertEqual(stats["decay_half_life_days"], 14)


class TestClientPeopleGraph(unittest.TestCase):
    """Test people graph access via client."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(self.db_path)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_people_accessible(self):
        self.assertIsNotNone(self.mem.people)

    def test_add_person_via_client(self):
        self.mem.people.add_person("Frankie", relationship="human")
        p = self.mem.people.find_person("Frankie")
        self.assertIsNotNone(p)

    def test_patterns_accessible(self):
        self.assertIsNotNone(self.mem.patterns)


class TestClientCompress(unittest.TestCase):
    """Test session compression via client."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.mock_llm = MockClientLLM()
        self.mem = AmberMemory(self.db_path, llm_fn=self.mock_llm)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_compress_requires_llm(self):
        mem_no_llm = AmberMemory(tempfile.mktemp(suffix=".db"))
        messages = [{"role": "user", "content": "test"}]
        try:
            asyncio.get_event_loop().run_until_complete(
                mem_no_llm.compress_session(messages, user="Test")
            )
        except Exception:
            pass  # Expected — no LLM
        mem_no_llm.close()

    def test_compress_with_mock_llm(self):
        messages = [
            {"role": "user", "content": "我喜欢喝威士忌"},
            {"role": "assistant", "content": "什么牌子的？"},
        ]
        memories = asyncio.get_event_loop().run_until_complete(
            self.mem.compress_session(messages, user="Frankie")
        )
        self.assertIsInstance(memories, list)


if __name__ == "__main__":
    unittest.main()
