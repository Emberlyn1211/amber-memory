"""Tests for storage.sqlite_store — CRUD, search, tags, links, embedding, taboo, source."""

import json
import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import Context, ContextType, DecayParams
from storage.sqlite_store import SQLiteStore


class SQLiteStoreTestBase(unittest.TestCase):
    """Base class that creates a temp DB for each test."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = SQLiteStore(self.tmp.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmp.name)

    def _make_ctx(self, uri="/test/mem/1", **kwargs):
        defaults = dict(
            uri=uri, abstract="Test memory", overview="Overview text",
            content="Full content", context_type="memory",
            category="preference", importance=0.5, tags=["test"],
        )
        defaults.update(kwargs)
        return Context(**defaults)


class TestCRUD(SQLiteStoreTestBase):
    """Test basic CRUD operations."""

    def test_put_and_get(self):
        ctx = self._make_ctx()
        self.store.put(ctx)
        got = self.store.get("/test/mem/1")
        self.assertIsNotNone(got)
        self.assertEqual(got.uri, "/test/mem/1")
        self.assertEqual(got.abstract, "Test memory")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(self.store.get("/does/not/exist"))

    def test_get_by_id(self):
        ctx = self._make_ctx(id="myid123")
        self.store.put(ctx)
        got = self.store.get_by_id("myid123")
        self.assertIsNotNone(got)
        self.assertEqual(got.uri, "/test/mem/1")

    def test_delete(self):
        ctx = self._make_ctx()
        self.store.put(ctx)
        self.assertTrue(self.store.delete("/test/mem/1"))
        self.assertIsNone(self.store.get("/test/mem/1"))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.store.delete("/nope"))

    def test_put_updates_existing(self):
        ctx = self._make_ctx()
        self.store.put(ctx)
        ctx.abstract = "Updated"
        self.store.put(ctx)
        got = self.store.get("/test/mem/1")
        self.assertEqual(got.abstract, "Updated")
        self.assertEqual(self.store.count(), 1)

    def test_touch_increments_access(self):
        ctx = self._make_ctx()
        self.store.put(ctx)
        self.store.touch("/test/mem/1")
        got = self.store.get("/test/mem/1")
        self.assertEqual(got.access_count, 1)

    def test_count(self):
        self.assertEqual(self.store.count(), 0)
        self.store.put(self._make_ctx("/a/1"))
        self.store.put(self._make_ctx("/a/2"))
        self.assertEqual(self.store.count(), 2)


class TestSearch(SQLiteStoreTestBase):
    """Test search operations."""

    def setUp(self):
        super().setUp()
        for i in range(5):
            self.store.put(self._make_ctx(
                uri=f"/test/mem/{i}",
                abstract=f"Memory about topic {i}",
                content=f"Detailed content for memory {i}",
                context_type="memory" if i % 2 == 0 else "person",
                category="preference" if i < 3 else "goal",
                tags=["alpha"] if i < 2 else ["beta"],
                importance=0.1 * (i + 1),
            ))

    def test_search_by_type(self):
        results = self.store.search_by_type("memory")
        self.assertTrue(all(r.context_type == "memory" for r in results))

    def test_search_by_category(self):
        results = self.store.search_by_category("goal")
        self.assertEqual(len(results), 2)

    def test_search_by_tag(self):
        results = self.store.search_by_tag("alpha")
        self.assertEqual(len(results), 2)

    def test_search_text(self):
        results = self.store.search_text("topic 3")
        uris = [r.uri for r in results]
        self.assertIn("/test/mem/3", uris)

    def test_search_text_empty_query(self):
        results = self.store.search_text("x")
        # single char < 2 falls back to full query
        self.assertIsInstance(results, list)

    def test_list_children(self):
        self.store.put(self._make_ctx("/parent/child/1", parent_uri="/parent/child"))
        self.store.put(self._make_ctx("/parent/child/2", parent_uri="/parent/child"))
        children = self.store.list_children("/parent/child")
        self.assertEqual(len(children), 2)

    def test_search_by_time_range(self):
        now = time.time()
        self.store.put(self._make_ctx("/time/1", event_time=now - 100))
        self.store.put(self._make_ctx("/time/2", event_time=now - 50))
        self.store.put(self._make_ctx("/time/3", event_time=now + 1000))
        results = self.store.search_by_time_range(now - 200, now)
        uris = [r.uri for r in results]
        self.assertIn("/time/1", uris)
        self.assertIn("/time/2", uris)
        self.assertNotIn("/time/3", uris)

    def test_get_top_memories(self):
        top = self.store.get_top_memories(limit=3)
        self.assertLessEqual(len(top), 3)
        scores = [s for _, s in top]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_get_decayed(self):
        old = self._make_ctx("/old/1", importance=0.01)
        old.last_accessed = time.time() - 365 * 86400
        self.store.put(old)
        decayed = self.store.get_decayed(threshold=0.5)
        uris = [c.uri for c in decayed]
        self.assertIn("/old/1", uris)

    def test_stats(self):
        s = self.store.stats()
        self.assertIn("total", s)
        self.assertIn("by_type", s)
        self.assertEqual(s["total"], 5)


class TestLinks(SQLiteStoreTestBase):
    """Test link operations."""

    def test_add_and_get_links(self):
        self.store.put(self._make_ctx("/a"))
        self.store.put(self._make_ctx("/b"))
        self.store.add_link("/a", "/b", "related", 1.0)
        links = self.store.get_links("/a")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["target_uri"], "/b")

    def test_link_updates_link_count(self):
        self.store.put(self._make_ctx("/x"))
        self.store.put(self._make_ctx("/y"))
        self.store.add_link("/x", "/y")
        ctx = self.store.get("/x")
        self.assertGreaterEqual(ctx.link_count, 1)

    def test_delete_removes_links(self):
        self.store.put(self._make_ctx("/p"))
        self.store.put(self._make_ctx("/q"))
        self.store.add_link("/p", "/q")
        self.store.delete("/p")
        links = self.store.get_links("/p")
        self.assertEqual(len(links), 0)


class TestEmbeddings(SQLiteStoreTestBase):
    """Test embedding storage."""

    def test_put_and_get_embedding(self):
        self.store.put(self._make_ctx("/emb/1"))
        vec = b"\x00\x01\x02\x03"
        self.store.put_embedding("/emb/1", vec, model="test")
        got = self.store.get_embedding("/emb/1")
        self.assertEqual(got, vec)

    def test_get_missing_embedding(self):
        self.assertIsNone(self.store.get_embedding("/nope"))


class TestTaboo(SQLiteStoreTestBase):
    """Test taboo system."""

    def test_add_and_list_taboos(self):
        tid = self.store.add_taboo("外公", "不要提外公", "global")
        taboos = self.store.list_taboos()
        self.assertEqual(len(taboos), 1)
        self.assertEqual(taboos[0]["pattern"], "外公")

    def test_remove_taboo(self):
        tid = self.store.add_taboo("secret")
        self.assertTrue(self.store.remove_taboo(tid))
        self.assertEqual(len(self.store.list_taboos(active_only=True)), 0)

    def test_check_taboos_triggered(self):
        self.store.add_taboo("敏感词")
        triggered = self.store.check_taboos("这段文字包含敏感词")
        self.assertEqual(len(triggered), 1)

    def test_check_taboos_not_triggered(self):
        self.store.add_taboo("敏感词")
        triggered = self.store.check_taboos("这段文字很正常")
        self.assertEqual(len(triggered), 0)


class TestSourceLayer(SQLiteStoreTestBase):
    """Test source layer operations."""

    def test_put_and_get_source(self):
        self.store.put_source("src1", "chat", "wechat", raw_content="hello")
        src = self.store.get_source("src1")
        self.assertIsNotNone(src)
        self.assertEqual(src["type"], "chat")
        self.assertEqual(src["raw_content"], "hello")

    def test_list_unprocessed(self):
        self.store.put_source("s1", "chat", "wechat")
        self.store.put_source("s2", "chat", "telegram")
        unprocessed = self.store.list_unprocessed_sources()
        self.assertEqual(len(unprocessed), 2)

    def test_mark_processed(self):
        self.store.put_source("s1", "chat", "wechat")
        self.store.mark_source_processed("s1", ["/mem/1"])
        unprocessed = self.store.list_unprocessed_sources()
        self.assertEqual(len(unprocessed), 0)

    def test_source_count(self):
        self.assertEqual(self.store.source_count(), 0)
        self.store.put_source("s1", "chat", "wechat")
        self.assertEqual(self.store.source_count(), 1)

    def test_context_manager(self):
        with SQLiteStore(self.tmp.name) as s:
            s.put(self._make_ctx("/ctx/mgr"))
        # re-open to verify
        s2 = SQLiteStore(self.tmp.name)
        self.assertIsNotNone(s2.get("/ctx/mgr"))
        s2.close()


if __name__ == "__main__":
    unittest.main()
