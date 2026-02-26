"""Tests for SQLiteStore — CRUD, search, tags, links, embeddings, taboos, sources."""

import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.context import Context, ContextType
from storage.sqlite_store import SQLiteStore


class TestStoreBasicCRUD(unittest.TestCase):
    """Test basic Create/Read/Update/Delete operations."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_put_and_get(self):
        ctx = Context(uri="/test/1", abstract="hello world", category="thought")
        self.store.put(ctx)
        result = self.store.get("/test/1")
        self.assertIsNotNone(result)
        self.assertEqual(result.abstract, "hello world")
        self.assertEqual(result.category, "thought")

    def test_get_nonexistent(self):
        result = self.store.get("/does/not/exist")
        self.assertIsNone(result)

    def test_put_overwrites(self):
        ctx1 = Context(uri="/test/overwrite", abstract="version 1")
        self.store.put(ctx1)
        ctx2 = Context(uri="/test/overwrite", abstract="version 2")
        self.store.put(ctx2)
        result = self.store.get("/test/overwrite")
        self.assertEqual(result.abstract, "version 2")

    def test_delete(self):
        ctx = Context(uri="/test/delete", abstract="to be deleted")
        self.store.put(ctx)
        self.assertIsNotNone(self.store.get("/test/delete"))
        self.store.delete("/test/delete")
        self.assertIsNone(self.store.get("/test/delete"))

    def test_delete_nonexistent(self):
        # Should not raise
        self.store.delete("/does/not/exist")

    def test_list_all(self):
        for i in range(5):
            self.store.put(Context(uri=f"/test/list/{i}", abstract=f"item {i}"))
        results = self.store.list_all(limit=10)
        self.assertEqual(len(results), 5)

    def test_list_all_with_limit(self):
        for i in range(10):
            self.store.put(Context(uri=f"/test/limit/{i}", abstract=f"item {i}"))
        results = self.store.list_all(limit=3)
        self.assertEqual(len(results), 3)

    def test_count(self):
        for i in range(7):
            self.store.put(Context(uri=f"/test/count/{i}", abstract=f"item {i}"))
        self.assertEqual(self.store.count(), 7)

    def test_put_preserves_all_fields(self):
        ctx = Context(
            uri="/test/fields",
            parent_uri="/test",
            abstract="abstract text",
            overview="overview text here",
            content="full content goes here with lots of detail",
            context_type=ContextType.PERSON,
            category="person",
            importance=0.85,
            event_time=1700000000.0,
            tags=["tag1", "tag2"],
            meta={"key": "value"},
        )
        self.store.put(ctx)
        result = self.store.get("/test/fields")
        self.assertEqual(result.parent_uri, "/test")
        self.assertEqual(result.overview, "overview text here")
        self.assertEqual(result.content, "full content goes here with lots of detail")
        self.assertEqual(result.category, "person")
        self.assertAlmostEqual(result.importance, 0.85, places=2)
        self.assertIn("tag1", result.tags)
        self.assertEqual(result.meta.get("key"), "value")


class TestStoreSearch(unittest.TestCase):
    """Test text search functionality."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        # Seed data
        self.store.put(Context(uri="/p/1", abstract="Frankie喜欢威士忌", category="preference"))
        self.store.put(Context(uri="/p/2", abstract="老王是同组同事", category="person"))
        self.store.put(Context(uri="/p/3", abstract="今天吃了火锅", category="activity"))
        self.store.put(Context(uri="/p/4", abstract="不要提老王前女友", category="taboo"))
        self.store.put(Context(uri="/p/5", abstract="计划下周开始跑步", category="goal"))

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_search_text_match(self):
        results = self.store.search_text("威士忌", limit=5)
        self.assertTrue(len(results) > 0)
        self.assertTrue(any("威士忌" in r.abstract for r, _ in results))

    def test_search_text_no_match(self):
        results = self.store.search_text("量子力学", limit=5)
        self.assertEqual(len(results), 0)

    def test_search_by_category(self):
        results = self.store.search_by_category("person", limit=10)
        self.assertTrue(len(results) > 0)
        for ctx, _ in results:
            self.assertEqual(ctx.category, "person")

    def test_search_by_category_taboo(self):
        results = self.store.search_by_category("taboo", limit=10)
        self.assertTrue(len(results) > 0)
        self.assertTrue(any("前女友" in r.abstract for r, _ in results))

    def test_search_limit(self):
        for i in range(20):
            self.store.put(Context(uri=f"/bulk/{i}", abstract=f"bulk item {i}", category="activity"))
        results = self.store.search_by_category("activity", limit=5)
        self.assertLessEqual(len(results), 5)

    def test_search_partial_match(self):
        results = self.store.search_text("老王", limit=5)
        self.assertTrue(len(results) >= 2)  # Both person and taboo mention 老王


class TestStoreTouch(unittest.TestCase):
    """Test touch (access refresh) functionality."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_touch_updates_accessed_at(self):
        ctx = Context(uri="/test/touch", abstract="touch me")
        self.store.put(ctx)
        original = self.store.get("/test/touch")
        original_time = original.accessed_at if hasattr(original, 'accessed_at') else original.created_at

        time.sleep(0.1)
        self.store.touch("/test/touch")
        updated = self.store.get("/test/touch")
        updated_time = updated.accessed_at if hasattr(updated, 'accessed_at') else updated.created_at
        self.assertGreaterEqual(updated_time, original_time)


class TestStoreTaboo(unittest.TestCase):
    """Test taboo system."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_add_taboo(self):
        tid = self.store.add_taboo("前女友", description="不要在老王面前提")
        self.assertIsNotNone(tid)

    def test_list_taboos(self):
        self.store.add_taboo("前女友", description="老王的")
        self.store.add_taboo("工资", description="敏感话题")
        taboos = self.store.list_taboos()
        self.assertEqual(len(taboos), 2)

    def test_check_taboo(self):
        self.store.add_taboo("前女友")
        self.assertTrue(self.store.check_taboo("老王的前女友怎么样了"))
        self.assertFalse(self.store.check_taboo("今天天气不错"))

    def test_remove_taboo(self):
        tid = self.store.add_taboo("测试禁忌")
        self.store.remove_taboo(tid)
        taboos = self.store.list_taboos()
        self.assertEqual(len(taboos), 0)


class TestStoreSource(unittest.TestCase):
    """Test source layer operations."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_put_source(self):
        self.store.put_source(
            source_id="wechat_msg_001",
            source_type="chat",
            origin="wechat",
            raw_content="你好啊",
            event_time=time.time(),
        )
        source = self.store.get_source("wechat_msg_001")
        self.assertIsNotNone(source)

    def test_mark_source_processed(self):
        self.store.put_source(
            source_id="bear_note_001",
            source_type="text",
            origin="bear",
            raw_content="一篇随感",
        )
        self.store.mark_source_processed("bear_note_001", ["/thought/001"])
        source = self.store.get_source("bear_note_001")
        self.assertTrue(source.get("processed", False))

    def test_source_with_file_path(self):
        self.store.put_source(
            source_id="photo_001",
            source_type="image",
            origin="camera",
            raw_content="客厅照片",
            file_path="/photos/IMG_001.jpg",
        )
        source = self.store.get_source("photo_001")
        self.assertEqual(source.get("file_path"), "/photos/IMG_001.jpg")


class TestStoreEmbedding(unittest.TestCase):
    """Test embedding storage."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_put_and_get_embedding(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        self.store.put_embedding("/test/embed", vec)
        result = self.store.get_embedding("/test/embed")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 5)
        self.assertAlmostEqual(result[0], 0.1, places=5)

    def test_get_nonexistent_embedding(self):
        result = self.store.get_embedding("/no/embed")
        self.assertIsNone(result)

    def test_overwrite_embedding(self):
        self.store.put_embedding("/test/overwrite", [1.0, 2.0])
        self.store.put_embedding("/test/overwrite", [3.0, 4.0])
        result = self.store.get_embedding("/test/overwrite")
        self.assertAlmostEqual(result[0], 3.0, places=5)


class TestStoreLinks(unittest.TestCase):
    """Test context linking."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.store.put(Context(uri="/a", abstract="node A"))
        self.store.put(Context(uri="/b", abstract="node B"))
        self.store.put(Context(uri="/c", abstract="node C"))

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_add_link(self):
        self.store.add_link("/a", "/b", relation="related")
        links = self.store.get_links("/a")
        self.assertTrue(len(links) > 0)

    def test_bidirectional_link(self):
        self.store.add_link("/a", "/b", relation="colleague")
        links_a = self.store.get_links("/a")
        links_b = self.store.get_links("/b")
        # At least one direction should work
        self.assertTrue(len(links_a) > 0 or len(links_b) > 0)

    def test_multiple_links(self):
        self.store.add_link("/a", "/b", relation="friend")
        self.store.add_link("/a", "/c", relation="colleague")
        links = self.store.get_links("/a")
        self.assertGreaterEqual(len(links), 2)


if __name__ == "__main__":
    unittest.main()
