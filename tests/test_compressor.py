"""Tests for session.compressor — full pipeline with mock LLM."""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import Context
from storage.sqlite_store import SQLiteStore
from session.compressor import SessionCompressor, ExtractionStats
from session.memory_extractor import ALWAYS_MERGE_CATEGORIES


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class CompressorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = SQLiteStore(self.tmp.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmp.name)


class TestExtractionStats(unittest.TestCase):
    """Test ExtractionStats dataclass."""

    def test_default_values(self):
        s = ExtractionStats()
        self.assertEqual(s.created, 0)
        self.assertEqual(s.merged, 0)
        self.assertEqual(s.deleted, 0)
        self.assertEqual(s.skipped, 0)

    def test_str_representation(self):
        s = ExtractionStats(created=2, merged=1, deleted=0, skipped=3)
        text = str(s)
        self.assertIn("created=2", text)
        self.assertIn("merged=1", text)
        self.assertIn("skipped=3", text)


class TestCompressEmptyInput(CompressorTestBase):
    """Test compress with empty/no messages."""

    def test_empty_messages(self):
        comp = SessionCompressor(store=self.store)
        result = run(comp.compress([]))
        self.assertEqual(result, [])

    def test_no_llm_no_extraction(self):
        comp = SessionCompressor(store=self.store, llm_fn=None)
        msgs = [{"role": "user", "content": "Hello"}]
        result = run(comp.compress(msgs))
        self.assertEqual(result, [])


class TestCompressFullPipeline(CompressorTestBase):
    """Test full extract → dedup → store pipeline."""

    def _make_extract_response(self, memories):
        import json
        return json.dumps({"memories": memories})

    def test_single_memory_creation(self):
        extract_resp = self._make_extract_response([{
            "category": "goal",
            "abstract": "学习 Rust",
            "overview": "用户想学 Rust 编程语言",
            "content": "用户表示想在今年学会 Rust",
        }])
        # First call = extraction, second call = importance scoring
        mock_llm = AsyncMock(side_effect=[extract_resp, "0.7"])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "我今年想学 Rust"}]
        result = run(comp.compress(msgs, user="Frankie", session_id="s1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "goal")
        self.assertEqual(self.store.count(), 1)

    def test_multiple_memories_created(self):
        extract_resp = self._make_extract_response([
            {"category": "preference", "abstract": "喜欢咖啡", "overview": "", "content": "喜欢喝咖啡"},
            {"category": "goal", "abstract": "学 Rust", "overview": "", "content": "想学 Rust"},
        ])
        # extraction + 2 importance calls
        mock_llm = AsyncMock(side_effect=[extract_resp, "0.5", "0.6"])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "我喜欢咖啡，今年想学 Rust"}]
        result = run(comp.compress(msgs))
        self.assertEqual(len(result), 2)
        self.assertEqual(self.store.count(), 2)

    def test_extraction_failure_returns_empty(self):
        mock_llm = AsyncMock(side_effect=Exception("LLM down"))
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "test"}]
        result = run(comp.compress(msgs))
        self.assertEqual(result, [])

    def test_importance_scoring_failure_defaults(self):
        extract_resp = self._make_extract_response([{
            "category": "thought", "abstract": "Test", "overview": "", "content": "Test content",
        }])
        # extraction succeeds, importance scoring fails
        mock_llm = AsyncMock(side_effect=[extract_resp, "not a number"])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "test"}]
        result = run(comp.compress(msgs))
        # Should still create the memory with default importance
        self.assertEqual(len(result), 1)


class TestCompressDedup(CompressorTestBase):
    """Test dedup integration in compress pipeline."""

    def test_skip_duplicate(self):
        # Pre-populate with existing memory
        existing = Context(
            uri="/pref/coffee", abstract="喜欢咖啡",
            overview="用户喜欢咖啡", content="用户每天喝咖啡",
            category="preference",
        )
        self.store.put(existing)

        extract_resp = '{"memories": [{"category": "preference", "abstract": "喜欢咖啡", "overview": "用户喜欢咖啡", "content": "用户每天喝咖啡"}]}'
        dedup_resp = '{"decision": "skip", "reason": "duplicate"}'
        mock_llm = AsyncMock(side_effect=[extract_resp, dedup_resp])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "我喜欢咖啡"}]
        result = run(comp.compress(msgs))
        self.assertEqual(len(result), 0)
        self.assertEqual(self.store.count(), 1)  # only the original

    def test_create_with_delete_old(self):
        old = Context(
            uri="/pref/old", abstract="旧偏好",
            content="旧内容", category="preference",
        )
        self.store.put(old)

        extract_resp = '{"memories": [{"category": "preference", "abstract": "新偏好", "overview": "", "content": "新内容"}]}'
        dedup_resp = '{"decision": "create", "reason": "replace", "list": [{"uri": "/pref/old", "decide": "delete", "reason": "outdated"}]}'
        mock_llm = AsyncMock(side_effect=[extract_resp, dedup_resp, "0.6"])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "新偏好"}]
        result = run(comp.compress(msgs))
        self.assertEqual(len(result), 1)
        # Old memory should be deleted
        self.assertIsNone(self.store.get("/pref/old"))


class TestAlwaysMergeCategories(CompressorTestBase):
    """Test that always-merge categories skip dedup."""

    def test_person_category_skips_dedup(self):
        self.assertIn("person", ALWAYS_MERGE_CATEGORIES)
        extract_resp = '{"memories": [{"category": "person", "abstract": "张三是同事", "overview": "", "content": "张三是用户的同事"}]}'
        mock_llm = AsyncMock(side_effect=[extract_resp, "0.6"])
        comp = SessionCompressor(store=self.store, llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "张三是我同事"}]
        result = run(comp.compress(msgs))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "person")

    def test_preference_category_skips_dedup(self):
        self.assertIn("preference", ALWAYS_MERGE_CATEGORIES)


class TestProcessCandidate(CompressorTestBase):
    """Test _process_candidate edge cases."""

    def test_none_decision_no_actions_skips(self):
        from session.memory_extractor import CandidateMemory
        from session.memory_deduplicator import DedupResult, DedupDecision

        comp = SessionCompressor(store=self.store)
        # Mock deduplicator to return NONE with no actions
        async def mock_dedup(candidate):
            return DedupResult(
                decision=DedupDecision.NONE,
                candidate=candidate,
                similar_memories=[],
                actions=[],
            )
        comp.deduplicator.deduplicate = mock_dedup
        candidate = CandidateMemory(
            category="thought", abstract="Test", overview="", content="Test",
        )
        stats = ExtractionStats()
        result = run(comp._process_candidate(candidate, "s1", stats))
        self.assertIsNone(result)
        self.assertEqual(stats.skipped, 1)


if __name__ == "__main__":
    unittest.main()
