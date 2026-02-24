#!/usr/bin/env python3
"""Tests for Amber Memory core functionality."""

import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amber_memory.core.context import Context, ContextType, DecayParams, EmotionTag
from amber_memory.core.uri import URI
from amber_memory.storage.sqlite_store import SQLiteStore
from amber_memory.client import AmberMemory


class TestURI(unittest.TestCase):
    def test_parse(self):
        uri = URI.parse("/wechat/messages/子扬/2026-02-24")
        self.assertEqual(uri.source, "wechat")
        self.assertEqual(uri.category, "messages")
        self.assertEqual(uri.path, "子扬/2026-02-24")
        self.assertEqual(uri.full, "/wechat/messages/子扬/2026-02-24")

    def test_parent(self):
        uri = URI.parse("/wechat/messages/子扬/2026-02-24")
        parent = uri.parent
        self.assertEqual(parent.full, "/wechat/messages/子扬")

    def test_from_wechat_msg(self):
        uri = URI.from_wechat_msg("子扬", "2026-02-24")
        self.assertEqual(uri.full, "/wechat/messages/子扬/2026-02-24")

    def test_hash_id(self):
        uri = URI.parse("/test/a/b")
        self.assertEqual(len(uri.hash_id), 16)

    def test_equality(self):
        a = URI.parse("/a/b/c")
        b = URI.parse("/a/b/c")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))


class TestContext(unittest.TestCase):
    def test_create(self):
        ctx = Context(uri="/test/mem/1", abstract="test", importance=0.8)
        self.assertEqual(ctx.uri, "/test/mem/1")
        self.assertEqual(ctx.importance, 0.8)
        self.assertIsNotNone(ctx.id)

    def test_decay_fresh(self):
        ctx = Context(importance=0.5)
        score = ctx.compute_score()
        self.assertAlmostEqual(score, 0.5, places=1)

    def test_decay_over_time(self):
        params = DecayParams(half_life_days=14)
        ctx = Context(importance=1.0)
        now = time.time()
        score_0 = ctx.compute_score(params, now=now)
        score_14 = ctx.compute_score(params, now=now + 14 * 86400)
        score_28 = ctx.compute_score(params, now=now + 28 * 86400)
        # After 1 half-life, score should be ~half
        self.assertAlmostEqual(score_14 / score_0, 0.5, places=1)
        self.assertAlmostEqual(score_28 / score_0, 0.25, places=1)

    def test_emotion_boost(self):
        neutral = Context(importance=0.5, emotion="neutral")
        love = Context(importance=0.5, emotion="love")
        self.assertGreater(love.compute_score(), neutral.compute_score())

    def test_access_boost(self):
        ctx = Context(importance=0.5, access_count=10)
        base = Context(importance=0.5, access_count=0)
        self.assertGreater(ctx.compute_score(), base.compute_score())

    def test_importance_floor(self):
        params = DecayParams(half_life_days=1)
        ctx = Context(importance=0.5)
        # After 100 days, should still be above floor
        score = ctx.compute_score(params, now=time.time() + 100 * 86400)
        self.assertGreater(score, 0)
        self.assertGreaterEqual(score, params.importance_floor * ctx.importance)

    def test_to_dict_roundtrip(self):
        ctx = Context(uri="/test/1", abstract="hello", importance=0.7, tags=["a", "b"])
        d = ctx.to_dict()
        ctx2 = Context.from_dict(d)
        self.assertEqual(ctx2.uri, ctx.uri)
        self.assertEqual(ctx2.tags, ctx.tags)

    def test_l0_l1_l2(self):
        ctx = Context(abstract="short", overview="medium length", content="full content here")
        self.assertEqual(ctx.to_l0(), "short")
        self.assertEqual(ctx.to_l1(), "medium length")
        self.assertEqual(ctx.to_l2(), "full content here")


class TestSQLiteStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.tmp)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_put_get(self):
        ctx = Context(uri="/test/1", abstract="hello")
        self.store.put(ctx)
        got = self.store.get("/test/1")
        self.assertIsNotNone(got)
        self.assertEqual(got.abstract, "hello")

    def test_delete(self):
        ctx = Context(uri="/test/del", abstract="bye")
        self.store.put(ctx)
        self.assertTrue(self.store.delete("/test/del"))
        self.assertIsNone(self.store.get("/test/del"))

    def test_search_text(self):
        self.store.put(Context(uri="/a", abstract="Frankie likes whisky"))
        self.store.put(Context(uri="/b", abstract="Amber likes coffee"))
        results = self.store.search_text("Frankie")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].uri, "/a")

    def test_search_tags(self):
        self.store.put(Context(uri="/a", tags=["搞钱", "医美"]))
        self.store.put(Context(uri="/b", tags=["技术"]))
        results = self.store.search_by_tag("搞钱")
        self.assertEqual(len(results), 1)

    def test_time_range(self):
        now = time.time()
        self.store.put(Context(uri="/old", event_time=now - 86400 * 30))
        self.store.put(Context(uri="/new", event_time=now))
        results = self.store.search_by_time_range(now - 86400, now + 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].uri, "/new")

    def test_links(self):
        self.store.put(Context(uri="/a"))
        self.store.put(Context(uri="/b"))
        self.store.add_link("/a", "/b", "related")
        links = self.store.get_links("/a")
        self.assertEqual(len(links), 1)

    def test_count_stats(self):
        self.store.put(Context(uri="/a", context_type="memory"))
        self.store.put(Context(uri="/b", context_type="entity"))
        self.assertEqual(self.store.count(), 2)
        stats = self.store.stats()
        self.assertEqual(stats["total"], 2)

    def test_touch(self):
        self.store.put(Context(uri="/t", access_count=0))
        self.store.touch("/t")
        ctx = self.store.get("/t")
        self.assertEqual(ctx.access_count, 1)


class TestAmberMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.mem = AmberMemory(db_path=self.tmp)

    def tearDown(self):
        self.mem.close()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_remember_recall(self):
        self.mem.remember("Frankie喜欢泰斯卡威士忌", importance=0.7, tags=["偏好"])
        results = self.mem.recall("Frankie")
        self.assertGreater(len(results), 0)
        self.assertIn("Frankie", results[0][0].content)

    def test_top(self):
        self.mem.remember("important", importance=0.9)
        self.mem.remember("trivial", importance=0.1)
        top = self.mem.top(2)
        self.assertEqual(len(top), 2)
        self.assertGreater(top[0][1], top[1][1])

    def test_forget(self):
        ctx = self.mem.remember("temp memory")
        self.assertTrue(self.mem.forget(ctx.uri))
        self.assertIsNone(self.mem.get(ctx.uri))

    def test_stats(self):
        self.mem.remember("test")
        stats = self.mem.stats()
        self.assertEqual(stats["total"], 1)

    def test_source_layer(self):
        sid = self.mem.add_source("text", "diary", raw_content="今天天气不错，和Frankie聊了创业方向")
        self.assertIsNotNone(sid)
        src = self.mem.store.get_source(sid)
        self.assertEqual(src["type"], "text")
        self.assertEqual(src["origin"], "diary")
        # Process
        count = self.mem.process_sources()
        self.assertEqual(count, 1)
        # Should be marked processed
        unprocessed = self.mem.store.list_unprocessed_sources()
        self.assertEqual(len(unprocessed), 0)

    def test_taboo_system(self):
        self.mem.remember("外公陈伯年2018年去世", importance=0.9)
        self.mem.remember("今天吃了火锅", importance=0.3)
        # Add taboo
        tid = self.mem.add_taboo("外公", description="不主动提起")
        taboos = self.mem.list_taboos()
        self.assertEqual(len(taboos), 1)
        # Recall with taboo filter
        results = self.mem.recall("外公", respect_taboos=True)
        self.assertEqual(len(results), 0)
        # Recall without taboo filter
        results = self.mem.recall("外公", respect_taboos=False)
        self.assertGreater(len(results), 0)
        # Remove taboo
        self.assertTrue(self.mem.remove_taboo(tid))

    def test_source_taboo_filter(self):
        """Sources matching taboos should not be auto-processed."""
        self.mem.add_taboo("秘密项目")
        sid = self.mem.add_source("text", "telegram", raw_content="秘密项目的进展很顺利")
        count = self.mem.process_sources()
        self.assertEqual(count, 0)  # Should be blocked by taboo

    def test_trace_source(self):
        sid = self.mem.add_source("chat", "wechat", raw_content="子扬说明天见面聊项目进展")
        self.mem.process_sources()
        # Find the memory created from this source
        results = self.mem.recall("明天见面")
        self.assertGreater(len(results), 0)
        # Trace back
        src = self.mem.trace_source(results[0][0].uri)
        self.assertIsNotNone(src)
        self.assertEqual(src["id"], sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
